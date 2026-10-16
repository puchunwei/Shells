"""Command orchestration. Every ordinary output crosses the redaction boundary."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys
import unicodedata

from ccswitch_profiles import MANAGED_ENV_KEYS, ProfileStore, extract_settings, redact, _atomic_json
from ccswitch_slots import SLOTS, edit_menu, set_slot, unify_slots
import ccswitch_ui as ui


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse includes rejected argv values in its normal error. Never echo
        # arguments: a user may accidentally pass a secret as an unsupported flag.
        raise UsageError('Invalid command arguments; run ccswitch help')


def parser():
    root = Parser(prog='ccswitch', description='Private Claude connection profiles and model slots')
    commands = root.add_subparsers(dest='command')
    for name in ('status', 'list', 'undo', 'doctor', 'migrate', 'models', 'version', 'help'):
        commands.add_parser(name)
    use = commands.add_parser('use')
    use.add_argument('name', nargs='?')
    for name in ('add', 'save', 'import', 'edit'):
        cmd = commands.add_parser(name)
        cmd.add_argument('name', nargs='?')
        cmd.add_argument('--from', dest='source')
        cmd.add_argument('--auth', choices=('api_key', 'bearer_token'))
        cmd.add_argument('--replace', action='store_true')
    remove = commands.add_parser('remove')
    remove.add_argument('name')
    init = commands.add_parser('init')
    init.add_argument('--replace', action='store_true')
    init.add_argument('--auth', choices=('api_key', 'bearer_token'))
    default = commands.add_parser('default')
    default.add_argument('model', nargs='?')
    default.add_argument('--restore', action='store_true')
    single = commands.add_parser('single')
    single.add_argument('model')
    slots = commands.add_parser('slots')
    slots.add_argument('parts', nargs='*', help='[NAME] | edit [NAME] | set NAME SLOT MODEL | menu ACTION NAME')
    slots.add_argument('--apply', action='store_true')
    slots.add_argument('--model')
    slots.add_argument('--label')
    slots.add_argument('--description')
    slots.add_argument('--behaves-as')
    slots.add_argument('--index', type=int)
    slots.add_argument('--to', type=int)
    slots.add_argument('--replace-builtins', choices=('true', 'false'))
    return root


def output_options(argv):
    # Shared hidden options may appear before or after nested commands. They
    # cannot carry authentication and are removed before command parsing.
    remaining, json_mode, shell_output = [], False, None
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == '--json':
            json_mode = True
        elif item == '--shell-output':
            if index + 1 >= len(argv) or shell_output is not None:
                raise UsageError('Invalid shell output option; run ccswitch help')
            index += 1
            shell_output = argv[index]
        else:
            remaining.append(item)
        index += 1
    return remaining, json_mode, shell_output


def emit(value, json_mode=False):
    public = redact(value)
    # JSON is also the readable fallback for rich settings/status structures.
    print(json.dumps(public, ensure_ascii=False, indent=None if json_mode else 2))


def read_source(source, store):
    path = store.settings_path if source == 'current' else Path(source).expanduser()
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise ValueError('Invalid source JSON') from None
    if not isinstance(value, dict):
        raise ValueError('Source must be a JSON object')
    return value


def migrate(store, explicit=False):
    # Use the Store's lock, state snapshot and atomic writer so even a missing
    # first target counts as a completed attempt. Applying profiles preserves
    # this state metadata. Explicit migrate always inspects both legacy sources.
    state, _ = store._state()
    targets = state.get('migration_attempted', [])
    if not isinstance(targets, list) or any(not isinstance(item, str) for item in targets):
        raise ValueError('Invalid migration state')
    target = str(store.settings_path)
    if not explicit and target in targets:
        return {'created': [], 'conflicts': [], 'warnings': []}
    result = store.migrate()
    with store._locked():
        state, stamp = store._state()
        targets = state.setdefault('migration_attempted', [])
        if not isinstance(targets, list) or any(not isinstance(item, str) for item in targets):
            raise ValueError('Invalid migration state')
        if target not in targets:
            targets.append(target)
            _atomic_json(store.root / 'state.json', state, expected=stamp)
    return result


def automatic_migration(store):
    return migrate(store)


def migration_preview(store):
    existing = {profile['name'] for profile in store.list_profiles()}
    return [name for name, path in (('current', store.settings_path), ('default', store.defaults_path))
            if path.exists() and name not in existing]


def write_shell_output(filename, env):
    if set(env) != set(MANAGED_ENV_KEYS):
        raise ValueError('Incomplete shell synchronization data')
    for value in env.values():
        if not isinstance(value, str) or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in value):
            raise ValueError('Unsafe shell synchronization data')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(filename, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Shell output must be a regular file')
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            descriptor = -1
            for key in MANAGED_ENV_KEYS:
                stream.write(key + '=' + env[key] + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def show_profile(profile, json_mode, *, saved=False, target=None):
    if json_mode:
        emit(profile, True)
    else:
        if saved:
            print('Saved ' + profile['name'] + '.')
        ui.preview(profile, target)


def show_status(store, status, json_mode):
    if json_mode:
        emit(status, True)
        return
    print('Profile: ' + (status['profile'] or '(unrecognized)'))
    print('Global target: ' + status['target'])
    print('Settings: ' + ('matches applied profile' if status['file_matches'] else 'unrecognized or changed'))
    print('Saved profile: ' + ('matches applied revision' if status['saved_matches'] else 'different or unavailable'))
    if status['profile']:
        try:
            saved = store.get(status['profile'])
            ui.preview(saved)
            current = extract_settings(read_source('current', store))
            expected = saved['settings']
            keys = [key for key in MANAGED_ENV_KEYS
                    if current.get('env', {}).get(key, '') != expected.get('env', {}).get(key, '')]
            keys.extend(key for key in ('model', 'modelPicker') if current.get(key) != expected.get(key))
            if keys:
                print('Drift keys: ' + ', '.join(keys))
        except (ValueError, OSError):
            pass
    for kind in ('shell_conflicts', 'auth_conflicts'):
        if status[kind]:
            print(kind.replace('_', ' ').capitalize() + ': ' + ', '.join(row['key'] for row in status[kind]))
    if status.get('migration_available'):
        print('Migration available: ' + ', '.join(status['migration_available']))
    for warning in status.get('warnings', []):
        print('Warning: ' + warning)


def finish_apply(result, json_mode, shell_output, *, saved=None, settings=None, failure_code=1):
    result = dict(result)
    if saved is not None:
        result.update(saved=True, saved_profile=saved)
        settings = saved['settings']
    complete = result.get('success') and not result.get('partial')
    if complete and shell_output is not None:
        try:
            write_shell_output(shell_output, result['env'])
        except (OSError, ValueError):
            result.update(success=False, shell_synced=False)
            result['warnings'] = list(result.get('warnings', [])) + ['file applied; shell not synced: output file write failed']
            complete = False
    if json_mode:
        emit(result, True)
    else:
        prefix = ('Saved ' + saved['name'] + '; ') if saved is not None else ''
        if complete:
            print(prefix + 'Applied ' + (result.get('profile') or 'previous settings') + '.')
            ui.preview(settings or {'env': result['env']}, result['target'])
            print('Model changes may take time; use /model to reselect a fixed model in existing sessions.')
        else:
            outcome = 'apply partial' if result.get('partial') else 'apply failed'
            print(prefix + outcome + '; shell not synced.')
            if result.get('error'):
                print(result['error'])
    if not complete:
        if result.get('partial'):
            print('file applied; shell not synced; operation is partial, see recovery backup', file=sys.stderr)
        for warning in result.get('warnings', []):
            print(warning, file=sys.stderr)
        return failure_code
    return 0


def save_then_apply(store, name, settings, json_mode, shell_output, *, apply=False, **save_options):
    automatic_migration(store)
    saved = store.save(name, settings, **save_options)
    if not apply:
        show_profile(saved, json_mode, saved=True)
        return 0
    try:
        result = store.apply(name)
    except (ValueError, RuntimeError, OSError) as error:
        # File/runtime errors can contain private contents. Validation diagnostics
        # originate from Store and name configuration keys, never credential values.
        message = str(error) if isinstance(error, ValueError) else 'Application failed; check paths, permissions and recovery state'
        result = {'success': False, 'applied': False, 'partial': False,
                  'profile': name, 'target': str(store.settings_path), 'env': {},
                  'error': message}
        return finish_apply(result, json_mode, None, saved=saved,
                            failure_code=2 if isinstance(error, (ValueError, RuntimeError)) else 1)
    return finish_apply(result, json_mode, shell_output, saved=saved)


def current_name(store):
    status = store.status()
    if not status.get('profile') or not status.get('file_matches'):
        raise ValueError('Current settings are not a recognized applied profile; specify a saved profile name')
    return status['profile']


def doctor(store):
    result = store.status()
    result['migration_available'] = migration_preview(store)
    # Name project and local override paths; never read credentials or run helpers.
    # Walk ancestors because Claude can inherit project settings from parents.
    paths = [store.config_dir / 'settings.local.json']
    for directory in (Path.cwd(), *Path.cwd().parents):
        paths.extend((directory / '.claude/settings.json', directory / '.claude/settings.local.json'))
    result['project_local_overrides'] = list(dict.fromkeys(str(path) for path in paths if path.is_file()))
    result['notes'] = ['Project/local overrides and managed policies can take precedence over global settings.',
                       'Helpers were not executed; credential contents were not read.']
    return result


def run_slots(args, store, json_mode, shell_output):
    parts = args.parts
    if len(parts) == 1 and parts[0] not in ('edit', 'set', 'menu'):
        show_profile(store.get(parts[0]), json_mode, target=store.settings_path)
        return 0
    if parts and parts[0] == 'set':
        if len(parts) != 4 or parts[2] not in SLOTS:
            raise UsageError('Use slots set NAME opus|sonnet|haiku|startup|subagent MODEL')
        name = parts[1]
        profile = store.get(name)
        draft = set_slot(profile['settings'], parts[2], parts[3])
        apply = args.apply
    elif parts and parts[0] == 'menu':
        if len(parts) != 3:
            raise UsageError('Use slots menu add|remove|move|rename|builtins NAME with explicit options')
        action, name = parts[1:]
        profile = store.get(name)
        draft = edit_menu(profile['settings'], action, model=args.model, label=args.label,
                          description=args.description, behaves_as=args.behaves_as,
                          index=args.index, to=args.to,
                          replace_built_in=None if args.replace_builtins is None else args.replace_builtins == 'true')
        apply = args.apply
    else:
        if parts and (parts[0] != 'edit' or len(parts) > 2):
            raise UsageError('Use slots [NAME] or slots edit [NAME]')
        ui.require_terminal()
        name = parts[1] if len(parts) == 2 else current_name(store)
        profile = store.get(name)
        draft, apply = ui.slot_wizard(profile['settings'], store.settings_path)
    return save_then_apply(store, name, draft, json_mode, shell_output, apply=apply,
                           replace=True, catalog=profile['catalog'], source=profile['source'])


def legacy_override(args, store, backend):
    if args.command == 'default' and args.restore and args.model:
        raise UsageError('default --restore does not take a model')
    automatic_migration(store)
    # Compatibility commands use default's connection and do not save overrides.
    profile = store.get('default')
    if args.command == 'default' and args.restore:
        return store.apply('default')
    settings = extract_settings(profile['settings'])
    selected = args.model or settings.get('env', {}).get('ANTHROPIC_MODEL') or settings.get('model') or 'sonnet'
    models, live = backend.load_model_catalog()
    model = backend.validate_model(selected, models, live)
    if not live:
        print('CloudCLI live catalog unavailable; using the built-in compatibility catalog.', file=sys.stderr)
    if args.command == 'single':
        settings = unify_slots(settings, model)
    else:
        settings['env'].update(backend.DEFAULT_MODEL_SLOTS)
        settings = set_slot(settings, 'startup', model)
    return store.apply('default', settings_override=settings)


def main(argv=None, backend=None):
    try:
        raw = list(sys.argv[1:] if argv is None else argv)
        argv, json_mode, shell_output = output_options(raw)
        argument_parser = parser()
        args = argument_parser.parse_args(argv)
        if backend is None:
            import ccswitch_backend as backend
        command = args.command or 'status'
        if command == 'help':
            argument_parser.print_help()
            print('\nDaily flow: use [NAME]; slots [NAME]; slots edit [NAME]')
            print('Import: import NAME --from FILE|current [--auth api_key|bearer_token]')
            print('Save: save NAME [--from FILE|current] [--replace] (does not apply)')
            print('Slots: slots set NAME opus|sonnet|haiku|startup|subagent MODEL [--apply]')
            print('Menu: slots menu add NAME --model MODEL [--label TEXT] [--description TEXT] [--behaves-as MODEL]')
            print('Menu: slots menu remove NAME --index N; slots menu move NAME --index N --to N')
            print('Menu: slots menu rename NAME --index N --label TEXT; indexes start at 0')
            print('Menu: slots menu builtins NAME --replace-builtins true|false')
            print('Compatibility: default [MODEL] | default --restore | single MODEL')
            print('Migration: migrate imports missing current/default profiles and never applies them.')
            print('All commands accept --json; applied commands support private --shell-output FILE.')
            return 0
        if command == 'version':
            if json_mode:
                emit({'version': backend.read_version()}, True)
            else:
                backend.cmd_version()
            return 0
        if command == 'models':
            if json_mode:
                models, live = backend.load_model_catalog()
                emit({'models': models, 'live': live}, True)
            else:
                backend.cmd_models()
            return 0
        store = ProfileStore()
        if command in ('status', 'doctor'):
            status = doctor(store) if command == 'doctor' else store.status()
            if command == 'status':
                status['migration_available'] = migration_preview(store)
            if command == 'doctor':
                emit(status, json_mode)
            else:
                show_status(store, status, json_mode)
        elif command == 'list':
            profiles = store.list_profiles()
            if json_mode:
                emit(profiles, True)
            elif not profiles:
                print('No saved profiles.')
            else:
                for profile in profiles:
                    show_profile(profile, False)
        elif command == 'migrate':
            emit(migrate(store, explicit=True), json_mode)
        elif command == 'use':
            name = args.name
            if name is None:
                name = ui.select_profile(store.list_profiles(), store.settings_path)
            profile = store.get(name)  # Validate before any migration writes.
            automatic_migration(store)
            return finish_apply(store.apply(name), json_mode, shell_output, settings=profile['settings'])
        elif command in ('add', 'save', 'import', 'edit'):
            name = args.name
            if name is None:
                name = ui.ask('Profile name (cancel): ').strip()
            store._profile_path(name)  # Store owns name validation; no filesystem mutation.
            apply = False
            existing = store.get(name) if command == 'edit' else None
            if args.source:
                settings = read_source(args.source, store)
            elif command == 'save':
                settings = read_source('current', store)
            elif command == 'import':
                raise UsageError('import requires --from FILE|current')
            else:
                settings = ui.connection(existing['settings'] if existing else None)
                settings, apply = ui.slot_wizard(settings, store.settings_path)
            # Validate before automatic migration so rejected imports don't write.
            settings = extract_settings(settings, auth=args.auth)
            return save_then_apply(store, name, settings, json_mode, shell_output, apply=apply,
                                   replace=args.replace or command == 'edit', auth=args.auth,
                                   catalog=existing['catalog'] if existing else 'manual',
                                   source=args.source or (existing['source'] if existing else
                                                         'current' if command == 'save' else 'manual'))
        elif command == 'init':
            settings = read_source('current', store) if store.settings_path.exists() else {'env': {}}
            # Validate unsupported auth from both the full target and inherited
            # shell before projection, so init cannot turn OAuth/cloud into static.
            settings = extract_settings(settings, auth=args.auth)
            settings['env'].update({key: value for key, value in os.environ.items() if value})
            settings = extract_settings(settings, auth=args.auth)
            if not settings['env'].get('ANTHROPIC_BASE_URL'):
                raise ValueError('Cannot initialize default without ANTHROPIC_BASE_URL')
            automatic_migration(store)
            show_profile(store.save('default', settings, replace=args.replace, auth=args.auth, source='init'), json_mode, saved=True)
        elif command == 'slots':
            return run_slots(args, store, json_mode, shell_output)
        elif command in ('default', 'single'):
            return finish_apply(legacy_override(args, store, backend), json_mode, shell_output)
        elif command == 'undo':
            automatic_migration(store)
            result = store.undo()
            settings = read_source('current', store) if result.get('success') and not json_mode else None
            return finish_apply(result, json_mode, shell_output, settings=settings)
        elif command == 'remove':
            store.get(args.name)
            automatic_migration(store)
            emit(store.remove(args.name), json_mode)
        return 0
    except ui.Cancelled:
        print('Cancelled; no changes saved.')
        return 0
    except (ValueError, RuntimeError) as error:
        print('ccswitch: ' + str(error), file=sys.stderr)
        return 2
    except OSError:
        # OS messages can include source file contents/paths or arbitrary faults.
        print('ccswitch: file operation failed; check paths and permissions', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Cancelled; no changes saved.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
