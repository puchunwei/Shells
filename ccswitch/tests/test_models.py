import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


BACKEND_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "lib", "ccswitch_backend.py"
)
SPEC = importlib.util.spec_from_file_location("ccswitch_backend", BACKEND_PATH)
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


LIVE_MODELS = [
    {
        "model_id": "claude-opus-4-6",
        "display_name": "Claude Opus 4.6",
        "internal": False,
        "supported_protoc": ["anthropic"],
    },
    {
        "model_id": "claude-sonnet-5",
        "display_name": "Claude Sonnet 5",
        "internal": False,
        "supported_protoc": ["anthropic"],
    },
    {
        "model_id": "gpt-5.6-sol",
        "display_name": "GPT 5.6 Sol",
        "internal": False,
        "supported_protoc": ["response"],
    },
    {
        "model_id": "qwen3.8-max",
        "display_name": "Qwen 3.8 Max",
        "internal": True,
        "supported_protoc": ["response", "completion", "anthropic"],
    },
    {
        "model_id": "qwen3.7-max",
        "display_name": "Qwen 3.7 Max",
        "internal": True,
        "supported_protoc": ["response", "completion", "anthropic"],
    },
    {
        "model_id": "glm-5.2",
        "display_name": "GLM 5.2",
        "internal": True,
        "supported_protoc": ["response", "completion", "anthropic"],
    },
    {
        "model_id": "deepseek-v4-pro",
        "display_name": "DeepSeek V4Pro",
        "internal": True,
        "supported_protoc": ["response", "completion", "anthropic"],
    },
]


class ModelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sdk_path = os.path.join(self.temp_dir.name, "anthropic-quota-models.mjs")
        with open(self.sdk_path, "w", encoding="utf-8") as sdk_file:
            sdk_file.write("export async function fetchAnthropicQuotaModels() {}\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_node(self, payload, exit_code=0):
        node_path = os.path.join(self.temp_dir.name, "fake-node")
        with open(node_path, "w", encoding="utf-8") as node_file:
            node_file.write("#!/bin/sh\n")
            if payload is not None:
                node_file.write("printf '%s' " + repr(json.dumps(payload)) + "\n")
            node_file.write(f"exit {exit_code}\n")
        os.chmod(node_path, os.stat(node_path).st_mode | stat.S_IXUSR)
        return node_path

    def test_loads_live_catalog_from_cloudcli_sdk(self):
        node_path = self.make_node(LIVE_MODELS)
        with patch.dict(
            os.environ,
            {
                "CCSWITCH_NODE_BIN": node_path,
                "CCSWITCH_CLOUDCLI_MODEL_SDK": self.sdk_path,
            },
            clear=False,
        ):
            models, live = BACKEND.load_model_catalog()

        self.assertTrue(live)
        self.assertEqual([model["id"] for model in models], [
            "claude-opus-4-6",
            "claude-sonnet-5",
            "gpt-5.6-sol",
            "qwen3.8-max",
            "qwen3.7-max",
            "glm-5.2",
            "deepseek-v4-pro",
        ])
        self.assertFalse(BACKEND.is_claude_compatible(models[2]))
        self.assertTrue(BACKEND.is_claude_compatible(models[3]))

    def test_falls_back_when_cloudcli_sdk_fails(self):
        node_path = self.make_node(None, exit_code=1)
        with patch.dict(
            os.environ,
            {
                "CCSWITCH_NODE_BIN": node_path,
                "CCSWITCH_CLOUDCLI_MODEL_SDK": self.sdk_path,
            },
            clear=False,
        ):
            models, live = BACKEND.load_model_catalog()

        self.assertFalse(live)
        self.assertEqual([model["id"] for model in models], [
            "claude-opus-4-6",
            "claude-sonnet-5",
            "gpt-5.6-sol",
            "qwen3.8-max",
            "qwen3.7-max",
            "glm-5.2",
            "deepseek-v4-pro",
        ])


class ModelSelectionTest(unittest.TestCase):
    def setUp(self):
        self.models = [dict(model) for model in BACKEND.FALLBACK_MODELS]

    def test_arrow_navigation_skips_opencode_only_models(self):
        keys = iter(["down", "enter"])
        output = io.StringIO()

        selected = BACKEND.choose_model(
            self.models,
            "claude-sonnet-5",
            keys.__next__,
            output,
        )

        self.assertEqual(selected, "qwen3.8-max")

    def test_number_selects_a_claude_compatible_model(self):
        keys = iter(["6"])
        selected = BACKEND.choose_model(
            self.models,
            "",
            keys.__next__,
            io.StringIO(),
        )
        self.assertEqual(selected, "glm-5.2")

    def test_opencode_only_number_is_rejected_without_exiting(self):
        keys = iter(["3", "4"])
        output = io.StringIO()

        selected = BACKEND.choose_model(
            self.models,
            "",
            keys.__next__,
            output,
        )

        self.assertEqual(selected, "qwen3.8-max")
        self.assertIn("仅 OpenCode", output.getvalue())

    def test_cancel_returns_none(self):
        selected = BACKEND.choose_model(
            self.models,
            "",
            iter(["cancel"]).__next__,
            io.StringIO(),
        )
        self.assertIsNone(selected)

    def test_validates_and_canonicalizes_live_model(self):
        self.assertEqual(
            BACKEND.validate_model("GLM-5.2", self.models, live=True),
            "glm-5.2",
        )
        self.assertEqual(
            BACKEND.validate_model("claude-opus-4.6", self.models, live=True),
            "claude-opus-4-6",
        )

    def test_rejects_opencode_only_model_for_claude(self):
        with self.assertRaisesRegex(ValueError, "仅 OpenCode"):
            BACKEND.validate_model("gpt-5.6-sol", self.models, live=True)

    def test_rejects_unknown_model_when_live_catalog_is_available(self):
        with self.assertRaisesRegex(ValueError, "不在当前实时目录"):
            BACKEND.validate_model("future-model", self.models, live=True)

    def test_allows_unknown_model_when_using_fallback_catalog(self):
        self.assertEqual(
            BACKEND.validate_model("future-model", self.models, live=False),
            "future-model",
        )


class ModelNormalizationTest(unittest.TestCase):
    def test_repository_version_is_available(self):
        self.assertEqual(BACKEND.read_version(), "0.2.1")

    def test_does_not_add_1m_to_claude_models(self):
        self.assertEqual(BACKEND.normalize_model("claude-sonnet-5"), "claude-sonnet-5")
        self.assertEqual(BACKEND.normalize_model("claude-opus-4.6"), "claude-opus-4.6")

    def test_removes_legacy_1m_suffix_from_claude_models(self):
        self.assertEqual(BACKEND.normalize_model("claude-sonnet-5[1m]"), "claude-sonnet-5")
        self.assertEqual(BACKEND.normalize_model("claude-opus-4-6[1M]"), "claude-opus-4-6")

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
        self.assertIn("claude-sonnet-5", text)
        self.assertNotIn("claude-sonnet-5  ->", text)
        self.assertNotIn("claude-opus-4.6  ->", text)
        self.assertIn("不会自动追加 [1m]", text)
        self.assertIn("deepseek-v4-pro", text)

    def test_version_command_prints_local_version(self):
        output = io.StringIO()
        with redirect_stdout(output):
            BACKEND.cmd_version()
        self.assertEqual(output.getvalue().strip(), "0.2.1")


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

    def test_default_restore_removes_legacy_suffixes_from_all_models(self):
        defaults = {
            "ANTHROPIC_BASE_URL": "http://gateway.example/v1/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "token",
        }
        defaults.update({key: "qwen3.7-max[1m]" for key in BACKEND.MODEL_KEYS})
        defaults["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "claude-sonnet-5[1m]"
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
        self.assertEqual(settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5")
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
