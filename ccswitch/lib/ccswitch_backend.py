#!/usr/bin/env python3
"""Backend for the ccswitch shell function.

Reads/writes Claude Code's ~/.claude/settings.json `env` block and the
ccswitch-defaults.json snapshot. Invoked by the ccswitch shell wrapper
(fish/bash/zsh), which passes secrets via environment variables — never
via argv or interpolated source code.
"""
import json
import os
import sys

HOME = os.path.expanduser("~")
SETTINGS_PATH = os.path.join(HOME, ".claude", "settings.json")
DEFAULTS_PATH = os.path.join(HOME, ".claude", "ccswitch-defaults.json")

MODEL_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]
SNAPSHOT_KEYS = ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"] + MODEL_KEYS


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=4, ensure_ascii=False)
    for key, value in snapshot.items():
        display = mask(value) if ("KEY" in key or "TOKEN" in key) else (value or "(空)")
        print(f"  {key}: {display}")


def cmd_mo():
    """Point settings.json at the MO/alternate endpoint. Reads MO_BASE_URL, MO_API_KEY, MODEL from env."""
    base_url = os.environ["MO_BASE_URL"]
    api_key = os.environ["MO_API_KEY"]
    model = os.environ["MODEL"]

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
        env[key] = unified_model if unified_model else defaults.get(key, "")
    cfg["model"] = env["ANTHROPIC_MODEL"]
    save_settings(cfg)

    for key in ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"] + MODEL_KEYS:
        print(f"{key}={env[key]}")


def cmd_status():
    cfg = load_json(SETTINGS_PATH)
    env = cfg.get("env", {})

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


COMMANDS = {
    "init": cmd_init,
    "mo": cmd_mo,
    "default": cmd_default,
    "status": cmd_status,
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
