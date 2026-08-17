import json
import os
import shutil
import subprocess
import tempfile
import unittest


CCSWITCH_ROOT = os.path.dirname(os.path.dirname(__file__))
MODEL_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]


class ShellWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = self.temp_dir.name
        self.claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(self.claude_dir)

        fish_dir = os.path.join(self.home, ".config", "fish", "functions")
        bash_dir = os.path.join(self.home, ".local", "share", "ccswitch")
        os.makedirs(fish_dir, exist_ok=True)
        os.makedirs(bash_dir, exist_ok=True)
        for source, destination in [
            ("fish/ccswitch.fish", os.path.join(fish_dir, "ccswitch.fish")),
            (
                "fish/_ccswitch_normalize_model.fish",
                os.path.join(fish_dir, "_ccswitch_normalize_model.fish"),
            ),
            ("lib/ccswitch_backend.py", os.path.join(fish_dir, "ccswitch_backend.py")),
            ("VERSION", os.path.join(fish_dir, "VERSION")),
            ("bash/ccswitch.bash", os.path.join(bash_dir, "ccswitch.bash")),
            ("lib/ccswitch_backend.py", os.path.join(bash_dir, "ccswitch_backend.py")),
            ("VERSION", os.path.join(bash_dir, "VERSION")),
        ]:
            shutil.copyfile(os.path.join(CCSWITCH_ROOT, source), destination)

        self.settings_path = os.path.join(self.claude_dir, "settings.json")
        self.defaults_path = os.path.join(self.claude_dir, "ccswitch-defaults.json")
        self.initial_settings = {
            "permissions": {"allow": ["Read"]},
            "env": {
                "ANTHROPIC_BASE_URL": "http://mo.example/v1/anthropic",
                "ANTHROPIC_API_KEY": "mo-key",
                **{key: "claude-opus-4-6" for key in MODEL_KEYS},
            },
            "model": "claude-opus-4-6",
        }
        defaults = {
            "ANTHROPIC_BASE_URL": "http://default.example/v1/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "default-token",
            **{key: "qwen3.7-max" for key in MODEL_KEYS},
        }
        defaults["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "claude-sonnet-5"
        self.write_json(self.settings_path, self.initial_settings)
        self.write_json(self.defaults_path, defaults)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def write_json(path, value):
        with open(path, "w", encoding="utf-8") as output:
            json.dump(value, output)

    def read_settings(self):
        with open(self.settings_path, encoding="utf-8") as settings_file:
            return json.load(settings_file)

    def run_shell(self, shell, command):
        env = os.environ.copy()
        env.update({
            "HOME": self.home,
            "CCSWITCH_CLOUDCLI_MODEL_SDK": os.path.join(self.home, "missing-sdk.js"),
            "CCSWITCH_TTY_PATH": os.path.join(self.home, "missing-tty"),
        })
        if shell == "fish":
            wrapper = os.path.join(
                self.home, ".config", "fish", "functions", "ccswitch.fish"
            )
            script = f"source {wrapper}; {command}"
            executable = shutil.which("fish")
        else:
            wrapper = os.path.join(
                self.home, ".local", "share", "ccswitch", "ccswitch.bash"
            )
            script = f"source {wrapper}; {command}"
            executable = shutil.which("bash")
        return subprocess.run(
            [executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

    def test_restore_flag_restores_independent_snapshot_models(self):
        for shell in ("bash", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default --restore")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                settings = self.read_settings()
                self.assertEqual(settings["env"]["ANTHROPIC_MODEL"], "qwen3.7-max")
                self.assertEqual(
                    settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"],
                    "claude-sonnet-5",
                )
                self.assertEqual(settings["permissions"], {"allow": ["Read"]})

    def test_direct_model_is_validated_and_canonicalized(self):
        for shell in ("bash", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default GLM-5.2")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                settings = self.read_settings()
                self.assertEqual(settings["model"], "glm-5.2")
                self.assertTrue(
                    all(settings["env"][key] == "glm-5.2" for key in MODEL_KEYS)
                )

    def test_no_argument_without_tty_fails_without_modifying_settings(self):
        for shell in ("bash", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("当前不是交互式终端", result.stdout + result.stderr)
                self.assertEqual(self.read_settings(), self.initial_settings)


if __name__ == "__main__":
    unittest.main()
