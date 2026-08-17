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
CUSTOM_OPTION_KEYS = [
    "ANTHROPIC_CUSTOM_MODEL_OPTION",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
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
        defaults.update({
            "ANTHROPIC_CUSTOM_MODEL_OPTION": "snapshot-model",
            "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": "Snapshot Model",
            "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION": "Saved by init",
        })
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

    def run_shell(self, shell, command, extra_env=None):
        env = os.environ.copy()
        env.update({
            "HOME": self.home,
            "CCSWITCH_CLOUDCLI_MODEL_SDK": os.path.join(self.home, "missing-sdk.js"),
        })
        if extra_env:
            env.update(extra_env)
        if shell == "fish":
            wrapper = os.path.join(
                self.home, ".config", "fish", "functions", "ccswitch.fish"
            )
            script = f"source {wrapper}; {command}"
        else:
            wrapper = os.path.join(
                self.home, ".local", "share", "ccswitch", "ccswitch.bash"
            )
            script = f"source {wrapper}; {command}"
        executable = shutil.which(shell)
        if executable is None:
            raise unittest.SkipTest(f"{shell} is not installed")
        return subprocess.run(
            [executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

    def test_restore_flag_restores_independent_snapshot_models(self):
        for shell in ("bash", "zsh", "fish"):
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
                self.assertEqual(
                    settings["env"]["ANTHROPIC_CUSTOM_MODEL_OPTION"],
                    "snapshot-model",
                )
                self.assertEqual(settings["permissions"], {"allow": ["Read"]})

    def test_direct_model_is_validated_and_canonicalized(self):
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default GLM-5.2")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                settings = self.read_settings()
                self.assertEqual(settings["model"], "glm-5.2")
                env = settings["env"]
                self.assertEqual(env["ANTHROPIC_MODEL"], "glm-5.2")
                self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "claude-opus-4-6")
                self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5")
                self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "qwen3.8-max")
                self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], "deepseek-v4-pro")
                self.assertEqual(env["ANTHROPIC_SMALL_FAST_MODEL"], "qwen3.7-max")
                self.assertEqual(env["CLAUDE_CODE_SUBAGENT_MODEL"], "qwen3.7-max")

    def test_no_argument_without_tty_restores_default_and_configures_slots(self):
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                env = self.read_settings()["env"]
                self.assertEqual(env["ANTHROPIC_MODEL"], "qwen3.7-max")
                self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "claude-opus-4-6")
                self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5")
                self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "qwen3.8-max")
                self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], "deepseek-v4-pro")

    def test_default_exports_custom_model_option_to_current_shell(self):
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(
                    shell,
                    'ccswitch default >/dev/null; printf "%s|%s" '
                    '"$ANTHROPIC_CUSTOM_MODEL_OPTION" '
                    '"$ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"',
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "deepseek-v4-pro|DeepSeek V4Pro")

    def test_restore_does_not_export_unrecognized_environment_records(self):
        with open(self.defaults_path, encoding="utf-8") as defaults_file:
            defaults = json.load(defaults_file)
        defaults["ANTHROPIC_AUTH_TOKEN"] = "token\nPATH=/tmp/injected"
        self.write_json(self.defaults_path, defaults)

        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(
                    shell,
                    'ccswitch default --restore >/dev/null; printf "%s" "$PATH"',
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotEqual(result.stdout, "/tmp/injected")

    def test_direct_model_rejects_allowed_key_injection(self):
        injected = "safe-model\nANTHROPIC_AUTH_TOKEN=injected-token"
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(
                    shell,
                    'ccswitch default "$INJECTED_MODEL"',
                    {"INJECTED_MODEL": injected},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("非法模型 ID", result.stdout + result.stderr)
                self.assertEqual(self.read_settings(), self.initial_settings)

    def test_restore_rejects_newline_in_exported_values(self):
        with open(self.defaults_path, encoding="utf-8") as defaults_file:
            defaults = json.load(defaults_file)
        defaults["ANTHROPIC_AUTH_TOKEN"] = (
            "token\nANTHROPIC_BASE_URL=http://injected.example"
        )
        self.write_json(self.defaults_path, defaults)

        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                self.write_json(self.settings_path, self.initial_settings)
                result = self.run_shell(shell, "ccswitch default --restore")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.read_settings(), self.initial_settings)


if __name__ == "__main__":
    unittest.main()
