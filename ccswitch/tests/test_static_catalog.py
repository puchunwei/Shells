"""The shipped catalog is a dated offline snapshot, refreshed deliberately."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'lib'
SPEC = importlib.util.spec_from_file_location('static_backend', LIB / 'ccswitch_backend.py')
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


class StaticCatalogTests(unittest.TestCase):
    def test_snapshot_has_date_and_all_fifteen_verified_model_ids(self):
        path = LIB / 'cloudcli-models.json'
        self.assertTrue(path.is_file())
        snapshot = json.loads(path.read_text())
        self.assertEqual(snapshot['updated_at'], '2026-10-16')
        self.assertEqual([m['id'] for m in snapshot['models']], [
            'claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8',
            'claude-opus-5', 'claude-opus-5-5', 'claude-sonnet-5',
            'gpt-5.6-sol', 'gpt-6-sol', 'gpt-6-luna',
            'qwen3.8-max', 'qwen3.7-max', 'qwen3.7-plus',
            'glm-5.2', 'deepseek-v4-pro', 'qwen3.8-flash'])
        self.assertTrue(all('anthropic' in m['protocols'] for m in snapshot['models']))

    def test_managed_connection_reads_static_catalog_without_network_or_sdk(self):
        settings = {'env': {
            'ANTHROPIC_BASE_URL': 'https://ducky.code.alibaba-inc.com/proxy',
            'ANTHROPIC_AUTH_TOKEN': 'offline-test-token'}}
        env = {k: v for k, v in os.environ.items() if k != 'CCSWITCH_CLOUDCLI_MODEL_SDK'}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(socket, 'socket', side_effect=AssertionError('unexpected network')), \
                patch.object(BACKEND.subprocess, 'run', side_effect=AssertionError('unexpected SDK')):
            models, live = BACKEND.load_model_catalog(settings=settings)
        self.assertFalse(live)
        self.assertEqual(len(models), 15)

    def test_returned_catalog_cannot_mutate_shipped_snapshot(self):
        with patch.dict(os.environ, CCSWITCH_CLOUDCLI_MODEL_SDK=''):
            models, _ = BACKEND.load_model_catalog(settings={})
            models[0]['protocols'].clear()
            again, _ = BACKEND.load_model_catalog(settings={})
        self.assertIn('anthropic', again[0]['protocols'])

    def test_claude_context_and_configured_id_are_explicit(self):
        for model in BACKEND.FALLBACK_MODELS:
            with self.subTest(model=model['id']):
                if model['id'].startswith('claude-'):
                    self.assertEqual(model.get('context_window_tokens'), 1000000)
                    expected = model['id'] + '[1m]'
                    self.assertEqual(model.get('claude_code_model', model['id']), expected)
                else:
                    self.assertNotIn('claude_code_model', model)

    def test_sdk_rows_reuse_known_claude_context_metadata(self):
        for model in BACKEND.FALLBACK_MODELS:
            row = BACKEND._normalize_catalog_entry({
                'model_id': model['id'], 'display_name': model['name'],
                'supported_protoc': model['protocols']})
            selected_id, label = BACKEND.catalog_model_choice(row)
            with self.subTest(model=model['id']):
                self.assertEqual(selected_id, model.get('claude_code_model', model['id']))
                self.assertEqual('（1M）' in label, model['id'].startswith('claude-'))
        row = {'id': 'claude-future-custom', 'name': 'Custom', 'protocols': ['anthropic']}
        self.assertEqual(BACKEND.catalog_model_choice(row)[0], 'claude-future-custom')


if __name__ == '__main__':
    unittest.main()
