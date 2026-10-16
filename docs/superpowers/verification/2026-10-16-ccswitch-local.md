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
