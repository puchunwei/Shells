"""Real shell integration; all files and private exports stay in temporary HOME."""
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELLS = ('bash', 'zsh', 'fish')


class ShellWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / 'claude custom'
        self.config.mkdir()
        self.settings = self.config / 'settings.json'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('ANTHROPIC_', 'CLAUDE_', 'CCSWITCH_', 'XDG_'))}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'xdg'),
                        CLAUDE_CONFIG_DIR=str(self.config), TMPDIR=str(self.home),
                        CCSWITCH_BACKEND=str(ROOT / 'lib/ccswitch_backend.py'),
                        CCSWITCH_CLOUDCLI_MODEL_SDK=str(self.home / 'missing'),
                        PYTHONDONTWRITEBYTECODE='1')
        self.secret = '''personal token=$HOME ' " $(touch NEVER) `touch NEVER2` \\ end'''
        self.data = {'env': {'ANTHROPIC_BASE_URL': 'https://personal.test/anthropic',
                            'ANTHROPIC_AUTH_TOKEN': self.secret}, 'model': 'sonnet'}
        self.source = self.home / 'input.json'
        self.source.write_text(json.dumps(self.data))
        self.cli('import', 'personal', '--from', str(self.source))

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-B', self.env['CCSWITCH_BACKEND'], *args],
                                env=self.env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def shell_args(self, shell, command):
        executable = shutil.which(shell)
        if executable is None:
            self.skipTest(shell + ' unavailable')
        wrapper = ROOT / ('fish/ccswitch.fish' if shell == 'fish' else 'bash/ccswitch.bash')
        return [executable, '-c', 'source ' + shlex.quote(str(wrapper)) + '; ' + command]

    def run_shell(self, shell, command, env=None):
        return subprocess.run(self.shell_args(shell, command), env=env or self.env,
                              capture_output=True, text=True, timeout=10, cwd=self.home)

    def test_use_slots_apply_and_undo_sync_disk_and_parent_shell(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(shell, '''ccswitch use personal >/dev/null; test "$ANTHROPIC_AUTH_TOKEN" = "$EXPECTED" && test -z "$ANTHROPIC_API_KEY" && ccswitch slots set personal sonnet Vendor/Next --apply >/dev/null && test "$ANTHROPIC_DEFAULT_SONNET_MODEL" = Vendor/Next && ccswitch undo >/dev/null && test -z "$ANTHROPIC_DEFAULT_SONNET_MODEL"''',
                    dict(self.env, EXPECTED=self.secret, ANTHROPIC_API_KEY='stale-key'))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                current = json.loads(self.settings.read_text())
                self.assertEqual(current['env']['ANTHROPIC_AUTH_TOKEN'], self.secret)
                self.assertFalse(current['env'].get('ANTHROPIC_API_KEY'))
                self.assertFalse((self.home / 'NEVER').exists())
                self.assertFalse((self.home / 'NEVER2').exists())
                # Start the next shell from the same saved slot state.
                self.source.write_text(json.dumps(self.data))
                self.cli('save', 'personal', '--from', str(self.source), '--replace')
                self.assertFalse(list(self.home.glob('ccswitch-env.*')))

    def test_nonterminal_missing_name_and_failure_preserve_shell(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                command = ('ccswitch use; set -l rc $status; test $rc -ne 0 && test "$ANTHROPIC_AUTH_TOKEN" = before'
                           if shell == 'fish' else
                           'ccswitch use; rc=$?; test "$rc" -ne 0 && test "$ANTHROPIC_AUTH_TOKEN" = before')
                result = self.run_shell(shell, command, dict(self.env, ANTHROPIC_AUTH_TOKEN='before'))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.settings.exists())
                self.assertFalse(list(self.home.glob('ccswitch-env.*')))

    def test_private_protocol_whitelist_exit_status_and_cleanup(self):
        # A stand-in is necessary to exercise the boundary after a backend writes then fails.
        fake = self.home / 'boundary.py'
        fake.write_text("import os,sys\np=sys.argv[sys.argv.index('--shell-output')+1]\nassert os.stat(p).st_mode & 0o777 == 0o600\nopen(p,'w').write('ANTHROPIC_AUTH_TOKEN=after\\nPATH=/injected\\nANTHROPIC_NOT_MANAGED=no\\n')\nsys.exit(int(os.environ['BOUNDARY_EXIT']))\n")
        for shell in SHELLS:
            for code in (0, 7):
                with self.subTest(shell=shell, code=code):
                    save = 'set -l rc $status' if shell == 'fish' else 'rc=$?'
                    expected = 'after' if code == 0 else 'before'
                    result = self.run_shell(shell, f'ccswitch use personal; {save}; test "$rc" = {code} && test "$ANTHROPIC_AUTH_TOKEN" = {expected} && test "$PATH" = "$ORIGINAL_PATH" && test -z "$ANTHROPIC_NOT_MANAGED"',
                        dict(self.env, CCSWITCH_BACKEND=str(fake), BOUNDARY_EXIT=str(code),
                             ORIGINAL_PATH=self.env['PATH'], ANTHROPIC_AUTH_TOKEN='before'))
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse(list(self.home.glob('ccswitch-env.*')))

    def test_terminal_use_cancel_preserves_tty_and_shell(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                master, slave = pty.openpty()
                save = 'set -l rc $status' if shell == 'fish' else 'rc=$?'
                proc = subprocess.Popen(self.shell_args(shell,
                    f'ccswitch use; {save}; test "$rc" -eq 0 && test "$ANTHROPIC_AUTH_TOKEN" = before'),
                    stdin=slave, stdout=slave, stderr=slave,
                    env=dict(self.env, ANTHROPIC_AUTH_TOKEN='before'), cwd=self.home)
                os.close(slave)
                output = b''
                try:
                    deadline = time.monotonic() + 5
                    while '选择配置'.encode() not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            try: output += os.read(master, 65536)
                            except OSError: break
                    self.assertIn('选择配置'.encode(), output)
                    os.write(master, b'cancel\n')
                    self.assertEqual(proc.wait(timeout=3), 0, output)
                    self.assertFalse(self.settings.exists())
                    self.assertFalse(list(self.home.glob('ccswitch-env.*')))
                finally:
                    os.close(master)
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()

    def test_update_refuses_remote_downgrade_before_installer_download(self):
        bindir = self.home / 'fakebin'
        bindir.mkdir()
        curl = bindir / 'curl'
        curl.write_text('#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\na=sys.argv[1:]\nwith open(os.environ["FETCH_LOG"],"a") as f: f.write(" ".join(a)+"\\n")\nif any(x.endswith("/VERSION") for x in a): print(os.environ["REMOTE_VERSION"])\nelse: sys.exit(99)\n')
        curl.chmod(0o755)
        for shell in SHELLS:
            for version in ('0.5.9', 'invalid'):
                with self.subTest(shell=shell, version=version):
                    log = self.home / 'fetch.log'
                    log.write_text('')
                    result = self.run_shell(shell, 'ccswitch update',
                        dict(self.env, PATH=str(bindir) + ':' + self.env['PATH'],
                             FETCH_LOG=str(log), REMOTE_VERSION=version))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('/VERSION', log.read_text())
                    self.assertNotIn('/install.sh', log.read_text())


if __name__ == '__main__':
    unittest.main()
