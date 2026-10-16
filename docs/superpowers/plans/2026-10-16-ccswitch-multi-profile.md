# ccswitch Multi Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在本机交付可用的命名 Claude API 配置切换与槽位编辑，迁移已有配置并保留其他 Claude 设置。

**Architecture:** Python 标准库实现配置库与受管字段应用，独立 CLI 模块负责交互。现有后端保留模型目录能力并分发命令，薄 shell 包装层通过私有输出文件同步环境变量。安装器支持本地源码安装，共享后端供 bash、zsh、fish 和独立命令使用。

**Tech Stack:** Python 3.8+ standard library, bash/zsh, fish, unittest, local mock HTTP gateway.

**Spec:** `docs/superpowers/specs/2026-10-15-ccswitch-multi-profile-product-design.md`；首版范围见 `docs/superpowers/specs/2026-10-16-ccswitch-mvp-cases.md`。

## Global Constraints

- 日常主流程只有 `use` 和 `slots`；每套连接维护一份组合，不开放 `--preset`。
- 新版为 0.6.0；只支持静态 API Key 和 Bearer Token，不转换其他认证来源。
- 名称为 1～48 位小写字母、数字、短横线、下划线，以字母或数字开头；名称不得与命令关键字冲突，default 允许作为迁移配置名称。
- 不保留 codex 专用命令、模板或自动检测；普通 current 导入不依赖它。
- `CLAUDE_CONFIG_DIR` 决定目标 Claude 目录；配置库为 `$XDG_CONFIG_HOME/ccswitch` 或 `~/.config/ccswitch`。
- 配置库目录权限为 `0700`，包含认证信息的文件为 `0600`；普通输出和 JSON 查询结果均对密钥脱敏。
- current/default 分别导入、原值保留、重名不覆盖、幂等执行；迁移不改源文件，不自动应用模板。
- 保存只更新配置库，保存并应用才写目标；应用仅处理已知连接及模型字段，保留其余设置。
- 认证互换显式清空旧值；不以删除旧字段完成热切换。动态生效有延迟，固定主模型需 `/model` 重选。
- 不发起真实模型推理、不自动升级 Claude、不改远端机器；用户授权本机安装和迁移。
- 功能与失败路径以真实临时文件/CLI/subprocess 测试；先观察 RED 再实现 GREEN。
- 三项开发任务顺序执行，每项独立审查。分支 `feat/ccswitch-profiles`，保留原有未跟踪调研文件；不推送远端。

## Shared Interfaces and Data

`ccswitch/lib/ccswitch_profiles.py` 提供：

```python
MANAGED_ENV_KEYS: tuple
MODEL_ENV_KEYS: tuple
TOP_LEVEL_KEYS = ('model', 'modelPicker')

class ProfileStore:
    def __init__(self, config_dir=None, root=None): ...
    # .settings_path / .defaults_path / .root are pathlib.Path
    def get(self, name): ...                 # full private profile dict
    def list_profiles(self): ...            # list of full private profile dicts
    def save(self, name, settings, replace=False, auth=None,
             catalog='manual', source='manual'): ...
    def migrate(self): ...                  # {created: [], conflicts: [], warnings: []}
    def apply(self, name, settings_override=None): ... # {env: {}, profile: name, ...}
    def undo(self): ...                     # same result shape as apply
    def status(self): ...                   # target, profile, file_matches,
                                            # saved_matches, shell_conflicts, ...
    def remove(self, name): ...

def extract_settings(settings, auth=None): ... # preserve only managed fields
def redact(value): ...                        # recursive safe public representation
```

Profile shape:

```json
{"schema_version":1,"name":"work","revision":1,"auth_type":"bearer_token","catalog":"manual","source":"manual","settings":{"env":{"ANTHROPIC_BASE_URL":"http://gateway.example/anthropic","ANTHROPIC_AUTH_TOKEN":"example-only","ANTHROPIC_MODEL":"sonnet","ANTHROPIC_DEFAULT_SONNET_MODEL":"model-a"},"model":"sonnet"}}
```

Schema 不重写导入的模型 ID，不给旧值自动加/删 `[1m]`。缺失静态认证可保存为需补充配置，但 use 拒绝。两个有效认证同时存在时要求 `auth='api_key'` 或 `auth='bearer_token'`；不猜测。

受管字段包含原 MODEL_KEYS/CUSTOM_OPTION_KEYS、`ANTHROPIC_DEFAULT_MODEL`、各受支持档位 Opus/Sonnet/Haiku/Fable 的模型/名称/说明/能力字段、Custom 能力字段、`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`。`modelPicker` 整体保留高级字段，但校验 options 的类型和模型值。其他任意 ANTHROPIC_* 不自动成为受管字段。冲突来源检查包括 apiKeyHelper、Bedrock/Vertex/Foundry 开关、OAuth；不删除凭据文件或运行脚本。

应用返回的 `env` 是完整受管环境变量字典：目标缺失的值显式为空，避免热加载和旧 shell 残留。backup 保留原始缺失状态；undo 在恢复未设置语义时也显式清空旧环境值，优先保证热更新的认证正确性，不承诺字节级恢复。顶层字段缺失则移除本工具管理的旧字段。

CLI `main(argv=None)` 放在 `ccswitch/lib/ccswitch_cli.py`，由后端 `main()` 调用。所有用户命令支持传入隐藏的 `--shell-output <file>`；只在确实应用成功时写入完整 `NAME=value` 行，不向 stdout 打印凭据。该文件由包装层 mktemp 创建，仅允许无控制字符的值，包装层逐行按白名单 export，禁止 eval。

### Task 1: 配置库、迁移、应用与撤销

**Files:** Create `ccswitch/lib/ccswitch_profiles.py`, `ccswitch/tests/test_profiles.py`.

**Consumes:** 上述固定字典结构与接口。
**Produces:** `ProfileStore`, `extract_settings`, `redact`, 两份字段清单。

- [x] RED：先写并运行文件行为测试。至少覆盖 API Key 往返、current/default 幂等迁移、源文件不变、hooks 保留、非法 JSON/名称不写入、认证冲突、shell 冲突、备份与 undo、手动改受管字段后拒绝撤销、权限。

```python
store.save('work', {'env': {'ANTHROPIC_BASE_URL': 'http://a.example',
                          'ANTHROPIC_API_KEY': 'test-key', 'ANTHROPIC_MODEL': 'sonnet'}})
store.apply('work')
written = json.loads(store.settings_path.read_text())
self.assertEqual(written['env']['ANTHROPIC_API_KEY'], 'test-key')
self.assertEqual(written['env']['ANTHROPIC_AUTH_TOKEN'], '')
self.assertEqual(written['hooks'], {'SessionStart': []})
```

Run: `python3 -B -m unittest discover -s ccswitch/tests -p test_profiles.py -v`。最初因尚无模块或接口失败，记录证据。

- [x] GREEN：实现投影字段、校验与私有原子写入。根目录文件锁协调本工具；受管字段摘要区分源文件偏差和保存修订偏差。目标不存在可以创建，JSON 损坏绝不重置；替换前检查外部文件变化。
- [x] 实现 migrate（每个来源独立处理）与 apply；在更改前保存每目标最近十条恢复记录。state 更新失败报告部分完成，不声称完整成功。
- [x] 实现 undo，仅在实际受管字段仍匹配上次 applied 摘要时恢复；保留之后新增的非受管字段。删除被任何目标当前引用的配置失败。
- [x] 跑聚焦测试并自审，再提交此任务涉及文件；报告 RED/GREEN 输出、commit、接口差异。既有测试基线问题不属于本任务，不改变旧模块。

### Task 2: CLI、槽位向导与旧入口兼容

**Files:** Create `ccswitch/lib/ccswitch_cli.py`, `ccswitch/lib/ccswitch_slots.py`, `ccswitch/lib/ccswitch_ui.py`, `ccswitch/tests/test_profile_cli.py`; Modify `ccswitch/lib/ccswitch_backend.py`, `ccswitch/tests/test_models.py`, `ccswitch/VERSION`.

**Consumes:** Task 1 的确切 Store API 与字段清单。
**Produces:** 可直接运行的 Python 后端，所有用户命令、交互和机器输出协议。CLI 负责命令编排，slots 模块负责共享草稿变更和槽位向导，ui 模块负责终端输入/选择；避免一个模块塞入全部流程。

- [x] RED：通过真实 CLI subprocess 写测试：import/use/list --json 脱敏；save 与 use 分开；slots set/apply；取消不写入；不完整认证拒绝应用；不存在 settings 可 add/import/use；移除 codex 入口；default/single 兼容；非交互无名称不挂起。

```python
result = self.cli('use', 'work', '--shell-output', str(self.output_file))
self.assertEqual(result.returncode, 0, result.stderr)
self.assertNotIn('test-token', result.stdout + result.stderr)
self.assertIn('ANTHROPIC_AUTH_TOKEN=test-token', self.output_file.read_text())
```

Run: `python3 -B -m unittest discover -s ccswitch/tests -p test_profile_cli.py -v`。先观察缺少命令的失败。

- [x] GREEN：argparse 命令覆盖 status/list/use/add/save/import/edit/remove/undo/doctor/slots/init/default/single/models/version/help/migrate。migrate 只导入缺失项，不应用到 Claude。`--json` 公共结果脱敏；解析错误不泄露用户输入密钥。profile 名和值校验委托 Store，不重复模型目录限制。
- [x] 导入/保存：from 文件支持完整 settings、本产品 profile、旧扁平快照；认证显式选择；保存重名需 --replace。第一次写操作之前 migrate；只读操作只预览。`init` 首次保存 default，存在需 --replace；保留同名 legacy snapshot 的防覆盖语义。
- [x] `use` 名称可省略但要求真实终端，选择后展示脱敏摘要和全局目标路径。所有交互 stdin/stdout 必须 TTY；非交互缺参数明确报错。应用后输出文件已更新和 `/model` 说明，不宣称所有会话已切换。
- [x] `slots` 编辑已识别当前项；`slots <name>` 查看；`slots edit <name>` 编辑。提供 Opus/Sonnet/Haiku、启动模型（别名/固定）、子代理默认、菜单添加/改名/排序/删除、统一填充、预览、保存/保存并应用/取消。菜单默认追加内置项。
- [x] 提供可脚本验证的 `slots set <name> <opus|sonnet|haiku|startup|subagent> <model> [--apply]`；`slots menu add/remove/move <name>` 使用明确参数；这些是交互同一份草稿变更函数的消费入口，不能各写一套逻辑。
- [x] `default [model]` 保留原固定槽位默认应用；`default --restore` 应用迁移的 default 原值；`single <model>` 统一受管模型槽位，临时覆盖不改保存配置。认证完整复用 Store。原模型目录辅助函数仍供旧模型校验使用，新自定义 profile 不依赖 CloudCLI 目录。
- [x] 从后端移除 Codex 专用常量、实现和自动读取；原旧测试中相应功能断言替换为入口拒绝/当前配置通用导入断言。修复已知 init 测试缺 Base URL 的夹具，版本断言更新 0.6.0；新行为必须有先失败证据。
- [x] 跑本任务测试及 `test_profiles.py`、`test_models.py`，自审并提交本任务文件。shell 旧测试在 Task 3 统一适配，报告具体未接入点。

### Task 3: Shell、安装器、文档与本机交付准备

**Files:** Modify `ccswitch/bash/ccswitch.bash`, `ccswitch/fish/ccswitch.fish`, `ccswitch/install.sh`, `ccswitch/README.md`, `ccswitch/tests/test_shell_wrappers.py`; Create `ccswitch/bin/ccswitch`, `ccswitch/tests/test_install.py`.

**Consumes:** Task 2 用户命令、`--shell-output` 协议、0.6.0 后端。
**Produces:** 可本地安装的三个 shell 包装层与独立命令；准确使用文档。

- [x] RED：真实 bash/fish（可用时 zsh）子进程运行 use/slots set --apply/undo，验证当前 shell 变量和磁盘一致，空认证不残留，带空格/等号/美元/引号的值不执行。取消/失败时不导出环境；非交互不挂起。

```python
result = self.run_shell('bash', 'ccswitch use personal; '
    'test "$ANTHROPIC_AUTH_TOKEN" = "personal-token" && '
    'test -z "$ANTHROPIC_API_KEY"')
self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

- [x] GREEN：包装层只运行后端和读取私有结果文件（白名单、无 eval、保留退出码、删除临时文件）。CLI 交互直接连接 TTY，不能用 command substitution 包住整段交互。保留 update/version 入口；update 在下载执行安装器前比较版本，远端低于本地 0.6.0 时拒绝降级，保留当前版本；移除 codex 命令和 rc 读写逻辑。
- [x] 安装器新增 `--local`，从当前脚本目录复制程序而不联网。统一后端安装到 `~/.local/share/ccswitch`，鱼壳自动加载文件到 fish functions；bash/zsh rc 只追加一次 source。安装 `~/.local/bin/ccswitch` 供无函数环境使用，提示父 shell 不能通过独立进程更新。--update 不改配置库/settings；取消旧 --url/--key 凭据安装方式并给通用录入指引。
- [x] RED/GREEN 安装测试：临时用户目录 `install.sh --local --shell bash/fish` 后可使用全部模块，第二次安装不重复 rc；安装前后 settings 和旧快照字节不变；覆盖 --update。本机真实安装由控制器在全项审查后执行，任务实现者不改真实用户配置。
- [x] README 用两个入口和迁移说明替代旧 codex 示例，说明全局范围、远端需远端执行、菜单与槽位、热更新延迟、固定模型 `/model`、本地保存密钥、undo 语义。保留 install/update/models 的使用说明，不承诺真实模型均可调用。
- [x] 跑 `python3 -B -m unittest discover -s ccswitch/tests -v` 及 shell 语法检查，自审并提交本任务文件，报告缺失 shell 的覆盖限制。

## Controller delivery checklist

- [x] 完成逐任务及全分支代码审查，处理重要问题。
- [x] 备份本机现有安装文件、对应 rc、真实 settings 和旧快照到权限 0700 的本机恢复目录，记录 SHA256；不把密钥或完整配置放进仓库。
- [x] 从本地源码安装 bash 和当前已有 fish 两套入口，命令均显示 0.6.0。
- [x] 显式执行 migrate（通过提供专用 migrate 命令或 first-write 的安全 save），生成本机 current/default；验证保存值和源字段相符且源文件 SHA256 未变化，不自动选择新的网关。
- [x] 通过临时 `CLAUDE_CONFIG_DIR` 和临时 `XDG_CONFIG_HOME` 实测已安装命令的 import/use/slots/undo，使用假凭据。若进行实际 CLI 热加载验证，沿用研究脚本的模拟 HTTP 网关，不调用真实模型。
- [x] 在真实目录只读运行 list/status/doctor，报告已导入名称、真实目标、保留的固定启动选择和需要 `/model` 的情况；不显示凭据。
- [x] 将实施结果与未覆盖限制写入计划末尾；最终给用户可立即执行的两条命令和当前安装情况。

## 实施结果（2026-10-16）

已在本机安装 0.6.0 的 bash、fish 和独立命令。zsh 包装层也已用真实 zsh 验证。当前 settings 与旧快照分别导入 current/default，未自动应用，源文件 SHA256 与安装前一致。

最终 92 项测试通过，无跳过；三个 shell 语法检查通过。真实 Claude 2.1.296 配合本地模拟网关完成 7 项已安装版本验收，包括认证切换、槽位热加载、固定模型边界和撤销。逐任务审查及最终修复复核完成，无遗留重要问题。

功能代码保留在 feat/ccswitch-profiles；原有未跟踪调研材料保留。当前固定启动模型原值保留；运行中固定模型仍需 /model 重选。模拟结果不代表真实网关的模型权限或可用性。详见[本机验收记录](../verification/2026-10-16-ccswitch-local.md)。
