"""Drive real terminal keys and verify saved settings, cancellation and tty state."""
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import fcntl

BACKEND = Path(__file__).resolve().parents[1] / 'lib/ccswitch_backend.py'
DOWN = b'\x1b[B'
END = b'\x1b[F'
ENTER = b'\r'


class MenuUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'claude'
        self.config.mkdir()
        self.settings = self.config / 'settings.json'
        self.source = self.root / 'input.json'
        self.data = {'env': {'ANTHROPIC_BASE_URL': 'https://gateway.test',
                             'ANTHROPIC_AUTH_TOKEN': 'menu-private-token',
                             'ANTHROPIC_DEFAULT_OPUS_MODEL': 'Vendor/Opus[1m]',
                             'ANTHROPIC_DEFAULT_SONNET_MODEL': 'Vendor/Sonnet',
                             'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'Vendor/Fast'},
                     'model': 'sonnet', 'permissions': {'allow': ['Read']}}
        self.source.write_text(json.dumps(self.data))
        self.settings.write_text(json.dumps(self.data))
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('ANTHROPIC_', 'CLAUDE_', 'CCSWITCH_', 'XDG_'))}
        self.env.update(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'xdg'),
                        CLAUDE_CONFIG_DIR=str(self.config), TERM='xterm-256color',
                        PYTHONDONTWRITEBYTECODE='1',
                        CCSWITCH_CLOUDCLI_MODEL_SDK=str(self.root / 'missing-sdk'))
        self.cli('import', 'work', '--from', str(self.source))

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-B', str(BACKEND), *args], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def terminal(self, args, steps, *, env=None, rows=24):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, 80, 0, 0))
        before = termios.tcgetattr(slave)
        process = subprocess.Popen([sys.executable, '-B', str(BACKEND), *args],
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env=env or self.env, cwd=self.root)
        output = b''
        pending = b''
        try:
            for marker, keys in steps:
                marker = marker.encode()
                deadline = time.monotonic() + 3
                while marker not in pending and time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        pending += os.read(master, 65536)
                output += pending
                self.assertIn(marker, pending, output.decode(errors='replace'))
                pending = b''
                os.write(master, keys)
            deadline = time.monotonic() + 3
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output += os.read(master, 65536)
            self.assertEqual(process.wait(timeout=1), 0, output.decode(errors='replace'))
            self.assertEqual(termios.tcgetattr(slave), before, 'terminal mode was not restored')
            self.assertNotIn(b'menu-private-token', output)
            return output.decode(errors='replace')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            os.close(slave)

    def test_arrows_choose_sonnet_existing_model_and_apply_without_typing(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', DOWN + DOWN + ENTER),
            ('编辑槽位', ENTER),
        ])
        saved = json.loads((self.root / 'xdg/ccswitch/profiles/work.json').read_text())
        actual = json.loads(self.settings.read_text())
        self.assertEqual(saved['settings']['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Vendor/Fast')
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Vendor/Fast')
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Opus[1m]')
        self.assertEqual(actual['env']['ANTHROPIC_AUTH_TOKEN'], 'menu-private-token')
        self.assertEqual(actual['permissions'], {'allow': ['Read']})

    def test_model_escape_returns_to_editor_and_escape_discards_draft(self):
        before = self.snapshot()
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', b'\x1b'),
            ('编辑槽位', b'\x1b'),
        ])
        self.assertEqual(self.snapshot(), before)

    def test_arrows_set_fable_from_catalog_and_apply(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN * 3 + ENTER),
            ('选择 Fable 模型', END + b'\x1b[A' + ENTER),
            ('CloudCLI 本地模型清单', DOWN * 4 + ENTER),
            ('编辑槽位', ENTER),
        ])
        saved = json.loads((self.root / 'xdg/ccswitch/profiles/work.json').read_text())
        actual = json.loads(self.settings.read_text())
        for settings in (saved['settings'], actual):
            self.assertEqual(settings['env']['ANTHROPIC_DEFAULT_FABLE_MODEL'], 'claude-opus-5-5[1m]')
            self.assertEqual(settings['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'Vendor/Opus[1m]')

    def test_startup_and_subagent_can_follow_fable(self):
        for slot, index, label, key in (
                ('startup', 4, '默认启动', 'ANTHROPIC_MODEL'),
                ('subagent', 5, '子代理默认', 'CLAUDE_CODE_SUBAGENT_MODEL')):
            with self.subTest(slot=slot):
                self.terminal(['slots', 'edit', 'work'], [
                    ('编辑槽位', DOWN * index + ENTER),
                    ('选择 ' + label + ' 模型', b'\x1b[H' + DOWN * 3 + ENTER),
                    ('编辑槽位', ENTER),
                ])
                actual = json.loads(self.settings.read_text())
                self.assertEqual(actual['env'][key], 'fable')
                if slot == 'startup':
                    self.assertEqual(actual['model'], 'fable')

    def test_ctrl_c_discards_draft_and_restores_terminal(self):
        before = self.snapshot()
        self.terminal(['slots', 'edit', 'work'], [('编辑槽位', b'\x03')])
        self.assertEqual(self.snapshot(), before)

    def test_custom_model_keeps_exact_id_and_save_does_not_apply(self):
        before = self.settings.read_bytes()
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', END + ENTER),
            ('模型 ID（Esc 返回）:', b'Other/Exact[1m]\n'),
            ('编辑槽位', DOWN + ENTER),
        ])
        saved = json.loads((self.root / 'xdg/ccswitch/profiles/work.json').read_text())
        self.assertEqual(saved['settings']['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Other/Exact[1m]')
        self.assertEqual(self.settings.read_bytes(), before)

    def test_typed_model_id_does_not_collapse_a_case_distinct_existing_id(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', b'vendor/sonnet\n'),
            ('编辑槽位', ENTER),
        ])
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'vendor/sonnet')

    def test_choose_profile_and_confirm_with_arrows(self):
        self.terminal(['use'], [
            ('选择配置', DOWN + ENTER),  # auto-imported current, then work
            ('确认应用', DOWN + ENTER),
        ])
        status = json.loads(self.cli('status', '--json').stdout)
        self.assertEqual(status['profile'], 'work')
        self.assertTrue(status['file_matches'])

    def test_profile_confirmation_defaults_to_cancel(self):
        before = self.snapshot()
        self.terminal(['use'], [('选择配置', ENTER), ('确认应用', ENTER)])
        self.assertEqual(self.snapshot(), before)

    def test_use_menu_can_delete_a_saved_profile_with_arrows(self):
        before = self.settings.read_bytes()
        self.terminal(['use'], [
            ('选择配置', END + ENTER),
            ('选择要删除的配置', DOWN + ENTER),
            ('确认删除以上保存的配置', DOWN + ENTER),
        ])
        self.assertEqual([row['name'] for row in json.loads(self.cli('list', '--json').stdout)],
                         ['current'])
        self.assertEqual(self.settings.read_bytes(), before)

    def test_remove_picker_defaults_to_cancel_and_keeps_all_files(self):
        before = self.snapshot()
        self.terminal(['remove'], [
            ('选择要删除的配置', DOWN + ENTER),
            ('确认删除以上保存的配置', ENTER),
        ])
        self.assertEqual(self.snapshot(), before)

    def test_remove_picker_can_confirm_and_preserve_active_settings(self):
        before = self.settings.read_bytes()
        self.terminal(['remove'], [
            ('选择要删除的配置', DOWN + ENTER),
            ('确认删除以上保存的配置', DOWN + ENTER),
        ])
        self.assertFalse((self.root / 'xdg/ccswitch/profiles/work.json').exists())
        self.assertEqual(self.settings.read_bytes(), before)

    def test_escape_from_remove_picker_keeps_all_files(self):
        before = self.snapshot()
        self.terminal(['remove'], [('选择要删除的配置', b'\x1b')])
        self.assertEqual(self.snapshot(), before)

    def test_ambiguous_current_profile_is_chosen_with_arrows_before_editing(self):
        before = self.snapshot()
        self.terminal(['slots'], [
            ('选择要编辑的配置', DOWN + ENTER),
            ('编辑槽位', b'\x1b'),
        ])
        self.assertEqual(self.snapshot(), before)

    def test_startup_can_follow_sonnet_from_the_menu(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN * 4 + ENTER),
            ('选择 默认启动 模型', ENTER),  # current setting is already sonnet
            ('编辑槽位', ENTER),
        ])
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_MODEL'], 'sonnet')
        self.assertEqual(actual['model'], 'sonnet')

    def test_explicit_catalog_lists_claude_compatible_reference_models(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', DOWN * 3 + ENTER),
            ('CloudCLI 本地模型清单', DOWN * 9 + ENTER),
            ('编辑槽位', ENTER),
        ])
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'qwen3.8-max')

    def test_catalog_arrows_can_select_new_opus_model_from_all_fifteen(self):
        output = self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', DOWN * 3 + ENTER),
            ('CloudCLI 本地模型清单', DOWN * 4 + ENTER),
            ('编辑槽位', ENTER),
        ])
        self.assertIn('15 个', output)
        self.assertIn('gpt-6-luna', output)
        self.assertIn('2026-10-16', output)
        self.assertNotIn('正在读取', output)
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'claude-opus-5-5[1m]')

    def test_catalog_claude_models_save_with_one_million_context(self):
        for index, expected in enumerate((
                'claude-opus-4-6[1m]', 'claude-opus-4-7[1m]', 'claude-opus-4-8[1m]',
                'claude-opus-5[1m]', 'claude-opus-5-5[1m]', 'claude-sonnet-5[1m]')):
            with self.subTest(model=expected):
                output = self.terminal(['slots', 'edit', 'work'], [
                    ('编辑槽位', DOWN + ENTER),
                    ('选择 Sonnet 模型', END + b'\x1b[A' + ENTER),
                    ('CloudCLI 本地模型清单', DOWN * index + ENTER),
                    ('编辑槽位', ENTER),
                ])
                actual = json.loads(self.settings.read_text())
                self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], expected)
                self.assertIn('Claude Opus 4.6（1M）', output)
                self.assertIn('Claude Sonnet 5（1M）', output)

    def test_manual_claude_id_is_saved_exactly_as_entered(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', END + ENTER),
            ('模型 ID（Esc 返回）:', b'claude-opus-4-6\n'),
            ('编辑槽位', ENTER),
        ])
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'claude-opus-4-6')

    def test_small_terminal_can_reach_custom_input_and_cancel(self):
        before = self.snapshot()
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', END + ENTER),
            ('模型 ID（Esc 返回）:', b'cancel\n'),
            ('选择 Sonnet 模型', b'\x1b'),
            ('编辑槽位', b'\x1b'),
        ], rows=8)
        self.assertEqual(self.snapshot(), before)

    def test_escape_from_custom_text_prompt_returns_without_saving(self):
        before = self.snapshot()
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', DOWN + ENTER),
            ('选择 Sonnet 模型', END + ENTER),
            ('模型 ID（Esc 返回）:', b'\x1b'),
            ('选择 Sonnet 模型', b'\x1b'),
            ('编辑槽位', b'\x1b'),
        ])
        self.assertEqual(self.snapshot(), before)

    def test_dumb_terminal_can_select_numbered_choices(self):
        self.terminal(['slots', 'edit', 'work'], [
            ('编辑槽位', b'2\n'),
            ('选择 Sonnet 模型', b'3\n'),
            ('编辑槽位', b'8\n'),
        ], env=dict(self.env, TERM='dumb'))
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'Vendor/Fast')


if __name__ == '__main__':
    unittest.main()
