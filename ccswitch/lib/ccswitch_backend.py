#!/usr/bin/env python3
"""Backend for the ccswitch shell function.

Reads/writes Claude Code's ~/.claude/settings.json `env` block and the
ccswitch-defaults.json snapshot. Invoked by the ccswitch shell wrapper
(fish/bash/zsh), which passes secrets via environment variables — never
via argv or interpolated source code.
"""
import json
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
SETTINGS_PATH = os.path.join(HOME, ".claude", "settings.json")
DEFAULTS_PATH = os.path.join(HOME, ".claude", "ccswitch-defaults.json")
VERSION_PATH = os.path.join(os.path.dirname(__file__), "VERSION")
SOURCE_VERSION_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")

MODEL_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]
SNAPSHOT_KEYS = ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"] + MODEL_KEYS
FALLBACK_MODELS = [
    {
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "type": "external",
        "protocols": ["anthropic"],
    },
    {
        "id": "claude-sonnet-5",
        "name": "Claude Sonnet 5",
        "type": "external",
        "protocols": ["anthropic"],
    },
    {
        "id": "gpt-5.6-sol",
        "name": "GPT 5.6 Sol",
        "type": "external",
        "protocols": ["response"],
    },
    {
        "id": "qwen3.8-max",
        "name": "Qwen 3.8 Max",
        "type": "internal",
        "protocols": ["response", "completion", "anthropic"],
    },
    {
        "id": "qwen3.7-max",
        "name": "Qwen 3.7 Max",
        "type": "internal",
        "protocols": ["response", "completion", "anthropic"],
    },
    {
        "id": "glm-5.2",
        "name": "GLM 5.2",
        "type": "internal",
        "protocols": ["response", "completion", "anthropic"],
    },
    {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek V4Pro",
        "type": "internal",
        "protocols": ["response", "completion", "anthropic"],
    },
]
SUPPORTED_MODELS = [model["id"] for model in FALLBACK_MODELS]
CLOUDCLI_MODEL_SDK_PATHS = [
    "/opt/cloudcli/app/server/services/anthropic-quota-models.js",
]
CLOUDCLI_MODEL_SCRIPT = """
import { pathToFileURL } from 'node:url';
const sdk = await import(pathToFileURL(process.argv[1]).href);
const models = await sdk.fetchAnthropicQuotaModels({ force: true });
process.stdout.write(JSON.stringify(models));
"""


def normalize_model(model):
    """Return the model ID without the legacy [1m] suffix."""
    model = model.strip()
    if not model:
        return model
    return re.sub(r"\[1m\]$", "", model, flags=re.IGNORECASE)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cloudcli_sdk_path():
    configured = os.environ.get("CCSWITCH_CLOUDCLI_MODEL_SDK", "")
    candidates = [configured] if configured else CLOUDCLI_MODEL_SDK_PATHS
    return next((path for path in candidates if os.path.isfile(path)), "")


def _managed_auth_token():
    for path in (SETTINGS_PATH, DEFAULTS_PATH):
        try:
            config = load_json(path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        env = config.get("env", config)
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        if token:
            return token
    return ""


def _normalize_catalog_entry(entry):
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("model_id", "")
    name = entry.get("display_name", "")
    protocols = entry.get("supported_protoc", [])
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    if not isinstance(protocols, list) or not protocols:
        return None
    protocols = [item.strip() for item in protocols if isinstance(item, str) and item.strip()]
    if not protocols:
        return None
    return {
        "id": model_id.strip(),
        "name": name.strip() if isinstance(name, str) and name.strip() else model_id.strip(),
        "type": "internal" if entry.get("internal") is True else "external",
        "protocols": protocols,
    }


def load_model_catalog():
    sdk_path = _cloudcli_sdk_path()
    if not sdk_path:
        return [dict(model) for model in FALLBACK_MODELS], False

    child_env = os.environ.copy()
    token = _managed_auth_token()
    if token:
        child_env["ANTHROPIC_AUTH_TOKEN"] = token
    node_bin = os.environ.get("CCSWITCH_NODE_BIN", "node")
    try:
        result = subprocess.run(
            [node_bin, "--input-type=module", "-e", CLOUDCLI_MODEL_SCRIPT, sdk_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=child_env,
        )
        payload = json.loads(result.stdout)
        models = [_normalize_catalog_entry(entry) for entry in payload]
        models = [model for model in models if model]
        if models:
            return models, True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        pass
    return [dict(model) for model in FALLBACK_MODELS], False


def is_claude_compatible(model):
    return "anthropic" in model.get("protocols", [])


def read_version():
    for path in (VERSION_PATH, SOURCE_VERSION_PATH):
        try:
            with open(path, "r", encoding="utf-8") as version_file:
                return version_file.read().strip() or "unknown"
        except OSError:
            continue
    return "unknown"


def save_settings(cfg):
    # Write to a temp file then rename, so a crash mid-write can't leave
    # settings.json truncated or corrupted.
    tmp_path = SETTINGS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, SETTINGS_PATH)


def mask(value):
    if not value:
        return "(未设置)"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def cmd_init():
    """Snapshot the caller's current ANTHROPIC_* env vars as the restore point for `ccswitch default`."""
    snapshot = {key: os.environ.get(key, "") for key in SNAPSHOT_KEYS}
    for key in MODEL_KEYS:
        snapshot[key] = normalize_model(snapshot[key])
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=4, ensure_ascii=False)
    for key, value in snapshot.items():
        display = mask(value) if ("KEY" in key or "TOKEN" in key) else (value or "(空)")
        print(f"  {key}: {display}")


def cmd_mo():
    """Point settings.json at the MO/alternate endpoint. Reads MO_BASE_URL, MO_API_KEY, MODEL from env."""
    base_url = os.environ["MO_BASE_URL"]
    api_key = os.environ["MO_API_KEY"]
    model = normalize_model(os.environ["MODEL"])

    cfg = load_json(SETTINGS_PATH)
    env = cfg.setdefault("env", {})
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_AUTH_TOKEN"] = ""
    for key in MODEL_KEYS:
        env[key] = model
    cfg["model"] = model
    save_settings(cfg)


def cmd_default():
    """Restore settings.json from the ccswitch-defaults.json snapshot.

    If UNIFIED_MODEL is set (non-empty), every model variable is set to that
    one value; otherwise each model variable is restored independently from
    the snapshot, preserving any opus/haiku/sonnet split the user had.
    Prints KEY=VALUE lines so the calling fish function can re-export them
    into the current shell.
    """
    if not os.path.exists(DEFAULTS_PATH):
        print("defaults snapshot not found; run `ccswitch init` first", file=sys.stderr)
        sys.exit(2)

    defaults = load_json(DEFAULTS_PATH)
    unified_model = os.environ.get("UNIFIED_MODEL", "")

    cfg = load_json(SETTINGS_PATH)
    env = cfg.setdefault("env", {})
    env["ANTHROPIC_BASE_URL"] = defaults.get("ANTHROPIC_BASE_URL", "")
    env["ANTHROPIC_AUTH_TOKEN"] = defaults.get("ANTHROPIC_AUTH_TOKEN", "")
    env.pop("ANTHROPIC_API_KEY", None)
    for key in MODEL_KEYS:
        env[key] = normalize_model(unified_model if unified_model else defaults.get(key, ""))
    cfg["model"] = env["ANTHROPIC_MODEL"]
    save_settings(cfg)

    for key in ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"] + MODEL_KEYS:
        print(f"{key}={env[key]}")


def cmd_status():
    cfg = load_json(SETTINGS_PATH)
    env = cfg.get("env", {})

    print("   VERSION:    " + read_version())
    print("   BASE_URL:   " + (env.get("ANTHROPIC_BASE_URL") or "(未设置)"))
    print("   API_KEY:    " + mask(env.get("ANTHROPIC_API_KEY", "")))
    print("   AUTH_TOKEN: " + mask(env.get("ANTHROPIC_AUTH_TOKEN", "")))
    print("   MODEL:      " + (env.get("ANTHROPIC_MODEL") or "(未设置)"))

    main_model = env.get("ANTHROPIC_MODEL", "")
    for label, key in [
        ("SMALL_FAST", "ANTHROPIC_SMALL_FAST_MODEL"),
        ("SONNET", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
        ("HAIKU", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    ]:
        value = env.get(key, "")
        if value and value != main_model:
            print(f"   {label + ':':<12}{value}")

    if os.path.exists(DEFAULTS_PATH):
        print(f"   DEFAULTS:   ✓ ({DEFAULTS_PATH})")
    else:
        print("   DEFAULTS:   ✗ (未初始化，请运行 ccswitch init)")


def cmd_normalize_model():
    print(normalize_model(os.environ.get("MODEL", "")), end="")


def cmd_models():
    print("默认网关模型：")
    for model in SUPPORTED_MODELS:
        normalized = normalize_model(model)
        suffix = f"  ->  {normalized}" if normalized != model else ""
        print(f"  {model}{suffix}")
    print("\n不会自动追加 [1m]；会自动移除历史遗留的 [1m] 后缀。")


def cmd_version():
    print(read_version())


COMMANDS = {
    "init": cmd_init,
    "mo": cmd_mo,
    "default": cmd_default,
    "status": cmd_status,
    "normalize-model": cmd_normalize_model,
    "models": cmd_models,
    "version": cmd_version,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: {sys.argv[0]} <{'|'.join(COMMANDS)}>", file=sys.stderr)
        sys.exit(1)

    try:
        COMMANDS[sys.argv[1]]()
    except FileNotFoundError as e:
        print(f"❌ 文件不存在: {e.filename}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败 ({e})", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"❌ 缺少必需的环境变量: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"❌ 文件操作失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
