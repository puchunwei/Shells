"""Private, file-backed Claude connection profiles.

Public methods return private data. Call ``redact`` at every display boundary.
Only explicitly registered fields are managed; unrelated Claude settings survive.
"""
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urlsplit
import uuid


MODEL_ENV_KEYS = (
    'ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_DEFAULT_MODEL',
    'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
    'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL',
    'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE',
    'ANTHROPIC_CUSTOM_MODEL_OPTION',
)
_SLOT_METADATA = tuple('ANTHROPIC_DEFAULT_' + slot + '_MODEL' + suffix
    for slot in ('OPUS', 'SONNET', 'HAIKU', 'FABLE')
    for suffix in ('_NAME', '_DESCRIPTION', '_SUPPORTED_CAPABILITIES'))
MANAGED_ENV_KEYS = (
    'ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
) + MODEL_ENV_KEYS + _SLOT_METADATA + (
    'ANTHROPIC_CUSTOM_MODEL_OPTION_NAME',
    'ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION',
    'ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES',
)
TOP_LEVEL_KEYS = ('model', 'modelPicker')
_AUTH_KEYS = {'api_key': 'ANTHROPIC_API_KEY', 'bearer_token': 'ANTHROPIC_AUTH_TOKEN'}
_PROVIDER_KEYS = ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX',
                  'CLAUDE_CODE_USE_FOUNDRY')
_OAUTH_KEYS = ('CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN_FD')
_HELPER_KEYS = ('apiKeyHelper', 'awsAuthRefresh', 'awsCredentialExport')
_SYSTEM_MANAGED_PATH = Path('/etc/claude-code/managed-settings.json')
_RESERVED_NAMES = frozenset(('status', 'list', 'use', 'add', 'save', 'import',
    'edit', 'remove', 'undo', 'doctor', 'slots', 'init', 'single', 'models',
    'version', 'help', 'migrate', 'update', 'run', 'preset'))


def _plain(value, field, nonempty=False, model=False):
    if not isinstance(value, str) or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in value):
        raise ValueError('Invalid string in ' + field)
    if nonempty and not value.strip():
        raise ValueError('Missing value in ' + field)
    if model and any(c.isspace() for c in value):
        raise ValueError('Invalid model in ' + field)


def _active(value):
    return bool(value) and str(value).lower() not in ('0', 'false', 'no', 'off')


def _auth_conflicts(settings, source):
    env = settings.get('env', {})
    if not isinstance(env, dict):
        raise ValueError('env must be an object')
    conflicts = [{'source': source, 'key': key} for key in _HELPER_KEYS if settings.get(key)]
    conflicts.extend({'source': source, 'key': key} for key in _PROVIDER_KEYS if _active(env.get(key)))
    conflicts.extend({'source': source, 'key': key} for key in _OAUTH_KEYS if env.get(key))
    return conflicts


def _fail_conflicts(conflicts):
    if conflicts:
        raise ValueError('Unsupported authentication or managed configuration: ' +
                         ', '.join(c['source'] + ':' + c['key'] for c in conflicts))


def _unwrap(settings):
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object')
    # Accept exported product profiles and legacy flat snapshots as well.
    if 'settings' in settings and 'env' not in settings:
        settings = settings['settings']
        if not isinstance(settings, dict):
            raise ValueError('Profile settings must be an object')
    flat_keys = MANAGED_ENV_KEYS + _PROVIDER_KEYS + _OAUTH_KEYS
    if 'env' not in settings and any(key in settings for key in flat_keys):
        settings = dict(settings, env={key: settings[key] for key in flat_keys if key in settings})
    return settings


def _project(settings):
    env = settings.get('env', {})
    if not isinstance(env, dict):
        raise ValueError('env must be an object')
    selected = {'env': {key: copy.deepcopy(env[key]) for key in MANAGED_ENV_KEYS if key in env}}
    for key, value in selected['env'].items():
        _plain(value, key)
        if key in MODEL_ENV_KEYS and key != 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE':
            _plain(value, key, model=True)
    base = selected['env'].get('ANTHROPIC_BASE_URL', '')
    if base:
        try:
            url = urlsplit(base)
            valid = url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password
        except ValueError:
            valid = False
        if not valid or any(c.isspace() for c in base):
            raise ValueError('Invalid ANTHROPIC_BASE_URL')
    for key in TOP_LEVEL_KEYS:
        if key in settings:
            selected[key] = copy.deepcopy(settings[key])
    if 'model' in selected:
        _plain(selected['model'], 'model', nonempty=True, model=True)
    if 'modelPicker' in selected:
        picker = selected['modelPicker']
        if not isinstance(picker, dict):
            raise ValueError('modelPicker must be an object')
        if 'replaceBuiltInOptions' in picker and not isinstance(picker['replaceBuiltInOptions'], bool):
            raise ValueError('modelPicker.replaceBuiltInOptions must be a boolean')
        if 'options' in picker:
            if not isinstance(picker['options'], list):
                raise ValueError('modelPicker.options must be an array')
            for option in picker['options']:
                if not isinstance(option, dict):
                    raise ValueError('modelPicker option must be an object')
                _plain(option.get('model'), 'modelPicker.options.model', nonempty=True, model=True)
                if 'label' in option:
                    _plain(option['label'], 'modelPicker.options.label', nonempty=True)
                for key in ('description', 'behavesAs'):
                    if key in option:
                        _plain(option[key], 'modelPicker.options.' + key, nonempty=(key == 'behavesAs'))
    # Reject non-JSON values in advanced fields, without echoing their contents.
    try:
        json.dumps(selected, allow_nan=False)
    except (ValueError, TypeError):
        raise ValueError('Settings must contain valid JSON values') from None
    return selected


def extract_settings(settings, auth=None):
    """Validate and copy managed settings; reject unsupported auth sources."""
    settings = _unwrap(settings)
    _fail_conflicts(_auth_conflicts(settings, 'source'))
    selected = _project(settings)
    if auth is not None and auth not in _AUTH_KEYS:
        raise ValueError('auth must be api_key or bearer_token')
    env = selected['env']
    present = [kind for kind, key in _AUTH_KEYS.items() if env.get(key)]
    if len(present) > 1 and auth is None:
        raise ValueError('Both static authentication values exist; select auth explicitly')
    if auth is not None:
        for kind, key in _AUTH_KEYS.items():
            if kind != auth:
                env[key] = ''
    return selected


def _sensitive(key):
    compact = re.sub('[^a-z0-9]', '', str(key).lower())
    return any(word in compact for word in ('token', 'apikey', 'password', 'secret', 'credential', 'authorization'))


def redact(value):
    """Return a recursive public copy, including secret-bearing conflict rows."""
    if isinstance(value, dict):
        secret_row = _sensitive(value.get('key', ''))
        return {key: ('<redacted>' if item else item)
                if ((_sensitive(key) and not (str(key).endswith('_present') and isinstance(item, bool))) or
                    (secret_row and key in ('actual', 'expected', 'value')))
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return copy.deepcopy(value)


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _snapshot(path):
    try:
        with path.open('rb') as handle:
            contents = handle.read()
            info = os.fstat(handle.fileno())
        return contents, (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, contents)
    except FileNotFoundError:
        return None, None


def _read_json(path, absent=None):
    contents, stamp = _snapshot(path)
    if contents is None:
        return copy.deepcopy(absent), stamp
    try:
        value = json.loads(contents)
    except (ValueError, UnicodeError):
        raise ValueError('Invalid JSON in ' + path.name) from None
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object in ' + path.name)
    return value, stamp


_NO_EXPECTATION = object()


class _ReplacedWriteError(OSError):
    """Replacement completed, but directory durability was not confirmed."""


def _atomic_json(path, value, expected=_NO_EXPECTATION):
    """Stage privately and check the original file immediately before replacement."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    replaced = False
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        if expected is not _NO_EXPECTATION and _snapshot(path)[1] != expected:
            raise ValueError('File changed externally; retry: ' + path.name)
        os.replace(temporary, path)
        replaced = True
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        if replaced:
            raise _ReplacedWriteError('File replaced but directory sync failed: ' + path.name) from None
        raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}', name):
        raise ValueError('Profile name must be 1-48 lowercase letters, digits, underscores or hyphens; start with a letter or digit')
    if name in _RESERVED_NAMES:
        raise ValueError('Profile name is a reserved command word')
    return name


class ProfileStore:
    def __init__(self, config_dir=None, root=None):
        self.config_dir = Path(config_dir if config_dir is not None else
            os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser().resolve()
        self.root = Path(root if root is not None else
            Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'ccswitch').expanduser().resolve()
        self.settings_path = self.config_dir / 'settings.json'
        self.defaults_path = self.config_dir / 'ccswitch-defaults.json'

    @contextmanager
    def _locked(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        for name in ('profiles', 'backups'):
            directory = self.root / name
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)
        descriptor = os.open(str(self.root / '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _profile_path(self, name):
        return self.root / 'profiles' / (_name(name) + '.json')

    def get(self, name):
        profile, _ = _read_json(self._profile_path(name))
        if profile is None:
            raise ValueError('Profile does not exist: ' + name)
        if (profile.get('schema_version') != 1 or profile.get('name') != name or
                not isinstance(profile.get('revision'), int) or profile['revision'] < 1):
            raise ValueError('Invalid profile schema: ' + name)
        settings = extract_settings(profile.get('settings'))
        if settings != profile['settings']:
            raise ValueError('Unexpected unmanaged fields in profile: ' + name)
        return profile

    def list_profiles(self):
        directory = self.root / 'profiles'
        return [self.get(path.stem) for path in sorted(directory.glob('*.json'))]

    def _save(self, name, settings, replace=False, auth=None, catalog='manual', source='manual'):
        path = self._profile_path(name)
        projected = extract_settings(settings, auth=auth)
        _plain(catalog, 'catalog', nonempty=True)
        _plain(source, 'source', nonempty=True)
        previous, stamp = _read_json(path)
        if previous is not None and not replace:
            raise ValueError('Profile already exists: ' + name)
        revision = self.get(name)['revision'] + 1 if previous is not None else 1
        present = [kind for kind, key in _AUTH_KEYS.items() if projected['env'].get(key)]
        profile = {'schema_version': 1, 'name': name, 'revision': revision,
                   'auth_type': present[0] if present else 'incomplete',
                   'catalog': catalog, 'source': source, 'settings': projected}
        _atomic_json(path, profile, expected=stamp)
        return profile

    def save(self, name, settings, replace=False, auth=None, catalog='manual', source='manual'):
        # Validate before creating even a lock or directory for invalid input.
        _name(name)
        extract_settings(settings, auth=auth)
        with self._locked():
            return self._save(name, settings, replace, auth, catalog, source)

    def migrate(self):
        result = {'created': [], 'conflicts': [], 'warnings': []}
        with self._locked():
            for name, path in (('current', self.settings_path), ('default', self.defaults_path)):
                if not path.exists():
                    continue
                try:
                    settings, _ = _read_json(path)
                    selected = extract_settings(settings)
                    destination = self._profile_path(name)
                    if destination.exists():
                        if self.get(name)['settings'] != selected:
                            result['conflicts'].append(name)
                        continue
                    self._save(name, settings, source='legacy:' + name)
                    result['created'].append(name)
                except (ValueError, OSError) as error:
                    # Never include source values or raw JSON parse diagnostics.
                    result['warnings'].append({'source': name, 'reason':
                        str(error) if isinstance(error, ValueError) else 'Could not read or save source'})
        return result

    def _state(self):
        state, stamp = _read_json(self.root / 'state.json', absent={'schema_version': 1, 'targets': {}})
        if state.get('schema_version') != 1 or not isinstance(state.get('targets'), dict):
            raise ValueError('Invalid state schema')
        return state, stamp

    def _backup_path(self):
        return self.root / 'backups' / (hashlib.sha256(str(self.settings_path).encode()).hexdigest() + '.json')

    def _record_recovery(self, before, after_digest, previous_state, target_existed, operation):
        backup_id = uuid.uuid4().hex
        backups, stamp = _read_json(self._backup_path(), absent={'records': []})
        if not isinstance(backups.get('records'), list):
            raise ValueError('Invalid recovery record schema')
        backups['records'] = (backups['records'] + [{
            'id': backup_id, 'target': str(self.settings_path), 'before': before,
            'target_existed': target_existed, 'after_digest': after_digest,
            'previous_state': previous_state, 'operation': operation,
        }])[-10:]
        _atomic_json(self._backup_path(), backups, expected=stamp)
        return backup_id

    def _external_conflicts(self, settings):
        conflicts = _auth_conflicts(settings, 'settings')
        conflicts.extend(_auth_conflicts({'env': dict(os.environ)}, 'shell'))
        managed_paths = [self.config_dir / 'managed-settings.json', _SYSTEM_MANAGED_PATH]
        managed_paths.extend(sorted((self.config_dir / 'managed-settings.d').glob('*.json')))
        managed_paths.extend(sorted((_SYSTEM_MANAGED_PATH.parent / 'managed-settings.d').glob('*.json')))
        for path in managed_paths:
            if not path.exists():
                continue
            managed, _ = _read_json(path)
            conflicts.extend(_auth_conflicts(managed, 'managed:' + str(path)))
            env = managed.get('env', {})
            conflicts.extend({'source': 'managed:' + str(path), 'key': key}
                             for key in MANAGED_ENV_KEYS if key in env)
            conflicts.extend({'source': 'managed:' + str(path), 'key': key}
                             for key in TOP_LEVEL_KEYS if key in managed)
        return conflicts

    @staticmethod
    def _merge(current, selected):
        merged = copy.deepcopy(current)
        env = merged.setdefault('env', {})
        if not isinstance(env, dict):
            raise ValueError('env must be an object')
        # Explicit empty values also clear hot-loaded and inherited authentication.
        env.update({key: selected.get('env', {}).get(key, '') for key in MANAGED_ENV_KEYS})
        for key in TOP_LEVEL_KEYS:
            if key in selected:
                merged[key] = copy.deepcopy(selected[key])
            else:
                merged.pop(key, None)
        return merged

    def _result(self, profile, written, backup, success=True, warning=None):
        return {'success': success, 'applied': True, 'partial': not success,
                'profile': profile, 'target': str(self.settings_path),
                'env': {key: written['env'][key] for key in MANAGED_ENV_KEYS} if success else {},
                'backup': str(self._backup_path()), 'backup_id': backup,
                'warnings': [] if success else [warning or 'Settings updated but state update or sync failed; recovery backup retained']}

    def apply(self, name, settings_override=None):
        with self._locked():
            profile = self.get(name)
            selected = extract_settings(profile['settings'] if settings_override is None else settings_override)
            if not any(selected['env'].get(key) for key in _AUTH_KEYS.values()):
                raise ValueError('Static authentication is incomplete')
            if not selected['env'].get('ANTHROPIC_BASE_URL'):
                raise ValueError('ANTHROPIC_BASE_URL is required')
            state, state_stamp = self._state()
            current, target_stamp = _read_json(self.settings_path, absent={})
            _fail_conflicts(self._external_conflicts(current))
            before = _project(current)
            written = self._merge(current, selected)
            applied_digest = _digest(_project(written))
            target = str(self.settings_path)
            backup_id = self._record_recovery(before, applied_digest,
                state['targets'].get(target), target_stamp is not None, 'apply')
            try:
                _atomic_json(self.settings_path, written, expected=target_stamp)
            except _ReplacedWriteError:
                return self._result(name, written, backup_id, success=False,
                    warning='Settings updated but target directory sync failed; state not updated; recovery backup retained')
            state['targets'][target] = {'profile': name, 'revision': profile['revision'],
                'saved_digest': _digest(profile['settings']), 'applied_digest': applied_digest,
                'backup_id': backup_id}
            try:
                _atomic_json(self.root / 'state.json', state, expected=state_stamp)
            except (OSError, ValueError):
                return self._result(name, written, backup_id, success=False)
            return self._result(name, written, backup_id)

    def undo(self):
        with self._locked():
            state, state_stamp = self._state()
            target = str(self.settings_path)
            entry = state['targets'].get(target)
            if not entry:
                raise ValueError('No applied configuration to undo')
            current, target_stamp = _read_json(self.settings_path, absent={})
            if _digest(_project(current)) != entry['applied_digest']:
                raise ValueError('Managed settings changed externally; undo refused')
            _fail_conflicts(self._external_conflicts(current))
            backups, _ = _read_json(self._backup_path(), absent={'records': []})
            record = next((r for r in reversed(backups['records']) if r['id'] == entry['backup_id']), None)
            if record is None:
                raise ValueError('Recovery record no longer available')
            written = self._merge(current, record['before'])
            backup_id = self._record_recovery(_project(current), _digest(_project(written)),
                entry, target_stamp is not None, 'undo')
            previous = record['previous_state']
            try:
                _atomic_json(self.settings_path, written, expected=target_stamp)
            except _ReplacedWriteError:
                return self._result(previous['profile'] if previous else None, written, backup_id, success=False,
                    warning='Settings updated but target directory sync failed; state not updated; recovery backup retained')
            if previous is None:
                state['targets'].pop(target)
            else:
                state['targets'][target] = previous
            try:
                _atomic_json(self.root / 'state.json', state, expected=state_stamp)
            except (OSError, ValueError):
                return self._result(previous['profile'] if previous else None, written, backup_id, success=False)
            return self._result(previous['profile'] if previous else None, written, backup_id)

    def status(self):
        state, _ = self._state()
        entry = state['targets'].get(str(self.settings_path))
        warnings = []
        try:
            current, target_stamp = _read_json(self.settings_path, absent={})
            projected = _project(current)
            auth_conflicts = self._external_conflicts(current)
            file_matches = bool(entry) and _digest(projected) == entry['applied_digest']
        except (ValueError, OSError):
            target_stamp = None
            projected, auth_conflicts, file_matches = {'env': {}}, [], False
            warnings.append('Could not inspect target or managed settings')
        saved_matches = False
        if entry:
            try:
                profile = self.get(entry['profile'])
                saved_matches = (profile['revision'] == entry['revision'] and
                                 _digest(profile['settings']) == entry['saved_digest'])
            except (ValueError, OSError):
                warnings.append('Applied profile is unavailable or invalid')
        matching_profiles = []
        if not entry and target_stamp is not None and not warnings:
            # Imported settings can already match a saved profile without a
            # switch. Compare managed values, treating cleared env as unset,
            # while keeping actual application/undo history untouched.
            try:
                normalized = self._merge({}, projected)
                matching_profiles = [profile['name'] for profile in self.list_profiles()
                    if self._merge({}, profile['settings']) == normalized]
            except (ValueError, OSError):
                warnings.append('Could not inspect saved profiles')
        shell_conflicts = [{'key': key, 'actual': os.environ[key],
            'expected': projected['env'].get(key, '')} for key in MANAGED_ENV_KEYS
            if key in os.environ and os.environ[key] != projected['env'].get(key, '')]
        return {'target': str(self.settings_path), 'root': str(self.root),
                'profile': entry['profile'] if entry else None,
                'revision': entry['revision'] if entry else None,
                'matching_profiles': matching_profiles,
                'file_matches': file_matches, 'saved_matches': saved_matches,
                'shell_conflicts': shell_conflicts, 'auth_conflicts': auth_conflicts,
                'credentials_present': (self.config_dir / '.credentials.json').exists(),
                'target_exists': self.settings_path.exists(), 'warnings': warnings}

    def remove(self, name):
        _name(name)
        with self._locked():
            state, _ = self._state()
            if any(entry.get('profile') == name for entry in state['targets'].values()):
                raise ValueError('配置正在使用，请先用 ccswitch use 切换到其他配置后再删除：' + name)
            self.get(name)
            self._profile_path(name).unlink()
        return {'removed': name}
