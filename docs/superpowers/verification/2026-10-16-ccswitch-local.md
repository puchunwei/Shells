# ccswitch 0.6.0 本机交付验收

日期：2026-10-16。目标：本机 beaver，`/home/admin/sandbox/Shells`。功能代码：`feat/ccswitch-profiles`，最终实现提交 `d01d168`。

## 已交付

按配置兼容与存储、切换命令与槽位编辑、终端与安装三步完成。日常使用：

```bash
ccswitch use
ccswitch slots
```

新开终端后使用新函数。新增连接执行 `ccswitch add work`，依次录入连接、编辑模型组合、选择保存/保存并应用/取消。普通输出精简，`--json` 保留完整脱敏结果。

本机已安装 bash、fish 入口和 `~/.local/bin/ccswitch`，均报告 0.6.0。五个 Python 模块和包装层统一位于 `~/.local/share/ccswitch`；安装文件摘要与已审查源码一致。

## 旧配置验收

- `~/.claude/settings.json` 导入为 `current`，旧 `ccswitch-defaults.json` 导入为 `default`。连接、认证、固定模型、独立槽位均按原值保存；没有自动应用任一配置。
- 两个源文件的 SHA256 在安装、迁移及最终验证后均与备份一致。再次迁移没有新增、冲突或告警。
- 配置库 `~/.config/ccswitch` 及其子目录为 0700，配置文件为 0600。真实目录的 list/status/doctor 已只读执行。
- 安装前备份位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-111602`：10 份已有文件副本及 18 个路径的存在状态/摘要清单；私有备份未放入仓库。

[迁移验收结果](2026-10-16-ccswitch-local/migration.json)。

## 测试与审查

| 验收项 | 结果 |
| --- | --- |
| 完整 unittest：存储、CLI、PTY、shell、安装 | 92 项通过，无跳过 |
| bash、zsh、fish 语法及真实子进程 | 通过 |
| 旧数据、取消不写、认证互换、失败与部分完成、撤销 | 通过 |
| 本地安装、重复安装、更新保留数据、拒绝降级 | 通过 |
| 分任务审查、最终全分支审查、最终修复复核 | 通过，无遗留重要问题 |
| 已安装文件与审查源码摘要一致 | 通过 |

最终审查补齐了新建/编辑的完整草稿流程、保存与应用分阶段结果、精简输出、准确的启动项识别及 zsh 示例引号。

完整回归命令：

```bash
PATH="/tmp/ccswitch-zsh-build.UaSaxW/install/bin:$PATH" python3 -B -m unittest discover -s ccswitch/tests -v
bash -n ccswitch/install.sh ccswitch/bash/ccswitch.bash ccswitch/bin/ccswitch
/tmp/ccswitch-zsh-build.UaSaxW/install/bin/zsh -n ccswitch/bash/ccswitch.bash
fish --no-execute ccswitch/fish/ccswitch.fish
```

本次 zsh 使用临时编译的 5.9.2；未替换系统或用户登录 shell。[完整测试输出](2026-10-16-ccswitch-local/tests.log)。

## 已安装版本与真实 Claude

真实 Claude Code 2.1.296 连接两个本地 HTTP 模拟网关，隔离配置和假凭据，7 项验收通过：基线 Bearer、切换地址/认证/活动别名、编辑槽位后别名跟随、固定模型保持原选择、切回 Bearer 清空 API Key、undo 恢复上一连接、保留其他偏好。[客户端验收结果](2026-10-16-ccswitch-local/runtime.json)。

动态加载由 Claude 原生实现，有延迟。运行中的固定模型需 `/model` 重选。该结果证明本地配置链路正确，不代表真实网关权限或模型可用性。未改动远端配置或 Claude 版本，未发起真实付费推理。

## 实施取舍

1. 使用当前检出目录的独立功能分支，保留未跟踪调研材料；代价是分支隔离不提供文件系统隔离，测试全部使用临时配置目录。
2. undo 对原来缺失的受管环境变量写入空值，防止 Claude 热加载保留旧认证；代价是恢复后的 JSON 可能多出空字段，不保证字节级还原。备份保留原始缺失信息。

本机安装交付完成；功能分支和工作目录保留。

## 首次导入识别修复

用户反馈首次执行 ccswitch 显示 unrecognized。根因是状态仅使用应用记录，迁移保存了 current/default 却没有应用记录；实际 settings 与 current 一致。现已补充只读内容匹配：唯一匹配项可显示为当前配置并直接进入 slots，多项匹配要求明确名称。应用历史保持真实，已有应用记录的偏差检查不变。

新增 5 项回归测试先失败再修复，完整回归 97 项通过；本机 fish 已更新，实际执行 ccswitch 显示 Profile: current，slots 能进入并取消。真实 settings、配置库及应用记录的摘要在操作前后保持一致。[修复后的完整回归](2026-10-16-ccswitch-local/initial-recognition-tests.log)。

## 0.6.1 方向键菜单

根据用户反馈，将配置选择、槽位、已有模型、保存动作和认证方式改为中文菜单，使用方向键、回车与 Esc。无法唯一识别当前配置时，slots 先展示配置选择。已保存模型 ID 原样保留，CloudCLI 目录仅在明确选择后读取；缺少的模型仍可手动录入。

新增 13 项真实 PTY 验证，覆盖无文字操作的选择及应用、只保存、自定义 ID 原值与大小写、Esc/Control-C 取消、输入框 Esc、终端恢复、小终端、编号降级、启动别名和显式目录来源。完整回归 110 项通过，bash/zsh/fish 语法检查通过；独立评审发现的文本输入框 Esc 问题已修复并复审通过。[本次测试输出](2026-10-16-ccswitch-local/menu-tests.log)。

已从本地安装 0.6.1 到 fish；共享后端也供 bash/zsh 包装层使用。实际本机 fish 打开槽位菜单、方向键选择模型并取消，settings、旧默认快照、配置库和应用记录的摘要均保持一致。在隔离 HOME 中，通过已安装 fish 包装层全程方向键保存并应用，验证磁盘和 Shell 环境同步，终端模式恢复正常。未发起真实模型调用。

本次运行时备份与本机菜单验证回执位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-133729-menu`。用户指南同步更新为[方向键操作示例](../../../ccswitch/USER_GUIDE.zh-CN.md)。

## 0.6.2 静态模型清单

读取 CloudCLI 服务源码确认目录地址后，以只读 GET 取得当前账号的 15 个模型，包含原备用清单缺少的 Opus 4.7、4.8、5.5 和 GPT 6 Sol/Luna。接口为这 15 个模型都标注了 Anthropic 协议，GPT 5.6 Sol 的旧协议限制也已更新。该查询未发起模型推理。

按用户最新要求，将本次数据固化到 [cloudcli-models.json](../../../ccswitch/lib/cloudcli-models.json)，记录日期、来源、ID、名称、内外部分类和协议。默认读取本地静态文件，不自动联网刷新或探测云端 SDK；后续重新核对并更新该文件，再运行本地安装同步。原有显式 SDK 配置保留兼容。

新增静态快照、禁止网络与 SDK 调用、返回副本隔离及新 Opus 模型方向键选择验证，完整回归 **114 项通过，无跳过**。bash/zsh/fish 语法与差异检查通过，独立审查通过；安装测试验证 JSON 资产分发完整并保留旧配置。[本次完整测试输出](2026-10-16-ccswitch-local/static-catalog-tests.log)。

已安装 0.6.2 到本机。在实际 fish 中，`models --json` 约 0.08 秒返回本地 15 个模型；实际方向键进入完整目录、选择 Opus 5.5 为草稿，再 Esc 取消。菜单验证前后 settings、配置库与应用记录摘要相同，终端模式恢复；安装后的五个模块和 JSON 数据均与源码一致。回执及安装前程序备份位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-135300-catalog`。

## 0.6.3 Claude 显式 1M 后缀

按用户环境的识别要求，为静态目录的 6 个 Claude 模型统一添加 `claude_code_model: 原始ID[1m]` 与 1M 标记。选择完整目录中的模型会保存带后缀的配置值，原始接口 `id` 保留。旧兼容命令的已知 1M 模型集合也从同份元数据派生；显式 SDK 目录按原始 ID 回用已知元数据。已有配置、导入、手输及未知模型不自动改写。

静态、SDK、六种模型逐一通过方向键选择并保存应用、手输裸 Claude ID 保持原值等回归先失败再修复，完整回归 **118 项通过**，独立复核通过。[完整测试输出](2026-10-16-ccswitch-local/one-million-tests.log)。

实际 Claude Code 2.1.296 使用隔离配置、假认证与本地模拟网关验证：6 种带 `[1m]` 的配置均显示 `contextWindow: 1000000`，发往模拟网关的模型 ID 均已剥离后缀。[客户端验证结果](2026-10-16-ccswitch-local/one-million-runtime.json)。该结果验证客户端识别及请求行为，不代表真实网关的上下文容量。后缀语义参考[官方模型配置文档](https://code.claude.com/docs/en/model-config#extended-context)。

本机已更新为 0.6.3；实际 fish 菜单显示 6 种 1M 选项，选择 Opus 5.5 后草稿显示 `claude-opus-5-5[1m]`。取消前后真实配置和配置库摘要相同，安装文件与源码一致。程序备份与回执位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-140622-one-million`。


## 0.6.4：补齐 Fable 槽位，说明兼容命令

- 官方模型配置文档确认 `fable` 由 `ANTHROPIC_DEFAULT_FABLE_MODEL` 控制：https://code.claude.com/docs/en/model-config 。已有保存、导入和 Shell 白名单早已保留 Fable；本次补齐槽位菜单、CLI setter、状态预览，以及默认启动/子代理的“跟随 Fable”选项。未配置时不自动分配模型。
- 静态清单仍为 15 个已核对的模型，未虚构 Fable 服务可用性。可按网关能力给 Fable 槽位选择已有模型，或手工填写网关提供的 ID。
- 新增 CLI 保存/应用/私有 Shell 输出原值和元数据保留测试、PTY 的 Fable 目录选择测试、默认启动和子代理跟随 Fable 测试；修复前观察到 setter 拒绝 Fable、菜单缺项的失败。修复后完整 **121 项测试通过，无跳过**，见 `fable-tests.log`；bash、zsh、fish 语法检查及 diff 空白检查通过。独立代码审查未发现阻塞问题。
- 本机 Claude Code 2.1.296 连接隔离的本地模拟网关：启动模型 `fable`、Fable 映射 `claude-opus-5-5[1m]`，实际请求模型为 `claude-opus-5-5`，客户端 contextWindow 为 1000000。证据见 `fable-runtime.json`，未调用真实付费网关。
- 已安装到本机 fish，版本 **0.6.4**；原程序备份 `/home/admin/.local/state/ccswitch/install-backups/20261016-141828-fable`。真实 fish + 已安装包装层通过方向键选择 Fable → 静态目录 Opus 5.5[1m] → 草稿显示正确 → Esc 取消；即时前后 settings、旧快照和配置库内容一致，TTY 恢复正常，安装文件与源文件一致。备份目录的 `fable-verification.json` 保存检查结果。
- 按用户的综合审查要求核对 `default` 和 `single`：未改变旧命令语义。文档明确 `use default` 原样恢复保存组合；旧 `default [MODEL]` 会套用内置 Opus/Sonnet/Haiku/自定义项搭配；旧 `single MODEL` 会用 default 连接临时统一全部模型绑定和菜单。后两种不修改保存的 default 组合。日常建议只用 `use` 和 `slots`，“统一所有模型”已在槽位的更多设置中提供。


## 0.6.5：default 仅保留为普通配置项

- 按用户要求删除 `default` 特殊命令及 `DEFAULT_MODEL_SLOTS` 内置模型模板。旧命令的无参数、指定模型、`--restore` 三种形式均在任何迁移/文件写入前返回移除指引：使用 `ccswitch use default` 或 `ccswitch slots edit default`。帮助、说明文档和独立启动器的应用提示列表同步清理。
- 名为 default 的普通配置照常支持保存、导入、查看、槽位编辑和应用。既有模型 ID、Fable 元数据及自定义菜单按保存内容使用；导入与更新程序均不应用配置。旧快照的只读迁移兼容保留，已有同名配置不被覆盖。
- 新增回归覆盖三种旧命令不写任何配置/状态/私有 Shell 输出；default 普通项按原值应用，不注入内置模板；安装后的独立命令仅输出相关指引。观察到修复前失败后再修改代码。旧 default 行为测试改为普通 `use default` 行为，single 兼容命令的独立回归继续通过。
- 完整 **124 项测试通过，无跳过**，见 `remove-default-tests.log`。bash/zsh/fish 语法检查、diff 空白检查通过。独立审查发现的启动器多余提示已修复并增加安装回归。
- 已更新本机 fish 和独立命令为 **0.6.5**。安装前程序备份及配置摘要位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-142502-remove-default`。真实 fish 和独立入口逐一执行三种已移除形式，均返回移除指引；default 仍可作为配置项读取。当前 `settings.json`、旧快照、全部配置库文件和状态文件与安装前摘要一致；启动器、包装层、Python 模块及静态清单均与源码一致。结果记录为备份目录中的 `verification.json`。


## 0.6.6：仅保留当前实际配置，并增加删除菜单

- 用户进一步明确需要一个实际配置项。上一轮仅删除命令、仍保留 current/default 两个保存项，没有满足这一点。复查发现 live settings 已经偏离这两个旧保存值，应用历史仍引用 default，因此没有简单地删除某个文件或应用旧配置。
- 在私有备份 `/home/admin/.local/state/ccswitch/profile-backups/20261016-143205-keep-current` 保存原配置库、状态、真实 settings 和旧快照。将 live settings 的受管部分保存到 current，旧 default profile 和 `ccswitch-defaults.json` 移到该备份目录，移除已归档 default 的过期应用状态引用。真实 settings 字节保持不变。隔离副本验证迁移不会再创建 default；本机检查仅剩 current，且其内容与 live settings 匹配。
- `ccswitch use` 的配置选择菜单新增“删除配置…”；`ccswitch remove` 不带名字时也进入方向键选择。预览后确认，默认取消，Esc 退出。已有 `remove NAME` 仍支持脚本直接删除。删除仅移除保存项，不应用配置、不触发自动迁移；后者修复了删除时又导入历史配置的问题。仍保护应用记录引用的配置，提示先切换再删除。
- 新增 4 项真实 PTY 测试：主菜单选择删除、独立删除确认、默认取消、Esc 取消；新增 CLI 测试验证删除不会导入旧配置或修改当前 settings。先观察到菜单缺失和旧安装的迁移副作用失败，再完成修复。完整 **129 项测试通过，无跳过**，见 `delete-menu-tests.log`。bash/zsh/fish 语法和 diff 空白检查通过；独立评审未发现阻塞问题。
- 本机已安装 **0.6.6**。实际 fish 验证：`slots` 直接打开 current；`use` 可进入删除选择和确认；独立 `remove` 可进入相同确认。两条路径默认取消后当前 settings、全部 profile 和状态文件摘要一致，TTY 正常恢复，安装文件与源码一致。安装前程序和检查回执位于 `/home/admin/.local/state/ccswitch/install-backups/20261016-143610-delete-menu`。本机删除验证使用取消，未删除剩余的 current。
