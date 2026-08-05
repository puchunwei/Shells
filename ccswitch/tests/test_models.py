import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout


BACKEND_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "lib", "ccswitch_backend.py"
)
SPEC = importlib.util.spec_from_file_location("ccswitch_backend", BACKEND_PATH)
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


class ModelNormalizationTest(unittest.TestCase):
    def test_adds_1m_only_to_sonnet_and_opus(self):
        self.assertEqual(BACKEND.normalize_model("claude-sonnet-5"), "claude-sonnet-5[1m]")
        self.assertEqual(BACKEND.normalize_model("claude-opus-4.6"), "claude-opus-4.6[1m]")

    def test_preserves_existing_suffix_case_insensitively(self):
        self.assertEqual(BACKEND.normalize_model("claude-sonnet-5[1m]"), "claude-sonnet-5[1m]")
        self.assertEqual(BACKEND.normalize_model("claude-opus-4-6[1M]"), "claude-opus-4-6[1M]")

    def test_other_model_families_are_unchanged(self):
        for model in ["qwen3.6-plus", "qwen3.7-max", "GLM-5.2", "deepseek-v4-pro"]:
            with self.subTest(model=model):
                self.assertEqual(BACKEND.normalize_model(model), model)

    def test_removes_legacy_1m_suffix_from_other_model_families(self):
        self.assertEqual(BACKEND.normalize_model("qwen3.7-max[1m]"), "qwen3.7-max")
        self.assertEqual(BACKEND.normalize_model("GLM-5.2[1M]"), "GLM-5.2")

    def test_models_command_shows_effective_gateway_ids(self):
        output = io.StringIO()
        with redirect_stdout(output):
            BACKEND.cmd_models()
        text = output.getvalue()
        self.assertIn("qwen3.7-max", text)
        self.assertIn("claude-sonnet-5  ->  claude-sonnet-5[1m]", text)
        self.assertIn("deepseek-v4-pro", text)


class ProfileBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_settings_path = BACKEND.SETTINGS_PATH
        self.original_defaults_path = BACKEND.DEFAULTS_PATH
        BACKEND.SETTINGS_PATH = os.path.join(self.temp_dir.name, "settings.json")
        BACKEND.DEFAULTS_PATH = os.path.join(self.temp_dir.name, "defaults.json")
        with open(BACKEND.SETTINGS_PATH, "w", encoding="utf-8") as settings_file:
            json.dump({"permissions": {"allow": ["Read"]}, "env": {}}, settings_file)

    def tearDown(self):
        BACKEND.SETTINGS_PATH = self.original_settings_path
        BACKEND.DEFAULTS_PATH = self.original_defaults_path
        self.temp_dir.cleanup()

    def test_default_restore_migrates_legacy_non_claude_suffixes(self):
        defaults = {
            "ANTHROPIC_BASE_URL": "http://gateway.example/v1/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "token",
        }
        defaults.update({key: "qwen3.7-max[1m]" for key in BACKEND.MODEL_KEYS})
        defaults["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "claude-sonnet-5"
        with open(BACKEND.DEFAULTS_PATH, "w", encoding="utf-8") as defaults_file:
            json.dump(defaults, defaults_file)

        old_unified_model = os.environ.pop("UNIFIED_MODEL", None)
        try:
            with redirect_stdout(io.StringIO()):
                BACKEND.cmd_default()
        finally:
            if old_unified_model is not None:
                os.environ["UNIFIED_MODEL"] = old_unified_model

        with open(BACKEND.SETTINGS_PATH, encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        self.assertEqual(settings["env"]["ANTHROPIC_MODEL"], "qwen3.7-max")
        self.assertEqual(settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5[1m]")
        self.assertEqual(settings["model"], "qwen3.7-max")
        self.assertEqual(settings["permissions"], {"allow": ["Read"]})

    def test_mo_still_switches_endpoint_and_unifies_all_model_keys(self):
        previous = {key: os.environ.get(key) for key in ["MO_BASE_URL", "MO_API_KEY", "MODEL"]}
        os.environ.update({
            "MO_BASE_URL": "http://mo.example/v1/anthropic",
            "MO_API_KEY": "secret",
            "MODEL": "qwen3.7-max",
        })
        try:
            BACKEND.cmd_mo()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        with open(BACKEND.SETTINGS_PATH, encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        env = settings["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://mo.example/v1/anthropic")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "secret")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "")
        self.assertTrue(all(env[key] == "qwen3.7-max" for key in BACKEND.MODEL_KEYS))
        self.assertEqual(settings["model"], "qwen3.7-max")


if __name__ == "__main__":
    unittest.main()
