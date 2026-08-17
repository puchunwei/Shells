# CC Switch Claude Code 模型槽位设计

## 目标

切换到 default profile 后，用户在 Claude Code 内执行 `/model`，可以直接选择常用的 CloudCLI 模型。CC Switch 不再在 shell 外部弹出模型选择器。

## 公开槽位映射

只使用 Claude Code 官方公开配置：

| Claude Code 入口 | 配置项 | 模型 |
|---|---|---|
| Opus | `ANTHROPIC_DEFAULT_OPUS_MODEL` | `claude-opus-4-6` |
| Sonnet | `ANTHROPIC_DEFAULT_SONNET_MODEL` | `claude-sonnet-5` |
| Haiku | `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `qwen3.8-max` |
| Custom | `ANTHROPIC_CUSTOM_MODEL_OPTION` | `deepseek-v4-pro` |

Custom 的显示名为 `DeepSeek V4Pro`，描述为 `CloudCLI model`。`ANTHROPIC_MODEL` 是当前模型；当它是 `glm-5.2` 或 `qwen3.7-max` 时，Claude Code 会把它作为动态第五项加入 `/model`。

## 命令行为

- `ccswitch default`：恢复 init 保存的默认端点和当前模型，同时写入上述四个固定槽位。
- `ccswitch default <model>`：校验模型，只更新当前模型，同时保持四个固定槽位。
- `ccswitch default --restore`：精确恢复 init 快照，不注入固定槽位，作为兼容和故障恢复入口。
- `ccswitch mo [model]`：维持现有统一模型行为，并移除 default profile 的 Custom 槽位，避免在 MO 端点误选 CloudCLI 模型。
- `ccswitch models`：继续展示 CloudCLI 实时目录，但不负责交互选择。

## 配置安全

`ccswitch init` 将 Custom 槽位的三个变量一并保存到快照。后端先验证所有模型 ID 和导出值，再原子替换 `settings.json`。Shell 包装器只接受明确允许的导出变量。

## 简化

删除原先的方向键 TTY 选择器及对应终端处理代码。`resolve-model` 只处理显式模型 ID，不再在缺少参数时进入交互模式。

## 验证

- Python 单测覆盖固定槽位、动态当前模型、精确恢复和 MO 清理。
- bash、zsh、fish 集成测试验证无参数 default 不依赖 TTY，且当前 shell 获得 Custom 槽位变量。
- Devix 中启动全新 Claude Code 会话，执行 `/model`，确认四个固定模型以及一个不同的当前模型可见。

