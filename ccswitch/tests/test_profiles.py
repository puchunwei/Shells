"""File-level contract for the private profile store (never uses real settings)."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from ccswitch_profiles import (MANAGED_ENV_KEYS, MODEL_ENV_KEYS, TOP_LEVEL_KEYS,
                               ProfileStore, extract_settings, redact)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.config = self.base / 'claude'
        self.config.mkdir()
        self.root = self.base / 'private'
        self.environ = patch.dict(os.environ, {'HOME': str(self.base),
            'CLAUDE_CONFIG_DIR': str(self.config), 'XDG_CONFIG_HOME': str(self.base / 'xdg')}, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.store = ProfileStore(config_dir=self.config, root=self.root)

    def write(self, value, path=None):
        path = path or self.store.settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def settings(self, key='key-A', model='sonnet'):
        return {'env': {'ANTHROPIC_BASE_URL': 'https://gateway.example/anthropic',
            'ANTHROPIC_API_KEY': key, 'ANTHROPIC_MODEL': model}}

    def read(self):
        return json.loads(self.store.settings_path.read_text())

    def test_api_key_roundtrip_preserves_hooks_and_clears_other_auth(self):
        self.write({'hooks': {'SessionStart': []}, 'env': {'KEEP': 'yes',
            'ANTHROPIC_AUTH_TOKEN': 'previous-token'}})
        saved = self.store.save('work', self.settings())
        self.assertEqual(saved['auth_type'], 'api_key')
        self.assertEqual(self.store.get('work')['settings']['env']['ANTHROPIC_API_KEY'], 'key-A')
        self.assertEqual(self.read()['env']['ANTHROPIC_AUTH_TOKEN'], 'previous-token')
        result = self.store.apply('work')
        self.assertTrue(result['success'])
        self.assertEqual(result['env']['ANTHROPIC_AUTH_TOKEN'], '')
        self.assertEqual(set(result['env']), set(MANAGED_ENV_KEYS))
        self.assertEqual(self.read()['env']['ANTHROPIC_API_KEY'], 'key-A')
        self.assertEqual(self.read()['env']['ANTHROPIC_AUTH_TOKEN'], '')
        self.assertEqual(self.read()['hooks'], {'SessionStart': []})
        self.assertEqual(self.read()['env']['KEEP'], 'yes')

    def test_bearer_switch_clears_api_key_and_missing_model_fields(self):
        self.store.save('api', self.settings())
        self.store.apply('api')
        self.store.save('token', {'env': {'ANTHROPIC_BASE_URL': 'http://b.example',
            'ANTHROPIC_AUTH_TOKEN': 'token-B'}})
        self.store.apply('token')
        self.assertEqual(self.read()['env']['ANTHROPIC_API_KEY'], '')
        self.assertEqual(self.read()['env']['ANTHROPIC_MODEL'], '')

    def test_default_paths_follow_environment_without_creating_store_on_read(self):
        store = ProfileStore()
        self.assertEqual(store.settings_path, self.config / 'settings.json')
        self.assertEqual(store.defaults_path, self.config / 'ccswitch-defaults.json')
        self.assertEqual(store.root, self.base / 'xdg' / 'ccswitch')
        self.assertEqual(store.list_profiles(), [])
        self.assertIsNone(store.status()['profile'])
        self.assertFalse(store.root.exists())

    def test_migrate_current_and_flat_default_are_independent_and_idempotent(self):
        self.write(self.settings(model='custom[1m]'))
        self.write({'ANTHROPIC_BASE_URL': 'http://old.example',
            'ANTHROPIC_AUTH_TOKEN': 'old-token', 'ANTHROPIC_MODEL': 'legacy-id'}, self.store.defaults_path)
        before = [p.read_bytes() for p in (self.store.settings_path, self.store.defaults_path)]
        result = self.store.migrate()
        self.assertEqual(result['created'], ['current', 'default'])
        self.assertEqual(self.store.get('current')['settings']['env']['ANTHROPIC_MODEL'], 'custom[1m]')
        self.assertEqual(self.store.get('default')['settings']['env']['ANTHROPIC_AUTH_TOKEN'], 'old-token')
        self.assertEqual(self.store.migrate()['created'], [])
        self.assertEqual(before, [p.read_bytes() for p in (self.store.settings_path, self.store.defaults_path)])

    def test_migrate_bad_current_still_imports_default_and_does_not_overwrite_names(self):
        self.store.settings_path.write_text('{broken')
        self.write(self.settings(), self.store.defaults_path)
        result = self.store.migrate()
        self.assertEqual(result['created'], ['default'])
        self.assertTrue(result['warnings'])
        self.store.save('current', self.settings(key='chosen'))
        self.write(self.settings(key='other'))
        result = self.store.migrate()
        self.assertIn('current', result['conflicts'])
        self.assertEqual(self.store.get('current')['settings']['env']['ANTHROPIC_API_KEY'], 'chosen')

    def test_invalid_name_and_invalid_json_never_replace_data(self):
        for name in ('../escape', '', 'a/b', '.', 'bad\nname'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.save(name, self.settings())
        self.store.save('work', self.settings())
        self.store.settings_path.write_text('{broken')
        with self.assertRaises(ValueError):
            self.store.apply('work')
        self.assertEqual(self.store.settings_path.read_text(), '{broken')

    def test_duplicate_save_requires_replace_and_revision_increments(self):
        self.store.save('work', self.settings())
        with self.assertRaises(ValueError):
            self.store.save('work', self.settings(key='different'))
        changed = self.store.save('work', self.settings(key='different'), replace=True)
        self.assertEqual(changed['revision'], 2)

    def test_profile_names_follow_lowercase_length_and_reserved_word_rules(self):
        valid = ('a', '0', 'a' * 48, 'work-2_backup', 'default', 'current')
        for name in valid:
            with self.subTest(valid=name):
                self.assertEqual(self.store.save(name, self.settings())['name'], name)
        invalid = ('a' * 49, 'Work', 'work.backup', '_work', '-work',
            'status', 'list', 'use', 'add', 'save', 'import', 'edit', 'remove',
            'undo', 'doctor', 'slots', 'init', 'single', 'models', 'version',
            'help', 'migrate', 'update', 'run', 'preset')
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        for name in invalid:
            with self.subTest(invalid=name), self.assertRaises(ValueError):
                self.store.save(name, self.settings())
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_auth_selection_is_explicit_and_missing_auth_cannot_apply(self):
        both = self.settings()
        both['env']['ANTHROPIC_AUTH_TOKEN'] = 'other-token'
        with self.assertRaises(ValueError):
            self.store.save('both', both)
        chosen = self.store.save('both', both, auth='bearer_token')
        self.assertEqual(chosen['settings']['env']['ANTHROPIC_API_KEY'], '')
        self.assertEqual(chosen['auth_type'], 'bearer_token')
        self.store.save('empty', {'env': {'ANTHROPIC_BASE_URL': 'http://a.example'}})
        with self.assertRaises(ValueError):
            self.store.apply('empty')
        self.assertFalse(self.store.settings_path.exists())

    def test_helper_cloud_and_oauth_sources_are_not_silently_projected(self):
        examples = [{'apiKeyHelper': 'do-not-run'},
            {'env': {'CLAUDE_CODE_USE_BEDROCK': '1'}},
            {'env': {'CLAUDE_CODE_USE_VERTEX': 'true'}},
            {'env': {'CLAUDE_CODE_USE_FOUNDRY': '1'}},
            {'env': {'CLAUDE_CODE_OAUTH_TOKEN': 'oauth-secret'}}]
        for i, example in enumerate(examples):
            with self.subTest(example=example), self.assertRaises(ValueError):
                self.store.save('blocked' + str(i), example)
        self.store.save('work', self.settings())
        self.write({'apiKeyHelper': 'do-not-run', 'hooks': {}})
        before = self.store.settings_path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.apply('work')
        self.assertEqual(self.store.settings_path.read_bytes(), before)

    def test_shell_conflicts_are_reported_and_cloud_shell_blocks_apply(self):
        self.store.save('work', self.settings())
        self.store.apply('work')
        with patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'shell-old',
                                    'ANTHROPIC_MODEL': 'different'}):
            conflicts = self.store.status()['shell_conflicts']
            self.assertIn('ANTHROPIC_AUTH_TOKEN', [c['key'] for c in conflicts])
            self.assertIn('ANTHROPIC_MODEL', [c['key'] for c in conflicts])
        before = self.store.settings_path.read_bytes()
        with patch.dict(os.environ, {'CLAUDE_CODE_USE_VERTEX': '1'}):
            with self.assertRaises(ValueError):
                self.store.apply('work')
        self.assertEqual(self.store.settings_path.read_bytes(), before)

    def test_managed_settings_block_and_credentials_existence_is_informational(self):
        self.store.save('work', self.settings())
        path = self.write({'model': 'locked'}, self.config / 'managed-settings.json')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.apply('work')
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        credentials = self.write({'claudeAiOauth': {'accessToken': 'secret'}},
                                 self.config / '.credentials.json')
        before = credentials.read_bytes()
        self.assertTrue(self.store.apply('work')['success'])
        self.assertTrue(self.store.status()['credentials_present'])
        self.assertEqual(credentials.read_bytes(), before)

    def test_backups_and_undo_restore_managed_fields_keep_new_unmanaged_fields(self):
        self.write({'model': 'original', 'env': {'ANTHROPIC_AUTH_TOKEN': 'before',
            'KEEP': 'unchanged'}, 'hooks': {'SessionStart': []}})
        self.store.save('work', self.settings())
        self.store.apply('work')
        edited = self.read()
        edited['permissions'] = {'allow': ['Read']}
        edited['env']['LATER'] = 'keep'
        self.write(edited)
        result = self.store.undo()
        self.assertTrue(result['success'])
        self.assertEqual(result['env']['ANTHROPIC_API_KEY'], '')
        self.assertEqual(self.read()['model'], 'original')
        self.assertEqual(self.read()['env']['ANTHROPIC_AUTH_TOKEN'], 'before')
        self.assertEqual(self.read()['env']['LATER'], 'keep')
        self.assertEqual(self.read()['permissions'], {'allow': ['Read']})
        self.assertIsNone(self.store.status()['profile'])
        self.assertTrue(list(self.root.rglob('*.json')))

    def test_undo_refuses_manual_managed_edit(self):
        self.store.save('work', self.settings())
        self.store.apply('work')
        edited = self.read()
        edited['env']['ANTHROPIC_MODEL'] = 'manual-change'
        self.write(edited)
        self.assertFalse(self.store.status()['file_matches'])
        with self.assertRaises(ValueError):
            self.store.undo()
        self.assertEqual(self.read()['env']['ANTHROPIC_MODEL'], 'manual-change')

    def test_status_distinguishes_file_changes_and_saved_revision_changes(self):
        self.store.save('work', self.settings())
        self.store.apply('work')
        self.assertTrue(self.store.status()['file_matches'])
        self.assertTrue(self.store.status()['saved_matches'])
        self.store.save('work', self.settings(model='opus'), replace=True)
        status = self.store.status()
        self.assertTrue(status['file_matches'])
        self.assertFalse(status['saved_matches'])

    def test_temporary_override_does_not_modify_saved_profile(self):
        self.store.save('work', self.settings())
        self.store.apply('work', settings_override=self.settings(model='temporary'))
        self.assertEqual(self.read()['env']['ANTHROPIC_MODEL'], 'temporary')
        self.assertEqual(self.store.get('work')['settings']['env']['ANTHROPIC_MODEL'], 'sonnet')
        self.assertTrue(self.store.status()['saved_matches'])

    def test_remove_checks_all_targets_using_the_store(self):
        self.store.save('work', self.settings())
        self.store.apply('work')
        other = ProfileStore(config_dir=self.base / 'other', root=self.root)
        with self.assertRaises(ValueError):
            other.remove('work')
        self.store.undo()
        other.remove('work')
        self.assertEqual(other.list_profiles(), [])

    def test_private_permissions_and_private_list_data(self):
        self.store.save('work', self.settings())
        self.store.apply('work')
        for path in [self.root] + list(self.root.rglob('*')):
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o700 if path.is_dir() else 0o600, str(path))
        self.assertEqual(stat.S_IMODE(self.store.settings_path.stat().st_mode), 0o600)
        self.assertEqual(self.store.list_profiles()[0]['settings']['env']['ANTHROPIC_API_KEY'], 'key-A')

    def test_state_failure_reports_partial_target_write_and_recovery_file(self):
        self.store.save('work', self.settings())
        replace = os.replace

        def obstruct_state(source, destination):
            replace(source, destination)
            if Path(destination) == self.store.settings_path:
                (self.root / 'state.json').mkdir()

        # Fault only the filesystem boundary, keeping real target and backup IO.
        with patch('ccswitch_profiles.os.replace', side_effect=obstruct_state):
            result = self.store.apply('work')
        self.assertFalse(result['success'])
        self.assertTrue(result['partial'])
        self.assertTrue(result['applied'])
        self.assertEqual(result['env'], {})
        self.assertEqual(self.read()['env']['ANTHROPIC_API_KEY'], 'key-A')
        records = json.loads(Path(result['backup']).read_text())['records']
        self.assertEqual(records[-1]['before'], {'env': {}})

    def test_apply_and_undo_report_partial_when_directory_sync_fails_after_replacement(self):
        self.store.save('work', self.settings())
        real_open, real_fsync = os.open, os.fsync
        for operation in ('apply', 'undo'):
            for fault in ('open', 'fsync'):
                with self.subTest(operation=operation, fault=fault):
                    store = ProfileStore(config_dir=self.base / (operation + '-' + fault), root=self.root)
                    self.write(self.settings(key='before-key'), store.settings_path)
                    if operation == 'undo':
                        store.apply('work')
                    state_path = self.root / 'state.json'
                    before_state = state_path.read_bytes() if state_path.exists() else None
                    directory = store.config_dir.stat()

                    def fail_open(path, flags, *args, **kwargs):
                        if str(path) == str(store.config_dir) and flags == os.O_RDONLY:
                            raise OSError('injected directory open failure')
                        return real_open(path, flags, *args, **kwargs)

                    def fail_fsync(descriptor):
                        info = os.fstat(descriptor)
                        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (directory.st_dev, directory.st_ino):
                            raise OSError('injected directory fsync failure')
                        return real_fsync(descriptor)

                    boundary = 'os.open' if fault == 'open' else 'os.fsync'
                    effect = fail_open if fault == 'open' else fail_fsync
                    with patch('ccswitch_profiles.' + boundary, side_effect=effect):
                        result = store.apply('work') if operation == 'apply' else store.undo()
                    self.assertFalse(result['success'])
                    self.assertTrue(result['applied'])
                    self.assertTrue(result['partial'])
                    self.assertEqual(result['env'], {})
                    expected_key = 'key-A' if operation == 'apply' else 'before-key'
                    written = json.loads(store.settings_path.read_text())
                    self.assertEqual(written['env']['ANTHROPIC_API_KEY'], expected_key)
                    self.assertEqual(state_path.read_bytes() if state_path.exists() else None, before_state)
                    records = json.loads(Path(result['backup']).read_text())['records']
                    self.assertEqual(records[-1]['id'], result['backup_id'])
                    self.assertIn('sync', ' '.join(result['warnings']))

    def test_malformed_state_prevents_target_write(self):
        self.store.save('work', self.settings())
        (self.root / 'state.json').mkdir()
        # A malformed state prevents any write rather than discarding state.
        with self.assertRaises((ValueError, OSError)):
            self.store.apply('work')
        self.assertFalse(self.store.settings_path.exists())

    def test_target_changed_during_backup_is_not_replaced(self):
        self.store.save('work', self.settings())
        self.write({'hooks': {'initial': True}})
        replace = os.replace

        def concurrent_edit(source, destination):
            replace(source, destination)
            if Path(destination).parent == self.root / 'backups':
                self.write({'hooks': {'external': True}})

        with patch('ccswitch_profiles.os.replace', side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError, 'changed externally'):
                self.store.apply('work')
        self.assertEqual(self.read(), {'hooks': {'external': True}})

    def test_recovery_records_are_limited_to_ten_per_target(self):
        self.store.save('work', self.settings())
        for i in range(12):
            result = self.store.apply('work', settings_override=self.settings(model='model-' + str(i)))
        records = json.loads(Path(result['backup']).read_text())['records']
        self.assertEqual(len(records), 10)
        self.assertEqual(records[0]['before']['env']['ANTHROPIC_MODEL'], 'model-1')
        self.store.undo()
        self.assertEqual(self.read()['env']['ANTHROPIC_MODEL'], 'model-10')

    def test_undo_saves_recovery_record_before_restoring(self):
        self.store.save('work', self.settings())
        applied = self.store.apply('work')
        result = self.store.undo()
        records = json.loads(Path(result['backup']).read_text())['records']
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]['before']['env']['ANTHROPIC_API_KEY'], 'key-A')
        self.assertNotEqual(result['backup_id'], applied['backup_id'])

    def test_flat_snapshot_with_cloud_flag_is_not_converted_to_static_auth(self):
        flat = {'ANTHROPIC_BASE_URL': 'http://a.example', 'ANTHROPIC_API_KEY': 'key',
                'CLAUDE_CODE_USE_BEDROCK': '1'}
        with self.assertRaisesRegex(ValueError, 'CLAUDE_CODE_USE_BEDROCK'):
            self.store.save('cloud', flat)


class ProjectionTests(unittest.TestCase):
    def test_picker_model_only_rows_import_and_apply_without_adding_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = ProfileStore(config_dir=base / 'claude', root=base / 'private')
            settings = {'env': {'ANTHROPIC_BASE_URL': 'http://a.example', 'ANTHROPIC_API_KEY': 'key'},
                'modelPicker': {'options': [{'model': 'model-only'}, {'model': 'other-id', 'label': 'Named'}]}}
            with patch.dict(os.environ, {}, clear=True):
                projected = extract_settings(settings)
                store.save('work', settings)
                self.assertTrue(store.apply('work')['success'])
            self.assertEqual(projected['modelPicker'], settings['modelPicker'])
            self.assertEqual(json.loads(store.settings_path.read_text())['modelPicker'], settings['modelPicker'])

    def test_projection_preserves_registered_advanced_fields_only(self):
        settings = {'env': {'ANTHROPIC_DEFAULT_MODEL': 'exact[1m]',
            'ANTHROPIC_DEFAULT_FABLE_MODEL_NAME': 'Fable custom',
            'ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES': 'vision,thinking',
            'ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES': 'vision',
            'CLAUDE_CODE_SUBAGENT_MODEL_FORCE': '1', 'ANTHROPIC_UNKNOWN': 'drop'},
            'model': 'fixed-id', 'hooks': {}, 'modelPicker': {'replaceBuiltInOptions': False,
                'advanced': {'keep': True}, 'options': [{'model': 'custom-id[1m]',
                'label': 'Custom', 'description': 'Description', 'behavesAs': 'sonnet'}]}}
        projected = extract_settings(settings)
        self.assertNotIn('hooks', projected)
        self.assertNotIn('ANTHROPIC_UNKNOWN', projected['env'])
        self.assertEqual(projected['env']['ANTHROPIC_DEFAULT_MODEL'], 'exact[1m]')
        self.assertEqual(projected['modelPicker'], settings['modelPicker'])
        self.assertIn('ANTHROPIC_DEFAULT_FABLE_MODEL_NAME', MANAGED_ENV_KEYS)
        self.assertIn('ANTHROPIC_DEFAULT_MODEL', MODEL_ENV_KEYS)
        self.assertEqual(TOP_LEVEL_KEYS, ('model', 'modelPicker'))

    def test_invalid_picker_models_and_control_values_are_rejected(self):
        cases = [{'env': {'ANTHROPIC_API_KEY': 'secret\nnext'}},
            {'modelPicker': {'options': 'wrong'}},
            {'modelPicker': {'replaceBuiltInOptions': 'false', 'options': []}},
            {'modelPicker': {'options': [{'model': '', 'label': 'empty'}]}},
            {'modelPicker': {'options': [{'model': 'model', 'label': None}]}},
            {'modelPicker': {'options': [{'model': 'model', 'label': ''}]}},
            {'model': 'with whitespace'}, {'env': []}, {'modelPicker': None}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                extract_settings(case)

    def test_recursive_redaction_covers_nested_auth_and_sensitive_values(self):
        private = {'settings': {'env': {'ANTHROPIC_API_KEY': 'api-secret',
            'ANTHROPIC_AUTH_TOKEN': 'bearer-secret', 'ANTHROPIC_MODEL': 'sonnet'}},
            'items': [{'accessToken': 'oauth-secret'}],
            'shell_conflicts': [{'key': 'ANTHROPIC_API_KEY', 'actual': 'api-secret', 'expected': 'new-secret'}]}
        public = redact(private)
        encoded = json.dumps(public)
        for secret in ('api-secret', 'bearer-secret', 'oauth-secret', 'new-secret'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(public['settings']['env']['ANTHROPIC_MODEL'], 'sonnet')
        self.assertEqual(private['settings']['env']['ANTHROPIC_API_KEY'], 'api-secret')

    def test_sensitive_subtrees_are_redacted_without_hiding_status_booleans(self):
        public = redact({'credentials': {'value': 'nested-secret'},
                         'apiKey': ['array-secret'], 'credentials_present': True,
                         'password': 12345})
        self.assertNotIn('nested-secret', json.dumps(public))
        self.assertNotIn('array-secret', json.dumps(public))
        self.assertNotIn('12345', json.dumps(public))
        self.assertIs(public['credentials_present'], True)


if __name__ == '__main__':
    unittest.main()
