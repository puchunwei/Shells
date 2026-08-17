# CC Switch Claude Code Model Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ccswitch default` populate Claude Code's native `/model` picker with stable public model slots instead of opening an external terminal picker.

**Architecture:** Keep endpoint and JSON mutation in `ccswitch_backend.py`; shell wrappers only choose command mode and export allowlisted results. Use Claude Code's documented role variables plus one custom option, while keeping the selected current model independent.

**Tech Stack:** Python 3 standard library, fish, bash/zsh, `unittest`.

---

### Task 1: Define public slot behavior in backend tests

**Files:**
- Modify: `ccswitch/tests/test_models.py`

- [ ] **Step 1: Write failing tests for slot mode**

Add tests that call `cmd_default()` with `DEFAULT_SLOT_MODE=1` and assert:

```python
self.assertEqual(env["ANTHROPIC_MODEL"], "glm-5.2")
self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "claude-opus-4-6")
self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5")
self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "qwen3.8-max")
self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], "deepseek-v4-pro")
self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"], "DeepSeek V4Pro")
```

Also assert `--restore` semantics preserve snapshot values and `cmd_mo()` removes all custom-option variables.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest ccswitch.tests.test_models.ProfileBehaviorTest -v
```

Expected: failures because slot constants and mode handling do not exist.

- [ ] **Step 3: Commit test-only RED state only after implementation is ready to follow immediately**

Do not publish a broken branch; continue directly to Task 2.

### Task 2: Implement slot-aware default switching

**Files:**
- Modify: `ccswitch/lib/ccswitch_backend.py`
- Test: `ccswitch/tests/test_models.py`

- [ ] **Step 1: Add explicit public slot constants**

Define:

```python
DEFAULT_MODEL_SLOTS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-6",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.8-max",
    "ANTHROPIC_CUSTOM_MODEL_OPTION": "deepseek-v4-pro",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": "DeepSeek V4Pro",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION": "CloudCLI model",
}
```

- [ ] **Step 2: Apply slots without overwriting the current model**

In `cmd_default()`, use `SELECTED_MODEL` only for `ANTHROPIC_MODEL`. In slot mode, merge `DEFAULT_MODEL_SLOTS`; otherwise restore every snapshotted field exactly. Preserve snapshotted `ANTHROPIC_SMALL_FAST_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL`.

- [ ] **Step 3: Remove default-profile custom options in MO mode**

Delete `ANTHROPIC_CUSTOM_MODEL_OPTION`, `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME`, and `ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION` from `settings.json` during `cmd_mo()`.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python3 -m unittest ccswitch.tests.test_models.ProfileBehaviorTest -v
```

Expected: all profile behavior tests pass.

- [ ] **Step 5: Commit backend behavior**

```bash
git add ccswitch/lib/ccswitch_backend.py ccswitch/tests/test_models.py
git commit -m "feat: configure Claude model slots for default profile"
```

### Task 3: Replace shell picker behavior

**Files:**
- Modify: `ccswitch/fish/ccswitch.fish`
- Modify: `ccswitch/bash/ccswitch.bash`
- Modify: `ccswitch/tests/test_shell_wrappers.py`
- Modify: `ccswitch/lib/ccswitch_backend.py`

- [ ] **Step 1: Write failing shell integration tests**

For bash, zsh, and fish, assert `ccswitch default` succeeds without a TTY and writes the four public slots. Assert `ccswitch default glm-5.2` sets only `ANTHROPIC_MODEL` to GLM while preserving the fixed slots.

- [ ] **Step 2: Run shell tests and verify RED**

```bash
python3 -m unittest ccswitch.tests.test_shell_wrappers.ShellWrapperTest -v
```

Expected: no-argument default fails because it still opens the old picker.

- [ ] **Step 3: Update both wrappers**

No-argument default invokes the backend with `DEFAULT_SLOT_MODE=1` and no selected model. Explicit model first calls `resolve-model`, then passes `SELECTED_MODEL`. `--restore` invokes the backend without slot mode. Add the three Custom option keys to the export allowlist and unset them when switching to MO.

- [ ] **Step 4: Delete unused TTY picker code**

Remove `choose_model`, rendering, `/dev/tty` handling, and related imports/tests. Make `resolve-model` reject an empty `MODEL` instead of opening an external picker.

- [ ] **Step 5: Run shell and full tests**

```bash
python3 -m unittest discover -s ccswitch/tests -v
bash -n ccswitch/bash/ccswitch.bash
zsh -n ccswitch/bash/ccswitch.bash
fish -n ccswitch/fish/ccswitch.fish
```

Expected: all tests and syntax checks pass.

- [ ] **Step 6: Commit wrapper behavior**

```bash
git add ccswitch/lib/ccswitch_backend.py ccswitch/fish/ccswitch.fish ccswitch/bash/ccswitch.bash ccswitch/tests
git commit -m "fix: move default model selection into Claude Code"
```

### Task 4: Document, deploy, and verify

**Files:**
- Modify: `ccswitch/README.md`
- Modify: `README.md`
- Modify: `ccswitch/VERSION`

- [ ] **Step 1: Update Chinese documentation and version**

Set version to `0.4.0`. Document the four fixed slots, dynamic fifth current model, removal of the external picker, and `/model` workflow.

- [ ] **Step 2: Run final local verification**

```bash
python3 -m unittest discover -s ccswitch/tests -v
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 3: Deploy to Devix without changing the current endpoint unexpectedly**

Back up installed CC Switch files, install `0.4.0`, run `ccswitch default glm-5.2`, and start a fresh temporary Claude Code PTY session.

- [ ] **Step 4: Verify `/model` in Claude Code**

Confirm the picker contains `claude-opus-4-6`, `claude-sonnet-5`, `qwen3.8-max`, `deepseek-v4-pro`, and the selected current model `glm-5.2`. Restore the user's pre-test endpoint and model afterward.

- [ ] **Step 5: Commit and push**

```bash
git add README.md ccswitch/README.md ccswitch/VERSION
git commit -m "docs: explain Claude Code model slot switching"
git push origin master
```
