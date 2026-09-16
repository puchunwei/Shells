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
import tempfile
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
CUSTOM_OPTION_KEYS = [
    "ANTHROPIC_CUSTOM_MODEL_OPTION",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
]
SNAPSHOT_KEYS = (
    ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"]
    + MODEL_KEYS
    + CUSTOM_OPTION_KEYS
)
DEFAULT_MODEL_SLOTS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5[1m]",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5[1m]",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.8-max",
    "ANTHROPIC_CUSTOM_MODEL_OPTION": "deepseek-v4-pro",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": "DeepSeek V4Pro",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION": "CloudCLI model",
}
# Codex profile: an Anthropic-compatible gateway (Sub2API) that maps Claude
# model families onto OpenAI/Codex models on the server side. Claude Code must
# therefore keep requesting plain Claude family names so the gateway's
# Opus/Sonnet/Haiku tier mapping can pick the right upstream model.
#
# Never write the [1m] selector here: the upstream is a GPT model, so a 1M
# context marker would stop Claude Code from compacting until it blows up
# upstream. Without the marker Claude Code assumes 200K, a safe bound.
CODEX_DEFAULT_MODEL = "claude-opus-5"
CODEX_MODEL_SLOTS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5",
}
# Deliberately NOT injecting retry/timeout keys here. The Codex gateway pools
# several upstream accounts whose quota windows drift independently, so
# streaming does fail intermittently and client-side retries matter — but those
# keys belong to the base configuration, not to a profile. Injecting them here
# would mean `ccswitch default` has to delete them again, which would silently
# wipe the same keys when the user had set them for their default endpoint.
# Keep CLAUDE_CODE_MAX_RETRIES / CLAUDE_CODE_RETRY_WATCHDOG in settings.json
# once, where they help both profiles.
FALLBACK_MODELS = [
    {
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "type": "external",
        "protocols": ["anthropic"],
    },
    {
        "id": "claude-opus-5",
        "name": "Claude Opus 5",
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
        "id": "qwen3.7-plus",
        "name": "Qwen 3.7 Plus",
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
    {
        "id": "qwen3.8-flash",
        "name": "Qwen 3.8 Flash",
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
CLAUDE_1M_MODEL_IDS = {
    "claude-opus-4-6",
    "claude-opus-5",
    "claude-sonnet-5",
}
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
ONE_M_SUFFIX_PATTERN = re.compile(r"\[1m\]$", flags=re.IGNORECASE)
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


def split_1m_suffix(model):
    model = model.strip()
    has_suffix = bool(ONE_M_SUFFIX_PATTERN.search(model))
    return ONE_M_SUFFIX_PATTERN.sub("", model), has_suffix


def canonical_model_base(model):
    return MODEL_ALIASES.get(model.lower(), model)


def uses_claude_1m_context(model):
    return canonical_model_base(model).lower() in CLAUDE_1M_MODEL_IDS


def normalize_model(model):
    """Normalize the model ID for Claude Code's configured endpoint."""
    model = model.strip()
    if not model:
        return model
    base, _ = split_1m_suffix(model)
    if uses_claude_1m_context(base):
        return f"{base}[1m]"
    return base


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
    base, has_1m_suffix = split_1m_suffix(normalized)
    canonical_base = canonical_model_base(base)
    if has_1m_suffix:
        return f"{canonical_base}[1m]"
    return canonical_base


def validate_model_id(model):
    if not isinstance(model, str):
        raise ValueError("非法模型 ID：模型 ID 必须是字符串")
    canonical = canonicalize_model(model)
    base, _ = split_1m_suffix(canonical)
    if base and not MODEL_ID_PATTERN.fullmatch(base):
        raise ValueError("非法模型 ID：只允许字母、数字以及 . _ : + / @ -")
    return canonical


def validate_plain_model_id(model):
    """Validate a model ID without ever attaching the [1m] selector.

    The Codex gateway resolves Claude family names to OpenAI models upstream,
    so a 1M context marker would be both meaningless and harmful there.
    """
    if not isinstance(model, str):
        raise ValueError("非法模型 ID：模型 ID 必须是字符串")
    base, _ = split_1m_suffix(model.strip())
    base = canonical_model_base(base)
    if base and not MODEL_ID_PATTERN.fullmatch(base):
        raise ValueError("非法模型 ID：只允许字母、数字以及 . _ : + / @ -")
    return base


def validate_export_value(name, value):
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串")
    if any(char in value for char in "\r\n\0"):
        raise ValueError(f"{name} 包含不允许的换行或 NUL 字符")
    return value


def validate_model(model, models, live):
    canonical = validate_model_id(model)
    base, _ = split_1m_suffix(canonical)
    selected = next(
        (item for item in models if item["id"].lower() == base.lower()),
        None,
    )
    if selected:
        if not is_claude_compatible(selected):
            raise ValueError(f"模型 {selected['id']} 仅 OpenCode 可用，不能用于 Claude Code")
        return canonical
    if live:
        raise ValueError(f"模型 {base} 不在当前实时目录中；请运行 `ccswitch models` 查看可用模型")
    return canonical


def read_version():
    for path in (VERSION_PATH, SOURCE_VERSION_PATH):
        try:
            with open(path, "r", encoding="utf-8") as version_file:
                return version_file.read().strip() or "unknown"
        except OSError:
            continue
    return "unknown"


def save_json(path, value):
    directory = os.path.dirname(path) or "."
    prefix = f".{os.path.basename(path)}."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        output = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with output:
            json.dump(value, output, indent=4, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def save_settings(cfg):
    save_json(SETTINGS_PATH, cfg)


def mask(value):
    if not value:
        return "(未设置)"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def cmd_init():
    """Snapshot the current endpoint as the restore point for `ccswitch default`.

    settings.json is the base and exported ANTHROPIC_* variables win over it.
    Reading only the environment used to silently store an all-empty snapshot
    whenever the user had not exported those variables — which is the normal
    case — and that destroyed the very restore point `init` exists to create.
    """
    snapshot = snapshot_from_settings()
    for key in SNAPSHOT_KEYS:
        from_env = os.environ.get(key)
        if from_env:
            snapshot[key] = from_env
    for key in MODEL_KEYS:
        snapshot[key] = validate_model_id(snapshot[key])
    snapshot["ANTHROPIC_CUSTOM_MODEL_OPTION"] = validate_model_id(
        snapshot["ANTHROPIC_CUSTOM_MODEL_OPTION"]
    )
    for key, value in snapshot.items():
        validate_export_value(key, value)
    if not snapshot.get("ANTHROPIC_BASE_URL"):
        # Refuse rather than overwrite a good snapshot with an unusable one.
        raise RuntimeError(
            "无法确定默认端点：settings.json 和环境变量里都没有 ANTHROPIC_BASE_URL；"
            "未改动已有快照"
        )
    save_json(DEFAULTS_PATH, snapshot)
    for key, value in snapshot.items():
        display = mask(value) if ("KEY" in key or "TOKEN" in key) else (value or "(空)")
        print(f"  {key}: {display}")


def snapshot_from_settings():
    """Build a defaults snapshot out of settings.json instead of the shell env.

    `ccswitch init` reads the caller's exported ANTHROPIC_* variables, which
    only works when the user actually exports them. Switching profiles must
    stay reversible even for users who never ran `init`, so derive the restore
    point from the file Claude Code really reads.
    """
    cfg = load_json(SETTINGS_PATH)
    env = cfg.get("env", {})
    snapshot = {key: env.get(key, "") or "" for key in SNAPSHOT_KEYS}
    if not snapshot["ANTHROPIC_MODEL"]:
        # settings.json may configure only the picker slots. Fall back to the
        # strongest configured slot so `ccswitch default` restores a usable
        # active model rather than an empty one.
        for key in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"):
            if snapshot.get(key):
                snapshot["ANTHROPIC_MODEL"] = snapshot[key]
                break
    for key in MODEL_KEYS:
        snapshot[key] = validate_model_id(snapshot[key])
    snapshot["ANTHROPIC_CUSTOM_MODEL_OPTION"] = validate_model_id(
        snapshot["ANTHROPIC_CUSTOM_MODEL_OPTION"]
    )
    for key, value in snapshot.items():
        validate_export_value(key, value)
    return snapshot


def cmd_codex():
    """Point settings.json at the Codex gateway (Anthropic-compatible Sub2API).

    Reads CODEX_BASE_URL, CODEX_API_KEY and an optional MODEL from the
    environment. Keeps the Opus/Sonnet/Haiku slots distinct because the gateway
    maps each family to a different upstream OpenAI model, which is what makes
    the cheap tier cheap. Prints KEY=VALUE lines for the shell wrapper to
    re-export into the current session.
    """
    base_url = os.environ["CODEX_BASE_URL"]
    api_key = os.environ["CODEX_API_KEY"]
    model = validate_plain_model_id(os.environ.get("MODEL", "") or CODEX_DEFAULT_MODEL)
    validate_export_value("CODEX_BASE_URL", base_url)
    validate_export_value("CODEX_API_KEY", api_key)

    if not os.path.exists(DEFAULTS_PATH):
        save_json(DEFAULTS_PATH, snapshot_from_settings())
        print(f"# auto-snapshot {DEFAULTS_PATH}", file=sys.stderr)

    applied = {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": CODEX_MODEL_SLOTS["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
    }
    applied.update(CODEX_MODEL_SLOTS)
    for key, value in applied.items():
        validate_export_value(key, value)

    cfg = load_json(SETTINGS_PATH)
    env = cfg.setdefault("env", {})
    env.update(applied)
    env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_AUTH_TOKEN"] = ""
    for key in CUSTOM_OPTION_KEYS:
        env.pop(key, None)
    cfg["model"] = model
    save_settings(cfg)

    for key, value in applied.items():
        print(f"{key}={value}")


def cmd_default():
    """Restore settings.json from the ccswitch-defaults.json snapshot.

    DEFAULT_SLOT_MODE=1 installs stable public picker slots while SELECTED_MODEL
    controls only the active model by default. UNIFY_SELECTED_MODEL=1 makes
    SELECTED_MODEL fill every Claude Code model slot. Without slot mode, restore
    the snapshot exactly, preserving any opus/haiku/sonnet split the user had.
    Prints KEY=VALUE lines so the calling fish function can re-export them
    into the current shell.
    """
    if not os.path.exists(DEFAULTS_PATH):
        print("defaults snapshot not found; run `ccswitch init` first", file=sys.stderr)
        sys.exit(2)

    defaults = load_json(DEFAULTS_PATH)
    slot_mode = os.environ.get("DEFAULT_SLOT_MODE", "") == "1"
    selected_model = os.environ.get("SELECTED_MODEL", "")
    unify_selected_model = os.environ.get("UNIFY_SELECTED_MODEL", "") == "1"

    restored = {
        "ANTHROPIC_BASE_URL": defaults.get("ANTHROPIC_BASE_URL", ""),
        "ANTHROPIC_AUTH_TOKEN": defaults.get("ANTHROPIC_AUTH_TOKEN", ""),
    }
    if slot_mode:
        current = selected_model or defaults.get("ANTHROPIC_MODEL", "")
        model = validate_model_id(current)
        if selected_model and unify_selected_model:
            for key in MODEL_KEYS:
                restored[key] = model
            restored["ANTHROPIC_CUSTOM_MODEL_OPTION"] = model
            restored["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"] = model
            restored["ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION"] = "Selected model"
        else:
            restored["ANTHROPIC_MODEL"] = model
            for key in ("ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
                restored[key] = validate_model_id(defaults.get(key, ""))
            restored.update(DEFAULT_MODEL_SLOTS)
    else:
        for key in MODEL_KEYS:
            restored[key] = validate_model_id(defaults.get(key, ""))
        for key in CUSTOM_OPTION_KEYS:
            value = defaults.get(key, "")
            if key == "ANTHROPIC_CUSTOM_MODEL_OPTION":
                value = validate_model_id(value)
            restored[key] = value
    for key, value in restored.items():
        validate_export_value(key, value)

    cfg = load_json(SETTINGS_PATH)
    env = cfg.setdefault("env", {})
    env.update(restored)
    env.pop("ANTHROPIC_API_KEY", None)
    cfg["model"] = env["ANTHROPIC_MODEL"]
    save_settings(cfg)

    for key in (
        ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"]
        + MODEL_KEYS
        + CUSTOM_OPTION_KEYS
    ):
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


CODEX_CONFIG_PATH = os.path.join(HOME, ".codex", "config.toml")
CODEX_AUTH_PATH = os.path.join(HOME, ".codex", "auth.json")


def _codex_base_url_from_toml(text, provider):
    """Pull base_url out of [model_providers.<provider>] without tomllib.

    tomllib only exists on Python 3.11+, and ccswitch targets "any python3".
    """
    section = re.compile(r"^\s*\[model_providers\.(?:\"([^\"]+)\"|([^\]\s]+))\]\s*$")
    base_url = re.compile(r"^\s*base_url\s*=\s*[\"']([^\"']+)[\"']\s*$")
    current, fallback = None, ""
    for line in text.splitlines():
        matched_section = section.match(line)
        if matched_section:
            current = matched_section.group(1) or matched_section.group(2)
            continue
        matched_url = base_url.match(line)
        if matched_url and current:
            if provider and current == provider:
                return matched_url.group(1)
            fallback = fallback or matched_url.group(1)
    return fallback


def detect_local_codex():
    """Reuse the Codex CLI's own endpoint and key when they are already set up.

    Codex CLI talks to the same gateway on /v1/responses while Claude Code uses
    /v1/messages, so the base URL carries over verbatim.
    """
    base_url, api_key = "", ""
    try:
        with open(CODEX_CONFIG_PATH, "r", encoding="utf-8") as config_file:
            text = config_file.read()
    except OSError:
        text = ""
    if text:
        provider_match = re.search(
            r"^\s*model_provider\s*=\s*[\"']([^\"']+)[\"']\s*$", text, flags=re.MULTILINE
        )
        provider = provider_match.group(1) if provider_match else ""
        try:
            import tomllib

            parsed = tomllib.loads(text)
            provider = parsed.get("model_provider", provider)
            providers = parsed.get("model_providers", {})
            entry = providers.get(provider) if isinstance(providers, dict) else None
            if isinstance(entry, dict):
                base_url = str(entry.get("base_url", "") or "")
        except Exception:
            base_url = ""
        if not base_url:
            base_url = _codex_base_url_from_toml(text, provider)
    try:
        auth = load_json(CODEX_AUTH_PATH)
        if isinstance(auth, dict):
            api_key = str(auth.get("OPENAI_API_KEY", "") or "")
    except (OSError, json.JSONDecodeError):
        api_key = ""
    base_url = base_url.strip().rstrip("/")
    api_key = api_key.strip()
    for name, value in (("base_url", base_url), ("api_key", api_key)):
        try:
            validate_export_value(name, value)
        except ValueError:
            return "", ""
    return base_url, api_key


def cmd_detect_codex():
    """Print the locally configured Codex endpoint for the shell wrapper.

    Prints nothing when Codex CLI is absent or uses OAuth instead of an API key,
    which lets the wrapper fall through to prompting.
    """
    base_url, api_key = detect_local_codex()
    if base_url:
        print(f"CODEX_DETECTED_BASE_URL={base_url}")
    if api_key:
        print(f"CODEX_DETECTED_API_KEY={api_key}")


def cmd_normalize_model():
    print(normalize_model(os.environ.get("MODEL", "")), end="")


def cmd_resolve_model():
    requested = os.environ.get("MODEL", "")
    if not requested:
        raise ValueError("请指定模型 ID；无参数时直接运行 `ccswitch default`")
    models, live = load_model_catalog()
    if not live:
        print("⚠ CloudCLI 实时目录不可用，当前使用内置兼容清单。", file=sys.stderr)
    selected = validate_model(requested, models, live)
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
    print("\nClaude Opus/Sonnet 默认使用 [1m] 选择项；其他模型会移除误带的 [1m] 后缀。")


def cmd_version():
    print(read_version())


COMMANDS = {
    "init": cmd_init,
    "codex": cmd_codex,
    "default": cmd_default,
    "status": cmd_status,
    "detect-codex": cmd_detect_codex,
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
    except (ValueError, RuntimeError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"❌ 文件操作失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
