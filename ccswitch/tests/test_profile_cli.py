"""CLI contract tests use isolated HOME/configs and actual backend subprocesses."""
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest

LIB = Path(__file__).resolve().parents[1] / 'lib'
BACKEND = LIB / 'ccswitch_backend.py'
sys.path.insert(0, str(LIB))
from ccswitch_profiles import MANAGED_ENV_KEYS


class ProfileCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'claude'
        self.config.mkdir()
        self.settings = self.config / 'settings.json'
        self.store_root = self.root / 'xdg' / 'ccswitch'
        self.output_file = self.root / 'shell-output'
        self.source = self.root / 'source.json'
        self.data = {'env': {'ANTHROPIC_BASE_URL': 'https://example.test/anthropic',
                            'ANTHROPIC_AUTH_TOKEN': 'test-token',
                            'ANTHROPIC_DEFAULT_OPUS_MODEL': 'Vendor/Opus[1m]'},
                     'model': 'sonnet', 'permissions': {'allow': ['Read']}}
        self.source.write_text(json.dumps(self.data))
        self.env = {key: value for key, value in os.environ.items()
                    if key not in MANAGED_ENV_KEYS and not key.startswith(('CLAUDE_CODE_USE_', 'CLAUDE_CODE_OAUTH_'))}
        self.env.update(HOME=str(self.root), CLAUDE_CONFIG_DIR=str(self.config),
                        XDG_CONFIG_HOME=str(self.root / 'xdg'), PYTHONDONTWRITEBYTECODE='1',
                        CCSWITCH_CLOUDCLI_MODEL_SDK=str(self.root / 'missing-sdk'))

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, '-B', str(BACKEND), *map(str, args)],
                              env=self.env if env is None else env, input='',
                              capture_output=True, text=True, timeout=8)

    def ok(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('test-token', result.stdout + result.stderr)
        return result

    def import_work(self):
        self.ok('import', 'work', '--from', self.source)

    def test_import_list_use_json_redacts_and_shell_file_is_private(self):
        self.import_work()
        self.assertFalse(self.settings.exists())
        listing = json.loads(self.ok('list', '--json').stdout)
        self.assertEqual(listing[0]['name'], 'work')
        self.assertEqual(listing[0]['settings']['env']['ANTHROPIC_AUTH_TOKEN'], '<redacted>')
        applied = self.ok('use', 'work', '--json', '--shell-output', self.output_file)
        self.assertTrue(json.loads(applied.stdout)['success'])
        self.assertIn('ANTHROPIC_AUTH_TOKEN=test-token\n', self.output_file.read_text())
        self.assertEqual(self.output_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.output_file.read_text().splitlines()), len(MANAGED_ENV_KEYS))
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Opus[1m]')
        self.assertNotIn('permissions', settings)

    def test_save_is_separate_from_use_and_replacement_is_explicit(self):
        self.settings.write_text(json.dumps(self.data))
        original = self.settings.read_bytes()
        self.ok('save', 'work')
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertNotEqual(self.cli('save', 'work').returncode, 0)
        self.ok('save', 'work', '--replace')
        self.ok('use', 'work')
        self.assertIn('/model', self.ok('use', 'work').stdout)

    def test_slots_set_menu_and_apply_preserve_saved_custom_model_ids(self):
        self.import_work()
        self.ok('slots', 'set', 'work', 'sonnet', 'MyVendor/Model[1m]')
        self.assertFalse(self.settings.exists())
        self.ok('slots', 'set', 'work', 'startup', 'opus', '--apply', '--shell-output', self.output_file)
        self.ok('slots', 'menu', 'add', 'work', '--model', 'Menu/Model', '--label', 'Menu label')
        self.ok('slots', 'menu', 'add', 'work', '--model', 'Second')
        self.ok('slots', 'menu', 'move', 'work', '--index', '1', '--to', '0')
        profile = json.loads((self.store_root / 'profiles/work.json').read_text())
        self.assertEqual(profile['settings']['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'MyVendor/Model[1m]')
        self.assertEqual(profile['settings']['modelPicker']['options'][0], {'model': 'Second'})
        self.assertFalse(profile['settings']['modelPicker']['replaceBuiltInOptions'])
        self.ok('slots', 'menu', 'remove', 'work', '--index', '0')
        self.assertNotEqual(self.cli('slots', 'menu', 'remove', 'work', '--index', '9').returncode, 0)

    def test_incomplete_and_dual_auth_require_explicit_choice(self):
        self.data['env'].pop('ANTHROPIC_AUTH_TOKEN')
        self.source.write_text(json.dumps(self.data))
        self.import_work()
        result = self.cli('use', 'work', '--shell-output', self.output_file)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output_file.exists())
        self.data['env'].update(ANTHROPIC_API_KEY='api-secret', ANTHROPIC_AUTH_TOKEN='test-token')
        self.source.write_text(json.dumps(self.data))
        result = self.cli('import', 'dual', '--from', self.source)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('api-secret', result.stderr)
        self.ok('import', 'dual', '--from', self.source, '--auth', 'bearer_token')
        self.ok('use', 'dual')
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_API_KEY'], '')

    def test_noninteractive_missing_inputs_never_prompt_and_errors_hide_arguments(self):
        for args in [('use',), ('add',), ('slots', 'edit'), ('save',), ('single',), ('codex',), ('detect-codex',), ('--api-key', 'test-token'), ('use', 'work', '--auth-token', 'test-token')]:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('test-token', result.stdout + result.stderr)
        self.assertFalse(self.store_root.exists())

    def test_add_edit_from_file_and_init_default_snapshot_protection(self):
        self.ok('add', 'work', '--from', self.source)
        self.ok('edit', 'work', '--from', self.source)
        self.ok('use', 'work')
        self.ok('init')
        self.assertNotEqual(self.cli('init').returncode, 0)
        self.ok('init', '--replace')
        self.assertFalse((self.config / 'ccswitch-defaults.json').exists())
        self.ok('default', '--restore')
        self.ok('undo', '--shell-output', self.output_file)
        self.assertIn('ANTHROPIC_AUTH_TOKEN=test-token', self.output_file.read_text())

    def test_migration_is_independent_idempotent_readonly_and_not_retried_automatically(self):
        self.settings.write_text(json.dumps(self.data))
        legacy = self.config / 'ccswitch-defaults.json'
        legacy.write_text(json.dumps(dict(self.data['env'], ANTHROPIC_MODEL='Legacy[1m]')))
        before = self.settings.read_bytes(), legacy.read_bytes()
        self.ok('status', '--json')
        self.assertFalse(self.store_root.exists())
        migrated = json.loads(self.ok('migrate', '--json').stdout)
        self.assertEqual(set(migrated['created']), {'current', 'default'})
        self.assertEqual((self.settings.read_bytes(), legacy.read_bytes()), before)
        self.import_work()
        self.ok('use', 'work')
        after_use = (self.store_root / 'profiles/current.json').read_bytes()
        self.ok('slots', 'set', 'work', 'haiku', 'other-model')
        self.assertEqual((self.store_root / 'profiles/current.json').read_bytes(), after_use)
        self.assertIn('current', json.loads(self.ok('migrate', '--json').stdout)['conflicts'])
        self.assertNotEqual(self.cli('init').returncode, 0)
        self.assertEqual(legacy.read_bytes(), before[1])

    def test_legacy_default_single_keep_catalog_compatibility_validation(self):
        self.ok('import', 'default', '--from', self.source)
        for command in ('default', 'single'):
            result = self.cli(command, 'gpt-5.6-sol')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('OpenCode', result.stderr)
        self.assertFalse(self.settings.exists())
        # Named profiles intentionally accept manually maintained upstream IDs.
        self.ok('slots', 'set', 'default', 'startup', 'gpt-5.6-sol')
        self.ok('use', 'default')
        self.assertEqual(json.loads(self.settings.read_text())['model'], 'gpt-5.6-sol')

    def test_default_and_single_are_temporary_overrides(self):
        self.settings.write_text(json.dumps(self.data))
        self.ok('migrate')
        self.ok('save', 'default', '--replace')
        saved = (self.store_root / 'profiles/default.json').read_bytes()
        self.ok('default', 'glm-5.2')
        target = json.loads(self.settings.read_text())
        self.assertEqual(target['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'claude-opus-5[1m]')
        self.assertEqual(target['model'], 'glm-5.2')
        self.ok('single', 'Vendor/Single[1m]')
        target = json.loads(self.settings.read_text())
        self.assertEqual(target['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'Vendor/Single')
        self.assertEqual((self.store_root / 'profiles/default.json').read_bytes(), saved)
        self.ok('default', '--restore')
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Opus[1m]')

    def test_status_doctor_redact_conflict_rows_and_show_local_overrides(self):
        self.import_work()
        self.ok('use', 'work')
        conflict_env = dict(self.env, ANTHROPIC_AUTH_TOKEN='shell-secret')
        result = self.cli('status', '--json', env=conflict_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('test-token', result.stdout)
        self.assertNotIn('shell-secret', result.stdout)
        workdir = self.root / 'project'
        (workdir / '.claude').mkdir(parents=True)
        override = workdir / '.claude/settings.local.json'
        override.write_text(json.dumps({'apiKeyHelper': 'never execute test-token'}))
        result = subprocess.run([sys.executable, '-B', str(BACKEND), 'doctor', '--json'], cwd=workdir,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(override), result.stdout)
        self.assertNotIn('test-token', result.stdout)

    def test_unsupported_import_auth_and_managed_target_are_refused(self):
        self.data['apiKeyHelper'] = 'test-token'
        self.source.write_text(json.dumps(self.data))
        self.assertNotEqual(self.cli('import', 'work', '--from', self.source).returncode, 0)
        self.data.pop('apiKeyHelper')
        self.source.write_text(json.dumps(self.data))
        self.import_work()
        (self.config / 'managed-settings.json').write_text(json.dumps({'env': {'ANTHROPIC_MODEL': 'managed'}}))
        result = self.cli('use', 'work', '--shell-output', self.output_file)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output_file.exists())

    def test_shell_output_failure_reports_applied_file_and_unsynced_shell(self):
        self.import_work()
        result = self.cli('use', 'work', '--shell-output', self.root / 'absent' / 'out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('file applied', result.stderr)
        self.assertIn('shell not synced', result.stderr)
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_AUTH_TOKEN'], 'test-token')
        self.assertNotIn('test-token', result.stdout + result.stderr)

    def test_partial_apply_never_writes_shell_exports(self):
        # Inject only state persistence failure; the actual temporary target is replaced.
        self.import_work()
        script = '''import sys
sys.path.insert(0, sys.argv[1])
import ccswitch_profiles as p
import ccswitch_cli as cli
original = p._atomic_json
def fail(path, *args, **kwargs):
    if path.name == 'state.json': raise OSError('private fault test-token')
    return original(path, *args, **kwargs)
p._atomic_json = fail
raise SystemExit(cli.main(['use', 'work', '--json', '--shell-output', sys.argv[2]]))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(LIB), str(self.output_file)],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['partial'])
        self.assertFalse(self.output_file.exists())
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_AUTH_TOKEN'], 'test-token')
        self.assertNotIn('test-token', result.stdout + result.stderr)

    def test_init_keeps_model_ids_prefers_exported_endpoint_and_checks_base_url(self):
        self.settings.write_text(json.dumps(self.data))
        init_env = dict(self.env, ANTHROPIC_BASE_URL='https://exported.test')
        result = self.cli('init', env=init_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads((self.store_root / 'profiles/default.json').read_text())
        self.assertEqual(profile['settings']['env']['ANTHROPIC_BASE_URL'], 'https://exported.test')
        self.assertEqual(profile['settings']['env']['ANTHROPIC_AUTH_TOKEN'], 'test-token')
        self.assertEqual(profile['settings']['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Opus[1m]')
        self.data['env'].pop('ANTHROPIC_BASE_URL')
        self.settings.write_text(json.dumps(self.data))
        previous = (self.store_root / 'profiles/default.json').read_bytes()
        self.assertNotEqual(self.cli('init', '--replace').returncode, 0)
        self.assertEqual((self.store_root / 'profiles/default.json').read_bytes(), previous)

    def test_init_invalid_env_has_safe_diagnostic_and_never_writes(self):
        self.settings.write_text(json.dumps({'env': 42}))
        result = self.cli('init')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(self.store_root.exists())

    def test_product_and_flat_file_imports_and_static_api_key_apply(self):
        self.source.write_text(json.dumps({'schema_version': 1, 'name': 'export', 'settings': self.data}))
        self.ok('import', 'product', '--from', self.source)
        self.source.write_text(json.dumps(dict(self.data['env'], ANTHROPIC_AUTH_TOKEN='', ANTHROPIC_API_KEY='api-secret')))
        result = self.ok('import', 'flat', '--from', self.source)
        self.assertNotIn('api-secret', result.stdout + result.stderr)
        result = self.ok('use', 'flat', '--shell-output', self.output_file)
        self.assertNotIn('api-secret', result.stdout + result.stderr)
        self.assertIn('ANTHROPIC_API_KEY=api-secret\n', self.output_file.read_text())
        self.assertIn('ANTHROPIC_AUTH_TOKEN=\n', self.output_file.read_text())

    def terminal_cli(self, args, inputs, prompt=b'Action', env=None, expected=0):
        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, '-B', str(BACKEND), *args],
                                   stdin=slave, stdout=slave, stderr=slave, env=self.env if env is None else env)
        os.close(slave)
        output = b''
        try:
            deadline = time.monotonic() + 5
            steps = inputs if isinstance(inputs, list) else [(prompt, inputs)]
            for marker, answer in steps:
                chunk = b''
                while marker not in chunk and time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], 0.2)
                    if ready:
                        try: chunk += os.read(master, 65536)
                        except OSError: break
                output += chunk
                self.assertIn(marker, chunk, output.decode(errors='replace'))
                os.write(master, answer.encode())
            while process.poll() is None and time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try: output += os.read(master, 65536)
                    except OSError: break
            result = process.wait(timeout=2)
            self.assertEqual(result, expected, output.decode(errors='replace'))
            self.assertNotIn(b'test-token', output)
            return output.decode(errors='replace')
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()

    def connection_steps(self, actions, edit=False):
        return [(b'Base URL', '\n' if edit else 'https://gateway.test/v1\n'),
                (b'Authentication', '\n' if edit else 'api_key\n')] + ([] if edit else [
                    (b'Secret', 'test-token\n')]) + [(b'Action:', actions)]

    def test_terminal_add_completed_draft_cancel_has_no_migration_or_save(self):
        self.settings.write_text(json.dumps(self.data))
        before = self.settings.read_bytes()
        output = self.terminal_cli(['add', 'personal'], self.connection_steps(
            'unify\nVendor/Unified[1m]\nstartup\nsonnet\ncancel\n'))
        self.assertFalse(self.store_root.exists())
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertIn('Vendor/Unified[1m]', output)
        self.assertNotIn('ANTHROPIC_API_KEY', output)

    def test_terminal_add_save_and_apply_and_edit_share_complete_draft(self):
        output = self.terminal_cli(['add', 'personal'], self.connection_steps(
            'unify\nVendor/Unified[1m]\nstartup\nsonnet\nsave\n'))
        self.assertFalse(self.settings.exists())
        profile = json.loads((self.store_root / 'profiles/personal.json').read_text())
        self.assertEqual(profile['settings']['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Unified[1m]')
        self.assertEqual(profile['settings']['model'], 'sonnet')
        self.assertIn('Saved', output)
        before = (self.store_root / 'profiles/personal.json').read_bytes()
        self.terminal_cli(['edit', 'personal'], self.connection_steps('sonnet\nDraft\ncancel\n', edit=True))
        self.assertEqual((self.store_root / 'profiles/personal.json').read_bytes(), before)
        self.terminal_cli(['edit', 'personal'], self.connection_steps('sonnet\nEdited\napply\n', edit=True))
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Edited')
        self.terminal_cli(['add', 'second'], self.connection_steps('unify\nSecond\napply\n'))
        self.assertEqual(json.loads(self.settings.read_text())['model'], 'Second')

    def test_saved_but_blocked_apply_is_explicit_in_human_and_json(self):
        self.import_work()
        blocked = dict(self.env, CLAUDE_CODE_USE_BEDROCK='1')
        for json_mode in (False, True):
            args = ['slots', 'set', 'work', 'sonnet', 'Saved/New', '--apply', '--shell-output', self.output_file]
            if json_mode: args.append('--json')
            result = self.cli(*args, env=blocked)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(self.output_file.exists())
            self.assertFalse(self.settings.exists())
            self.assertEqual(json.loads((self.store_root / 'profiles/work.json').read_text())['settings']['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Saved/New')
            if json_mode:
                value = json.loads(result.stdout)
                self.assertIs(value['saved'], True)
                self.assertIs(value['success'], False)
                self.assertIs(value['applied'], False)
                self.assertIs(value['partial'], False)
                self.assertIn('CLAUDE_CODE_USE_BEDROCK', value['error'])
                self.assertEqual(value['saved_profile']['settings']['env']['ANTHROPIC_AUTH_TOKEN'], '<redacted>')
            else:
                self.assertIn('saved', result.stdout.lower())
                self.assertIn('apply failed', result.stdout.lower())
            self.assertNotIn('test-token', result.stdout + result.stderr)
        output = self.terminal_cli(['edit', 'work'], self.connection_steps('haiku\nSaved/Fast\napply\n', edit=True),
                                   env=blocked, expected=2)
        self.assertIn('saved', output.lower())
        self.assertIn('apply failed', output.lower())

    def test_saved_partial_apply_reports_both_stages_without_exports(self):
        self.import_work()
        script = """import sys
sys.path.insert(0, sys.argv[1])
import ccswitch_profiles as p
import ccswitch_cli as cli
original = p._atomic_json
def fail(path, *args, **kwargs):
    if path.name == 'state.json': raise OSError('private fault test-token')
    return original(path, *args, **kwargs)
p._atomic_json = fail
raise SystemExit(cli.main(['slots', 'set', 'work', 'sonnet', 'Saved/Partial', '--apply', '--json', '--shell-output', sys.argv[2]]))
"""
        result = subprocess.run([sys.executable, '-B', '-c', script, str(LIB), str(self.output_file)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        value = json.loads(result.stdout)
        self.assertIs(value['saved'], True)
        self.assertIs(value['applied'], True)
        self.assertIs(value['partial'], True)
        self.assertIs(value['success'], False)
        self.assertEqual(value['saved_profile']['settings']['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Saved/Partial')
        self.assertFalse(self.output_file.exists())
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Saved/Partial')
        self.assertNotIn('test-token', result.stdout + result.stderr)

    def test_daily_human_summaries_are_concise_and_json_stays_detailed(self):
        self.import_work()
        self.ok('slots', 'menu', 'add', 'work', '--model', 'Menu/Extra')
        for args in [('list',), ('slots', 'work'), ('use', 'work'), ('status',), ('undo',)]:
            result = self.ok(*args)
            self.assertLess(len(result.stdout.splitlines()), 16, result.stdout)
            self.assertNotIn('"env"', result.stdout)
            self.assertNotIn('backup_id', result.stdout)
            self.assertNotIn('ANTHROPIC_API_KEY', result.stdout)
        saved = self.ok('slots', 'work').stdout
        for text in ('work', 'bearer_token', 'example.test', 'Vendor/Opus[1m]', 'Menu: 1'):
            self.assertIn(text, saved)
        applied = json.loads(self.ok('use', 'work', '--json').stdout)
        self.assertEqual(set(applied['env']), set(MANAGED_ENV_KEYS))
        self.assertIn('backup_id', applied)
        self.assertEqual(applied['env']['ANTHROPIC_AUTH_TOKEN'], '<redacted>')
        target = json.loads(self.settings.read_text())
        target['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'] = 'External'
        self.settings.write_text(json.dumps(target))
        result = self.cli('status', env=dict(self.env, ANTHROPIC_AUTH_TOKEN='shell-secret'))
        self.assertIn('ANTHROPIC_DEFAULT_OPUS_MODEL', result.stdout)
        self.assertIn('ANTHROPIC_AUTH_TOKEN', result.stdout)
        self.assertNotIn('shell-secret', result.stdout + result.stderr)

    def test_terminal_slot_cancel_after_edit_does_not_write(self):
        self.import_work()
        before = {p: p.read_bytes() for p in self.store_root.rglob('*') if p.is_file()}
        self.terminal_cli(['slots', 'edit', 'work'], 'opus\nchanged-draft\ncancel\n')
        after = {p: p.read_bytes() for p in self.store_root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(self.settings.exists())

    def test_terminal_slots_save_then_apply_and_recognize_current(self):
        self.import_work()
        self.terminal_cli(['slots', 'edit', 'work'], 'opus\nExact/Model[1m]\nstartup\nsonnet\nsubagent\nagent-model\nmenu-add\nmenu-model\nMenu\nDescription\nsonnet\nsave\n')
        self.assertFalse(self.settings.exists())
        profile = json.loads((self.store_root / 'profiles/work.json').read_text())
        self.assertEqual(profile['settings']['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Exact/Model[1m]')
        self.assertEqual(profile['settings']['env']['CLAUDE_CODE_SUBAGENT_MODEL'], 'agent-model')
        self.assertEqual(profile['settings']['modelPicker']['options'][0],
                         {'model': 'menu-model', 'label': 'Menu', 'description': 'Description', 'behavesAs': 'sonnet'})
        self.terminal_cli(['use'], 'work\ny\n', prompt=b'Profile (')
        self.terminal_cli(['slots'], 'haiku\nnew-haiku\napply\n')
        self.assertEqual(json.loads(self.settings.read_text())['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'new-haiku')

    def test_terminal_use_and_add_cancel_never_write(self):
        self.import_work()
        self.terminal_cli(['use'], 'work\nn\n', prompt=b'Profile (')
        self.assertFalse(self.settings.exists())
        before = {p: p.read_bytes() for p in self.store_root.rglob('*') if p.is_file()}
        self.terminal_cli(['add', 'cancelled'], 'cancel\n', prompt=b'Base URL')
        self.assertEqual(before, {p: p.read_bytes() for p in self.store_root.rglob('*') if p.is_file()})

    def test_migration_attempt_completes_even_when_first_target_is_missing(self):
        self.import_work()
        self.ok('use', 'work')
        self.ok('slots', 'set', 'work', 'opus', 'next')
        self.assertFalse((self.store_root / 'profiles/current.json').exists())
        # Explicit migration remains possible and reports its created names.
        result = json.loads(self.ok('migrate', '--json').stdout)
        self.assertEqual(result['created'], ['current'])

    def test_init_refuses_unsupported_shell_auth_and_invalid_names_do_not_migrate(self):
        self.settings.write_text(json.dumps(self.data))
        for invalid in ('BadName', '-bad', 'doctor'):
            result = self.cli('save', invalid)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.store_root.exists())
        shell = dict(self.env, CLAUDE_CODE_OAUTH_TOKEN='shell-secret')
        result = self.cli('init', env=shell)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('shell-secret', result.stdout + result.stderr)
        self.assertFalse(self.store_root.exists())

    def test_unify_keeps_force_policy_and_default_preserves_independent_fast_model(self):
        self.data['env'].update(CLAUDE_CODE_SUBAGENT_MODEL_FORCE='true', ANTHROPIC_SMALL_FAST_MODEL='separate-fast')
        self.source.write_text(json.dumps(self.data))
        self.ok('import', 'default', '--from', self.source)
        self.ok('default', 'glm-5.2')
        target = json.loads(self.settings.read_text())['env']
        self.assertEqual(target['ANTHROPIC_SMALL_FAST_MODEL'], 'separate-fast')
        self.assertEqual(target['CLAUDE_CODE_SUBAGENT_MODEL_FORCE'], 'true')
        self.ok('single', 'glm-5.2')
        self.assertEqual(json.loads(self.settings.read_text())['env']['CLAUDE_CODE_SUBAGENT_MODEL_FORCE'], 'true')

    def test_remove_saved_profile_and_model_only_advanced_picker_import(self):
        self.data['modelPicker'] = {'options': [{'model': 'raw[1m]'}], 'replaceBuiltInOptions': False,
                                    'advanced': {'extension': True}}
        self.source.write_text(json.dumps(self.data))
        self.import_work()
        self.ok('slots', 'work', '--json')
        self.ok('use', 'work')
        self.assertEqual(json.loads(self.settings.read_text())['modelPicker'], self.data['modelPicker'])
        self.assertNotEqual(self.cli('remove', 'work').returncode, 0)
        self.ok('import', 'unused', '--from', self.source)
        self.ok('remove', 'unused')
        self.assertFalse((self.store_root / 'profiles/unused.json').exists())


if __name__ == '__main__':
    unittest.main()
