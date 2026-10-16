"""Offline installer integration with temporary HOME and actual installed commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('backend', 'profiles', 'cli', 'slots', 'ui')


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home with spaces'
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('CCSWITCH_', 'CLAUDE_', 'ANTHROPIC_', 'XDG_'))}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'xdg'),
                        PYTHONDONTWRITEBYTECODE='1')
        self.target = self.home / '.claude'
        self.target.mkdir()
        self.settings = self.target / 'settings.json'
        self.snapshot = self.target / 'ccswitch-defaults.json'
        self.settings.write_bytes(b'{"env":{"ANTHROPIC_AUTH_TOKEN":"old"}}\n')
        self.snapshot.write_bytes(b'{"ANTHROPIC_AUTH_TOKEN":"legacy"}\n')
        self.store = self.home / 'xdg/ccswitch/profiles/work.json'
        self.store.parent.mkdir(parents=True)
        self.store.write_bytes(b'private-store-marker\n')

    def install(self, shell, *args):
        return subprocess.run(['bash', str(ROOT / 'install.sh'), '--local', '--shell', shell, *args],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_local_install_all_modules_autoload_and_idempotent_update(self):
        for shell in ('bash', 'zsh', 'fish'):
            with self.subTest(shell=shell):
                before = {p: p.read_bytes() for p in (self.settings, self.snapshot, self.store)}
                result = self.install(shell)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                runtime = self.home / '.local/share/ccswitch'
                for module in MODULES:
                    self.assertTrue((runtime / ('ccswitch_' + module + '.py')).is_file())
                snapshot = json.loads((runtime / 'cloudcli-models.json').read_text())
                self.assertEqual(len(snapshot['models']), 15)
                executable = self.home / '.local/bin/ccswitch'
                result = subprocess.run([str(executable), 'version', '--json'], env=self.env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'version': '0.6.6'})
                rc = self.home / ('.zshrc' if shell == 'zsh' else '.bashrc')
                original_rc = rc.read_bytes() if rc.exists() else None
                for mode in ((), ('--update',)):
                    result = self.install(shell, *mode)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual({p: p.read_bytes() for p in before}, before)
                    if shell != 'fish': self.assertEqual(rc.read_bytes(), original_rc)
                if shutil.which(shell):
                    command = 'ccswitch version --json' if shell == 'fish' else 'source "$HOME/.' + shell + 'rc"; ccswitch version --json'
                    result = subprocess.run([shutil.which(shell), '-c', command], env=self.env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'version': '0.6.6'})

    def test_rc_comment_and_custom_paths_do_not_suppress_actual_registration(self):
        for shell in ('bash', 'zsh'):
            with self.subTest(shell=shell):
                rc = self.home / ('.' + shell + 'rc')
                original = '# source "$HOME/.local/share/ccswitch/ccswitch.bash"\nsource /old/custom/ccswitch.bash\nsource \'$HOME/.local/share/ccswitch/ccswitch.bash\'\n# user content\n'
                rc.write_text(original)
                self.assertEqual(self.install(shell).returncode, 0)
                expected = 'source "$HOME/.local/share/ccswitch/ccswitch.bash"'
                self.assertTrue(rc.read_text().startswith(original))
                self.assertEqual(rc.read_text().splitlines().count(expected), 1)
                before = rc.read_bytes()
                self.assertEqual(self.install(shell, '--update').returncode, 0)
                self.assertEqual(rc.read_bytes(), before)

    def test_rc_previous_official_active_source_is_not_duplicated(self):
        rc = self.home / '.bashrc'
        original = '  source ~/.local/share/ccswitch/ccswitch.bash\n'
        rc.write_text(original)
        self.assertEqual(self.install('bash').returncode, 0)
        self.assertEqual(rc.read_text(), original)

    def test_installed_standalone_applies_slots_and_undo_with_parent_shell_notice(self):
        result = self.install('bash')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.home / 'connection.json'
        source.write_text(json.dumps({'env': {'ANTHROPIC_BASE_URL': 'https://example.test',
                                              'ANTHROPIC_API_KEY': 'private-key'}}))
        env = dict(self.env, XDG_CONFIG_HOME=str(self.home / 'fresh-xdg'))
        executable = self.home / '.local/bin/ccswitch'
        for args in [('import', 'personal', '--from', str(source)), ('use', 'personal'),
                     ('slots', 'set', 'personal', 'sonnet', 'Vendor/New', '--apply'), ('undo',)]:
            result = subprocess.run([str(executable), *args], env=env, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('private-key', result.stdout + result.stderr)
            if args[0] != 'import':
                self.assertIn('parent shell', result.stderr)
        current = json.loads(self.settings.read_text())
        self.assertEqual(current['env']['ANTHROPIC_API_KEY'], 'private-key')
        self.assertFalse(current['env'].get('ANTHROPIC_DEFAULT_SONNET_MODEL'))

    def test_local_update_refuses_older_package_without_touching_install(self):
        result = self.install('bash')
        self.assertEqual(result.returncode, 0, result.stderr)
        package = Path(self.temp.name) / 'old-package'
        shutil.copytree(ROOT, package)
        (package / 'VERSION').write_text('0.5.9\n')
        before = (self.home / '.local/share/ccswitch/VERSION').read_bytes()
        result = subprocess.run(['bash', str(package / 'install.sh'), '--local', '--shell', 'bash', '--update'],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / '.local/share/ccswitch/VERSION').read_bytes(), before)

    def test_removed_default_guidance_has_no_apply_notice_or_config_changes(self):
        self.assertEqual(self.install('fish').returncode, 0)
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        executable = self.home / '.local/bin/ccswitch'
        for args in (('default',), ('default', 'glm-5.2'), ('default', '--restore')):
            with self.subTest(args=args):
                result = subprocess.run([str(executable), *args], env=self.env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertIn('ccswitch use default', result.stderr)
                self.assertNotIn('parent shell', result.stderr)
                self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before)

    def test_source_launcher_version_uses_selected_source_runtime(self):
        bindir = self.home / 'fakebin'
        bindir.mkdir()
        curl = bindir / 'curl'
        curl.write_text('#!/bin/sh\nexit 1\n')
        curl.chmod(0o755)
        result = subprocess.run(['bash', str(ROOT / 'bin/ccswitch'), 'version'],
                                env=dict(self.env, PATH=str(bindir) + ':' + self.env['PATH']),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ccswitch 0.6.6', result.stdout)

    def test_removed_credentials_options_rejected_without_echo_or_writes(self):
        result = self.install('bash', '--url', 'secret-url', '--key', 'secret-key')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('secret-', result.stdout + result.stderr)
        self.assertIn('ccswitch add', result.stdout + result.stderr)
        self.assertFalse((self.home / '.local/share/ccswitch').exists())


if __name__ == '__main__':
    unittest.main()
