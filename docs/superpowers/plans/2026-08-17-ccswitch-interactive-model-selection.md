# CC Switch Interactive Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live CloudCLI model catalog and an interactive default-gateway model picker to `ccswitch` while preserving direct model arguments and explicit snapshot restore.

**Architecture:** Keep all catalog discovery, compatibility decisions, terminal interaction, and JSON writes in the Python backend so fish, bash, and zsh share behavior. Shell wrappers only choose between interactive selection, direct selection, and `--restore`, then export the backend result into the current shell.

**Tech Stack:** Python 3 standard library, Node.js dynamic import for the installed CloudCLI SDK, fish, bash/zsh, `unittest`.

---

### Task 1: Live model catalog

**Files:**
- Modify: `ccswitch/lib/ccswitch_backend.py`
- Modify: `ccswitch/tests/test_models.py`

- [ ] **Step 1: Write failing catalog tests**

Add tests using a temporary executable as `CCSWITCH_NODE_BIN` and a temporary SDK path as `CCSWITCH_CLOUDCLI_MODEL_SDK`. The fake executable writes a quota response containing Claude, Qwen, GLM, DeepSeek, and response-only GPT models. Assert that `load_model_catalog()` returns canonical IDs, protocol compatibility, and `live=True`; add a failure case asserting the complete canonical fallback catalog and `live=False`.

```python
models, live = BACKEND.load_model_catalog()
self.assertTrue(live)
self.assertEqual([model["id"] for model in models], [
    "claude-opus-4-6", "claude-sonnet-5", "gpt-5.6-sol",
    "qwen3.8-max", "qwen3.7-max", "glm-5.2", "deepseek-v4-pro",
])
self.assertFalse(BACKEND.is_claude_compatible(models[2]))
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python3 -m unittest ccswitch.tests.test_models -v`

Expected: failures because `load_model_catalog()` and compatibility helpers do not exist.

- [ ] **Step 3: Implement catalog discovery and fallback**

Add canonical fallback dictionaries, a CloudCLI SDK path resolver, a bounded `subprocess.run()` Node invocation, response normalization, and `is_claude_compatible()`. Return `(models, True)` only for a valid non-empty SDK response; otherwise return fallback models and `False`.

```python
FALLBACK_MODELS = [
    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "type": "external", "protocols": ["anthropic"]},
    {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "type": "external", "protocols": ["anthropic"]},
    {"id": "gpt-5.6-sol", "name": "GPT 5.6 Sol", "type": "external", "protocols": ["response"]},
    {"id": "qwen3.8-max", "name": "Qwen 3.8 Max", "type": "internal", "protocols": ["response", "completion", "anthropic"]},
    {"id": "qwen3.7-max", "name": "Qwen 3.7 Max", "type": "internal", "protocols": ["response", "completion", "anthropic"]},
    {"id": "glm-5.2", "name": "GLM 5.2", "type": "internal", "protocols": ["response", "completion", "anthropic"]},
    {"id": "deepseek-v4-pro", "name": "DeepSeek V4Pro", "type": "internal", "protocols": ["response", "completion", "anthropic"]},
]
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python3 -m unittest ccswitch.tests.test_models -v`

Expected: all catalog and existing normalization/profile tests pass.

### Task 2: Model validation and interactive picker

**Files:**
- Modify: `ccswitch/lib/ccswitch_backend.py`
- Modify: `ccswitch/tests/test_models.py`

- [ ] **Step 1: Write failing selection tests**

Add pure selection tests with injected key sequences for down/up, Enter, number selection, cancellation, response-only rejection, explicit live-catalog validation, unknown-model rejection for live catalogs, and unknown-model acceptance during fallback.

```python
selected = BACKEND.choose_model(models, "claude-sonnet-5", iter(["down", "enter"]).__next__, output)
self.assertEqual(selected, "qwen3.8-max")
self.assertIsNone(BACKEND.choose_model(models, "", iter(["cancel"]).__next__, output))
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python3 -m unittest ccswitch.tests.test_models -v`

Expected: failures because selection and validation APIs are missing.

- [ ] **Step 3: Implement selection and validation**

Add `validate_model()`, a pure `choose_model()`, `/dev/tty` raw-key handling, and `cmd_resolve_model()`. Write menu output to the controlling TTY and only the selected model ID to stdout. Return exit code 2 for cancellation/non-TTY and reject response-only models with an OpenCode-specific message.

```python
def cmd_resolve_model():
    requested = normalize_model(os.environ.get("MODEL", ""))
    models, live = load_model_catalog()
    if requested:
        print(validate_model(requested, models, live), end="")
        return
    print(interactive_select_model(models, current_model()), end="")
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python3 -m unittest ccswitch.tests.test_models -v`

Expected: all selection, validation, and previous tests pass.

### Task 3: Shell command semantics

**Files:**
- Modify: `ccswitch/fish/ccswitch.fish`
- Modify: `ccswitch/bash/ccswitch.bash`
- Create: `ccswitch/tests/test_shell_wrappers.py`

- [ ] **Step 1: Write failing shell integration tests**

Create temporary HOME directories with installed-layout copies. Assert that `ccswitch default --restore` restores the snapshot, `ccswitch default <model>` invokes backend resolution and writes the selected model, and no-argument selection propagates cancellation without changing `settings.json`. Skip fish assertions only when fish is unavailable.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python3 -m unittest discover -s ccswitch/tests -v`

Expected: wrapper tests fail because no-argument `default` still restores and `--restore` is treated as a model ID.

- [ ] **Step 3: Update fish and bash/zsh wrappers**

Implement the agreed routing:

```text
ccswitch default            -> backend resolve-model (interactive) -> backend default
ccswitch default MODEL      -> backend resolve-model (validated)   -> backend default
ccswitch default --restore  -> backend default with empty UNIFIED_MODEL
```

Update status/help text and unknown-command lists without changing MO semantics.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python3 -m unittest discover -s ccswitch/tests -v`

Expected: Python and shell wrapper tests all pass.

### Task 4: User-facing catalog and documentation

**Files:**
- Modify: `ccswitch/lib/ccswitch_backend.py`
- Modify: `ccswitch/tests/test_models.py`
- Modify: `ccswitch/README.md`
- Modify: `README.md`
- Modify: `ccswitch/VERSION`

- [ ] **Step 1: Write failing output tests**

Assert that `cmd_models()` displays canonical model IDs, internal/external source, Claude Code/OpenCode compatibility, response-only GPT labeling, and a fallback warning when live discovery fails.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python3 -m unittest ccswitch.tests.test_models -v`

Expected: formatting assertions fail against the old static list.

- [ ] **Step 3: Implement output and documentation**

Render the catalog in aligned Chinese CLI text, update all usage examples for interactive selection and `--restore`, document CloudCLI dependency/fallback behavior, remove obsolete IDs, and bump the version from `0.2.1` to `0.3.0`.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python3 -m unittest discover -s ccswitch/tests -v`

Expected: all tests pass with version `0.3.0`.

### Task 5: Repository and Devix verification

**Files:**
- No new source files

- [ ] **Step 1: Run local static and regression checks**

Run:

```bash
python3 -m unittest discover -s ccswitch/tests -v
bash -n ccswitch/bash/ccswitch.bash ccswitch/install.sh
fish -n ccswitch/fish/ccswitch.fish ccswitch/fish/_ccswitch_normalize_model.fish
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 2: Install the working tree version into Devix**

Copy only `ccswitch.fish`, `_ccswitch_normalize_model.fish`, `ccswitch_backend.py`, and `VERSION` to the corresponding installed fish functions directory in the Devix container, preserving existing MO endpoint configuration and default snapshots.

- [ ] **Step 3: Verify the live catalog and model writes in Devix**

Run non-destructive catalog/status checks, then back up `~/.claude/settings.json`, verify direct switches to `claude-sonnet-5` and `qwen3.8-max`, verify `--restore`, and restore the user's chosen final model. Confirm `gpt-5.6-sol` is visible but rejected for Claude Code.

- [ ] **Step 4: Verify the real interactive menu**

Run `ccswitch default` in a TTY session, select a Claude-compatible model with arrow keys, and confirm a newly launched Claude Code process reads the selected model.

- [ ] **Step 5: Commit and push**

Review the diff, commit implementation and documentation, push `master` to `origin`, and verify local HEAD equals `origin/master`.
