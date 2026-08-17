# CC Switch 交互式模型选择设计

## 目标

让 `ccswitch` 使用 CloudCLI 的实时模型目录，并让用户在终端中交互选择默认网关模型，同时保留直接传入模型 ID 的快速用法和 MO 端点切换能力。

## 命令行为

- `ccswitch default`：从实时目录展示交互式模型菜单，选择后切换到默认端点，并将 Claude Code 的全部模型变量统一为所选模型。
- `ccswitch default <model-id>`：不显示菜单，直接切换到指定模型。
- `ccswitch default --restore`：恢复 `ccswitch init` 保存的端点和各模型独立快照。
- `ccswitch models`：展示实时模型目录、模型 ID、来源类型和客户端兼容性。
- `ccswitch mo [model-id]`：保持现有行为，切换到 MO 端点；不传模型时继续使用现有默认值。

非交互环境调用 `ccswitch default` 时不等待输入，而是返回明确错误，提示使用模型 ID 或 `--restore`。

## 模型目录

后端优先通过本机 CloudCLI SDK 的 `fetchAnthropicQuotaModels` 获取当前账号实时目录。目录中的 `protocols` 决定兼容性：

- 包含 `anthropic`：可供 Claude Code 选择。
- 仅包含 `response`：在 `ccswitch models` 和交互菜单中展示，但标记为“仅 OpenCode”，不可选作 Claude Code 模型。

SDK 不存在、请求失败或超时时，回退到内置目录：

- `claude-opus-4-6`
- `claude-sonnet-5`
- `qwen3.8-max`
- `qwen3.7-max`
- `glm-5.2`
- `deepseek-v4-pro`
- `gpt-5.6-sol`（仅 OpenCode）

回退会给出提示，模型切换仍可继续完成。内置 ID 使用实时目录的规范拼写，不再使用旧的 `claude-opus-4.6` 或 `GLM-5.2`。

## 交互体验

交互菜单由 Python 后端统一实现，fish、bash、zsh 共用同一套行为。菜单通过 `/dev/tty` 读取按键，支持：

- 上下方向键移动
- Enter 确认
- `q` 或 Esc 取消
- 数字键快速选择

当前模型会被标记，OpenCode 专用模型显示但不可确认。模型选择结果通过标准输出返回给 shell 包装层，菜单和提示写到控制终端，避免污染包装层解析的数据。

## 配置写入

选择 Claude Code 兼容模型后，继续使用现有原子写入逻辑更新 `~/.claude/settings.json`：

- 恢复默认端点的 URL 和认证信息。
- 将六个 Claude Code 模型环境变量及顶层 `model` 统一设置为所选规范模型 ID。
- 不修改 `permissions`、MCP 或其他无关配置。
- 清理历史 `[1m]` 后缀，但不再自动添加该后缀。

`ccswitch init` 仍只负责保存恢复快照，不承担模型目录缓存。

## 错误处理

- CloudCLI SDK 查询最多等待 10 秒，失败后回退内置目录。
- 用户输入未知模型 ID 时，如果实时目录可用则拒绝并显示可用模型；目录不可用时允许显式模型 ID 原样传给网关，以保留新模型前向兼容性。
- 尝试选择仅 OpenCode 模型时返回错误，并说明应在 OpenCode 中使用。
- 用户取消选择时不改写任何配置。

## 测试

Python 单元测试覆盖：实时目录解析、协议过滤、规范 ID、SDK 失败回退、交互选择、取消、非 TTY、OpenCode 专用模型拒绝，以及 default 选择/restore 两种写入行为。

Shell 层测试覆盖 fish 与 bash/zsh 对后端选择结果的传递。最终在 Devix 容器验证实时目录、交互选择、直接模型参数、旧快照恢复和 Claude Code 新进程读取结果。
