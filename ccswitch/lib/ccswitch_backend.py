#!/usr/bin/env python3
"""Backend for the ccswitch shell function.

Model catalog compatibility utilities and executable entry point.
Profile orchestration lives in ccswitch_cli; secrets are read from files
or terminal input, and shell synchronization uses a private output file.
"""
import json
import copy
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse

HOME = os.path.expanduser("~")
SETTINGS_PATH = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.join(HOME, ".claude")), "settings.json")
DEFAULTS_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), "ccswitch-defaults.json")
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
# Deliberately updated local snapshot; daily commands never refresh it.
STATIC_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "cloudcli-models.json")
with open(STATIC_CATALOG_PATH, encoding="utf-8") as catalog_file:
    STATIC_MODEL_CATALOG = json.load(catalog_file)
FALLBACK_MODELS = STATIC_MODEL_CATALOG["models"]
STATIC_CATALOG_UPDATED_AT = STATIC_MODEL_CATALOG["updated_at"]
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
    model["id"] for model in FALLBACK_MODELS
    if model.get("claude_code_model") == model["id"] + "[1m]"
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
    return configured if configured and os.path.isfile(configured) else ""


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
        "name": name if isinstance(name, str) and name else model_id.strip(),
        "type": "internal" if entry.get("internal") is True else "external",
        "protocols": protocols,
    }


def _cloudcli_bearer(settings):
    """Only send a credential paired with CloudCLI's managed endpoint."""
    if not isinstance(settings, dict) or not isinstance(settings.get("env"), dict):
        return ""
    env = settings["env"]
    try:
        endpoint = urllib.parse.urlsplit(env.get("ANTHROPIC_BASE_URL", ""))
        trusted = (endpoint.scheme == "https"
                   and endpoint.hostname == "ducky.code.alibaba-inc.com"
                   and endpoint.port in (None, 443)
                   and endpoint.username is None and endpoint.password is None)
    except (ValueError, TypeError, AttributeError):
        return ""
    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    return token if trusted and isinstance(token, str) else ""


def _normalize_catalog(payload):
    if not isinstance(payload, list):
        raise ValueError("Invalid model catalog")
    models, seen = [], set()
    for entry in payload:
        model = _normalize_catalog_entry(entry)
        if model and model["id"] not in seen:
            seen.add(model["id"])
            models.append(model)
    if payload and not models:
        raise ValueError("Invalid model catalog entries")
    return models


def load_model_catalog(settings=None):
    # SDK access is an explicit compatibility opt-in, never auto-discovered.
    sdk_path = _cloudcli_sdk_path()
    if not sdk_path:
        return copy.deepcopy(FALLBACK_MODELS), False
    context = settings
    if context is None:
        try:
            context = load_json(SETTINGS_PATH)
        except (OSError, ValueError):
            context = {}
    token = _cloudcli_bearer(context)
    if settings is not None and not token:
        return copy.deepcopy(FALLBACK_MODELS), False

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in CLOUDCLI_CHILD_ENV_KEYS
    }
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
        return _normalize_catalog(json.loads(result.stdout)), True
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        pass
    return copy.deepcopy(FALLBACK_MODELS), False


def is_claude_compatible(model):
    return "anthropic" in model.get("protocols", [])


def catalog_model_choice(model):
    reference = next((row for row in FALLBACK_MODELS if row["id"] == model["id"]), {})
    configured_id = model.get("claude_code_model", reference.get("claude_code_model", model["id"]))
    tokens = model.get("context_window_tokens", reference.get("context_window_tokens"))
    context = "（1M）" if tokens == 1000000 else ""
    return configured_id, model["name"] + context + " · " + configured_id


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


def cmd_normalize_model():
    print(normalize_model(os.environ.get("MODEL", "")), end="")


def cmd_resolve_model():
    requested = os.environ.get("MODEL", "")
    if not requested:
        raise ValueError("请指定模型 ID；通过 `ccswitch slots` 选择并配置模型")
    models, live = load_model_catalog()
    if not live and os.environ.get("CCSWITCH_CLOUDCLI_MODEL_SDK"):
        print("⚠ CloudCLI 实时目录不可用，当前使用内置兼容清单。", file=sys.stderr)
    selected = validate_model(requested, models, live)
    print(selected, end="")


def cmd_models():
    models, live = load_model_catalog()
    if live:
        print("CloudCLI 实时模型目录：")
    else:
        print(f"CloudCLI 本地模型清单（{STATIC_CATALOG_UPDATED_AT}，{len(models)} 个）：")
        if os.environ.get("CCSWITCH_CLOUDCLI_MODEL_SDK"):
            print("⚠ 无法读取 CloudCLI 实时目录，当前展示本地静态清单。")
    print("")
    print(f"  {'模型 ID':<24} {'来源':<8} 客户端")
    for model in models:
        source = "内部模型" if model["type"] == "internal" else "外部模型"
        clients = "Claude Code / OpenCode" if is_claude_compatible(model) else "仅 OpenCode"
        configured_id, _ = catalog_model_choice(model)
        print(f"  {configured_id:<28} {source:<8} {clients}")
    print("\nClaude Opus/Sonnet 默认使用 [1m] 选择项；其他模型会移除误带的 [1m] 后缀。")


def cmd_version():
    print(read_version())


def main(argv=None):
    # importlib users need the sibling module path too. Do not depend on cwd.
    lib_dir = os.path.dirname(os.path.abspath(__file__))
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from ccswitch_cli import main as cli_main
    return cli_main(argv, backend=sys.modules.get(__name__))


if __name__ == "__main__":
    sys.exit(main())
