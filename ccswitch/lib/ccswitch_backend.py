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
import select
import subprocess
import sys
import termios
import tty
import unicodedata

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
CLOUDCLI_MODEL_SDK_PATHS = [
    "/opt/cloudcli/app/server/services/anthropic-quota-models.js",
]
CLOUDCLI_MODEL_SCRIPT = """
import { pathToFileURL } from 'node:url';
const sdk = await import(pathToFileURL(process.argv[1]).href);
const models = await sdk.fetchAnthropicQuotaModels({ force: true });
process.stdout.write(JSON.stringify(models));
"""
MODEL_ALIASES = {
    "claude-opus-4.6": "claude-opus-4-6",
    "glm-5.2": "glm-5.2",
}
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CLOUDCLI_CHILD_ENV_KEYS = {
    "HOME",
    "USER",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "XDG_CONFIG_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
}


class SelectionCancelled(Exception):
    pass


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
    if not isinstance(model_id, str) or not MODEL_ID_PATTERN.fullmatch(model_id.strip()):
        return None
    if not isinstance(protocols, list) or not protocols:
        return None
    protocols = [item.strip() for item in protocols if isinstance(item, str) and item.strip()]
    if not protocols:
        return None
    if isinstance(name, str):
        name = ANSI_ESCAPE_PATTERN.sub("", name)
        name = "".join(" " if unicodedata.category(char).startswith("C") else char for char in name)
        name = re.sub(r"\s+", " ", name).strip()[:128]
    return {
        "id": model_id.strip(),
        "name": name if name else model_id.strip(),
        "type": "internal" if entry.get("internal") is True else "external",
        "protocols": protocols,
    }


def load_model_catalog():
    sdk_path = _cloudcli_sdk_path()
    if not sdk_path:
        return [dict(model) for model in FALLBACK_MODELS], False

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in CLOUDCLI_CHILD_ENV_KEYS
    }
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


def canonicalize_model(model):
    normalized = normalize_model(model)
    return MODEL_ALIASES.get(normalized.lower(), normalized)


def validate_model_id(model):
    if not isinstance(model, str):
        raise ValueError("非法模型 ID：模型 ID 必须是字符串")
    canonical = canonicalize_model(model)
    if canonical and not MODEL_ID_PATTERN.fullmatch(canonical):
        raise ValueError("非法模型 ID：只允许字母、数字以及 . _ : + / @ -")
    return canonical


def validate_export_value(name, value):
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串")
    if any(char in value for char in "\r\n\0"):
        raise ValueError(f"{name} 包含不允许的换行或 NUL 字符")
    return value


def validate_model(model, models, live):
    canonical = validate_model_id(model)
    selected = next(
        (item for item in models if item["id"].lower() == canonical.lower()),
        None,
    )
    if selected:
        if not is_claude_compatible(selected):
            raise ValueError(f"模型 {selected['id']} 仅 OpenCode 可用，不能用于 Claude Code")
        return selected["id"]
    if live:
        raise ValueError(f"模型 {canonical} 不在当前实时目录中；请运行 `ccswitch models` 查看可用模型")
    return canonical


def _render_model_menu(
    models,
    selected_index,
    current_model_id,
    output,
    message="",
    redraw=False,
):
    line_count = len(models) + 3
    if redraw:
        output.write(f"\033[{line_count}A")
    lines = ["请选择默认网关模型："]
    for index, model in enumerate(models):
        pointer = "❯" if index == selected_index else " "
        current = " ● 当前" if model["id"].lower() == current_model_id.lower() else ""
        compatibility = "Claude Code" if is_claude_compatible(model) else "仅 OpenCode"
        lines.append(
            f" {pointer} {index + 1}. {model['name']} ({model['id']}) [{compatibility}]{current}"
        )
    lines.append(" ↑/↓ 选择  Enter 确认  数字直选  q 退出")
    lines.append(message)
    for line in lines:
        output.write(f"\r\033[2K{line}\n")
    output.flush()


def choose_model(models, current, read_key, output):
    compatible_indices = [
        index for index, model in enumerate(models) if is_claude_compatible(model)
    ]
    if not compatible_indices:
        raise ValueError("当前模型目录中没有 Claude Code 兼容模型")

    canonical_current = canonicalize_model(current)
    selected_index = next(
        (
            index
            for index in compatible_indices
            if models[index]["id"].lower() == canonical_current.lower()
        ),
        compatible_indices[0],
    )
    message = ""
    redraw = False
    while True:
        _render_model_menu(
            models,
            selected_index,
            canonical_current,
            output,
            message,
            redraw,
        )
        redraw = True
        message = ""
        key = read_key()
        if key in ("cancel", "q"):
            return None
        if key in ("up", "down"):
            position = compatible_indices.index(selected_index)
            step = -1 if key == "up" else 1
            selected_index = compatible_indices[(position + step) % len(compatible_indices)]
            continue
        if key == "enter":
            return models[selected_index]["id"]
        if len(key) == 1 and key.isdigit() and key != "0":
            index = int(key) - 1
            if index >= len(models):
                message = "无效序号"
                continue
            model = models[index]
            if not is_claude_compatible(model):
                message = f"{model['id']} 仅 OpenCode 可用，不能用于 Claude Code"
                continue
            return model["id"]


def _read_tty_key(stream):
    fd = stream.fileno()
    char = os.read(fd, 1)
    if char in (b"\r", b"\n"):
        return "enter"
    if char in (b"q", b"Q", b"\x03"):
        return "cancel"
    if char != b"\x1b":
        return char.decode("utf-8", errors="ignore")

    if not select.select([fd], [], [], 0.05)[0]:
        return "cancel"
    if os.read(fd, 1) != b"[" or not select.select([fd], [], [], 0.05)[0]:
        return "cancel"
    return {b"A": "up", b"B": "down"}.get(os.read(fd, 1), "cancel")


def current_model():
    try:
        config = load_json(SETTINGS_PATH)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
    return config.get("env", {}).get("ANTHROPIC_MODEL", config.get("model", ""))


def open_terminal_streams(path):
    terminal_input = open(path, "r", encoding="utf-8", buffering=1)
    try:
        terminal_output = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        terminal_input.close()
        raise
    return terminal_input, terminal_output


def interactive_select_model(models, current):
    terminal_path = os.environ.get("CCSWITCH_TTY_PATH", "/dev/tty")
    try:
        terminal_input, terminal_output = open_terminal_streams(terminal_path)
    except OSError as error:
        raise RuntimeError(
            "当前不是交互式终端；请使用 `ccswitch default <model-id>` 或 `ccswitch default --restore`"
        ) from error

    fd = terminal_input.fileno()
    previous = termios.tcgetattr(fd)
    terminal_output.write("\033[?25l")
    try:
        tty.setraw(fd)
        return choose_model(
            models,
            current,
            lambda: _read_tty_key(terminal_input),
            terminal_output,
        )
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, previous)
        finally:
            try:
                terminal_output.write("\033[?25h\n")
            finally:
                terminal_input.close()
                terminal_output.close()


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
        snapshot[key] = validate_model_id(snapshot[key])
    for key, value in snapshot.items():
        validate_export_value(key, value)
    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=4, ensure_ascii=False)
    for key, value in snapshot.items():
        display = mask(value) if ("KEY" in key or "TOKEN" in key) else (value or "(空)")
        print(f"  {key}: {display}")


def cmd_mo():
    """Point settings.json at the MO/alternate endpoint. Reads MO_BASE_URL, MO_API_KEY, MODEL from env."""
    base_url = os.environ["MO_BASE_URL"]
    api_key = os.environ["MO_API_KEY"]
    model = validate_model_id(os.environ["MODEL"])
    validate_export_value("MO_BASE_URL", base_url)
    validate_export_value("MO_API_KEY", api_key)

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

    restored = {
        "ANTHROPIC_BASE_URL": defaults.get("ANTHROPIC_BASE_URL", ""),
        "ANTHROPIC_AUTH_TOKEN": defaults.get("ANTHROPIC_AUTH_TOKEN", ""),
    }
    for key in MODEL_KEYS:
        source_model = unified_model if unified_model else defaults.get(key, "")
        restored[key] = validate_model_id(source_model)
    for key, value in restored.items():
        validate_export_value(key, value)

    cfg = load_json(SETTINGS_PATH)
    env = cfg.setdefault("env", {})
    env.update(restored)
    env.pop("ANTHROPIC_API_KEY", None)
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


def cmd_resolve_model():
    requested = os.environ.get("MODEL", "")
    models, live = load_model_catalog()
    if not live:
        print("⚠ CloudCLI 实时目录不可用，当前使用内置兼容清单。", file=sys.stderr)
    if requested:
        selected = validate_model(requested, models, live)
    else:
        selected = interactive_select_model(models, current_model())
        if selected is None:
            raise SelectionCancelled("已取消模型选择，配置未修改")
    print(selected, end="")


def cmd_models():
    models, live = load_model_catalog()
    if live:
        print("CloudCLI 实时模型目录：")
    else:
        print("默认网关模型目录（内置回退）：")
        print("⚠ 无法读取 CloudCLI 实时目录，当前展示内置兼容清单。")
    print("")
    print(f"  {'模型 ID':<24} {'来源':<8} 客户端")
    for model in models:
        source = "内部模型" if model["type"] == "internal" else "外部模型"
        clients = "Claude Code / OpenCode" if is_claude_compatible(model) else "仅 OpenCode"
        print(f"  {model['id']:<24} {source:<8} {clients}")
    print("\n不会自动追加 [1m]；会自动移除历史遗留的 [1m] 后缀。")


def cmd_version():
    print(read_version())


COMMANDS = {
    "init": cmd_init,
    "mo": cmd_mo,
    "default": cmd_default,
    "status": cmd_status,
    "normalize-model": cmd_normalize_model,
    "resolve-model": cmd_resolve_model,
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
    except (ValueError, RuntimeError, SelectionCancelled) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"❌ 文件操作失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
