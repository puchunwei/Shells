# ccswitch

在 [Claude Code](https://claude.com/claude-code) 的两套 API 端点之间快速切换：

- **`default`** — 你平时的默认网关（`ccswitch init` 保存的那套，或 codex 首次切换时自动快照的那套）
- **`codex`** — 一个 Anthropic 兼容网关，把 Claude 的 Opus/Sonnet/Haiku 三档在服务端映射到 OpenAI/Codex 模型，让 Claude Code 跑在 Codex 订阅额度上

支持 **fish**、**bash**、**zsh**。

切换时会同步做两件事：

1. 改写 `~/.claude/settings.json` 里的 `env` 块（Claude Code 启动时读取的配置）
2. 设置当前 shell 的环境变量（当前终端立即生效）

## 快速安装

一行命令，自动检测当前正在使用的 shell（fish / bash / zsh）并安装到正确的位置。安装器会优先检查当前进程树，而不是读取代表账户默认登录 shell 的 `$SHELL`：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash
```

无法从进程树判断时，可以显式指定目标 shell：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash -s -- --shell fish
```

安装过程中会交互式提示输入 codex 端点地址和 API Key（可以直接回车跳过——首次运行 `ccswitch codex` 会再问一次）。也可以通过参数传入：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash -s -- \
  --url "https://your-endpoint/api/anthropic" \
  --key "your-api-key"
```

安装完新开一个终端：

```bash
ccswitch codex              # 切到 codex 端点（首次会提示输入 Base URL / API Key）
ccswitch default            # 切回默认网关，并配置 Claude Code /model 槽位
ccswitch init               # 可选：显式保存当前默认配置
ccswitch default --restore  # 恢复快照里保存的默认配置
```

切回默认网关后，在 Claude Code 中执行 `/model`，即可从配置好的模型槽位中交互选择。

## 依赖

- **fish** 或 **bash** 或 **zsh**
- Python 3（用来安全地读写 JSON，不依赖任何第三方库）
- 已经跑过至少一次 `claude`，让 `~/.claude/settings.json` 存在

## 手动安装

<details>
<summary>fish</summary>

```bash
# 复制文件
cp VERSION fish/*.fish lib/ccswitch_backend.py ~/.config/fish/functions/
```

fish 会自动 autoload，无需额外配置。然后在 `~/.config/fish/config.fish` 中加上端点配置：

```fish
set -gx CODEX_ANTHROPIC_BASE_URL "https://your-gateway"
set -gx CODEX_ANTHROPIC_API_KEY "your-api-key"
```

也可以不设置，首次运行 `ccswitch codex` 时交互输入。
</details>

<details>
<summary>bash / zsh</summary>

```bash
# 复制文件
mkdir -p ~/.local/share/ccswitch
cp VERSION bash/ccswitch.bash lib/ccswitch_backend.py ~/.local/share/ccswitch/
```

在 `~/.bashrc`（bash）或 `~/.zshrc`（zsh）末尾添加：

```bash
export CCSWITCH_BACKEND="$HOME/.local/share/ccswitch/ccswitch_backend.py"
source "$HOME/.local/share/ccswitch/ccswitch.bash"

export CODEX_ANTHROPIC_BASE_URL="https://your-gateway"
export CODEX_ANTHROPIC_API_KEY="your-api-key"
```

也可以不设置，首次运行 `ccswitch codex` 时交互输入。
</details>

## 用法

```bash
ccswitch status                 # 查看当前用的是哪套端点、哪个模型
ccswitch codex                  # 切到 codex 端点，当前模型默认 claude-opus-5
ccswitch codex claude-sonnet-5  # 切到 codex 端点并指定当前模型（不会加 [1m]）
ccswitch default                # 恢复默认网关，并配置 Claude Code /model 槽位
ccswitch default glm-5.2        # 指定当前模型，固定 /model 槽位保持不变
ccswitch single glm-5.2         # 恢复默认网关，并将所有模型槽位统一为 glm-5.2
ccswitch default --restore      # 恢复 init 保存的各模型独立配置
ccswitch models                 # 查看 CloudCLI 实时模型目录和客户端兼容性
ccswitch version                # 查看本地版本并检查 GitHub 最新版本
ccswitch update                 # 更新脚本，不修改现有端点配置
ccswitch help                   # 查看帮助
```

Claude Code 需要通过模型名里的 `[1m]` 选择项识别 1000K 上下文窗口。脚本会为已知 Claude Opus/Sonnet 模型自动添加或保留 `[1m]`；其他模型传入误带的 `[1m]` / `[1M]` 时，会在写入配置前移除：

| 输入 | 最终模型 ID |
|---|---|
| `claude-opus-5` | `claude-opus-5[1m]` |
| `claude-sonnet-5` | `claude-sonnet-5[1m]` |
| `claude-opus-4.6` | `claude-opus-4-6[1m]`（旧 ID 自动规范化） |
| `claude-opus-5[1m]` | `claude-opus-5[1m]` |
| `claude-opus-4-6[1m]` | `claude-opus-4-6[1m]` |
| `qwen3.8-max` | `qwen3.8-max` |
| `qwen3.7-max` | `qwen3.7-max` |
| `qwen3.7-plus` | `qwen3.7-plus` |
| `GLM-5.2` | `glm-5.2`（大小写自动规范化） |
| `deepseek-v4-pro` | `deepseek-v4-pro` |
| `qwen3.8-flash` | `qwen3.8-flash` |

## codex 端点

`ccswitch codex` 指向一个 **Anthropic 兼容网关**（例如 Sub2API），由网关在服务端把 Claude 的模型系列映射到 OpenAI/Codex 模型。因此 Claude Code 侧要继续请求标准的 Claude 系列名，网关才能按档匹配：

| Claude Code 档位 | 写入的模型 ID | 网关侧映射到 |
|---|---|---|
| Opus | `claude-opus-5` | 由网关配置（例如 `gpt-5.6-sol`） |
| Sonnet | `claude-sonnet-5` | 由网关配置（例如 `gpt-5.6-sol`） |
| Haiku | `claude-haiku-4-5` | 由网关配置（例如 `gpt-5.6-luna`，最便宜的一档） |

两个关键取舍：

- **三档保持独立**，不像旧的 `mo` 那样把六个模型键统一成一个值。成本分层完全依赖这个区分——Claude Code 会用 Haiku 档跑标题、摘要和 `count_tokens` 探测，调用量大但任务轻，映射到便宜模型能省很多。
- **不写 `[1m]` 选择项**。上游是 GPT 模型，1M 上下文标记在这里没有意义，而且会让 Claude Code 迟迟不压缩上下文，最后在上游炸掉。不带标记时 Claude Code 按 200K 处理，对 GPT 上游是合理的保守值。

### 首次配置

第一次运行 `ccswitch codex` 时，如果 `CODEX_ANTHROPIC_BASE_URL` / `CODEX_ANTHROPIC_API_KEY` 都没设置，会交互提示输入（API Key 不回显），**先只在当前 shell 生效**，然后询问是否写入 shell 配置永久保存。非交互式终端下不提示，直接报错并给出手动设置方式。

### 不需要先跑 init

`ccswitch codex` 在 `~/.claude/ccswitch-defaults.json` 不存在时，会先把当前 `settings.json` 的 `env` 快照下来再改写。这样即使从没运行过 `ccswitch init` 也能用 `ccswitch default` 切回去。

`ccswitch init` 读的是调用方**已导出的** `ANTHROPIC_*` 环境变量，只有你确实 export 过才有意义；自动快照读的是 Claude Code 真正会读的那个文件，所以更可靠。

## Claude Code `/model` 槽位

`ccswitch default` 会使用 Claude Code 的公开配置项写入以下槽位：

| `/model` 位置 | 模型 |
|---|---|
| Opus | `claude-opus-5[1m]` |
| Sonnet | `claude-sonnet-5[1m]` |
| Haiku | `qwen3.8-max` |
| Custom | `deepseek-v4-pro`（显示为 `DeepSeek V4Pro`） |

进入 Claude Code 后运行 `/model` 即可交互选择。`ccswitch default <model-id>` 只修改当前模型，不会覆盖上述固定槽位；当当前模型是 `glm-5.2`、`qwen3.7-max` 等其他模型时，Claude Code 通常会把它作为额外一项显示。

如果你希望只保留一个模型选择，可以使用 `ccswitch single <model-id>`。它会切回默认网关，并把当前模型、small fast、subagent、Opus、Sonnet、Haiku 和 Custom 槽位全部写成同一个模型。

Claude Code 公开配置目前只提供 Opus、Sonnet、Haiku 和一个 Custom 槽位，因此不能通过这套稳定配置把全部 CloudCLI 模型同时固定到 `/model`。`ccswitch default --restore` 不注入这些槽位，而是精确恢复 `ccswitch init` 保存的配置。

## 实时模型目录

这一节只作用于 **`default`** profile。安装了 CloudCLI 时，`ccswitch models` 和显式执行 `ccswitch default <model-id>` 会通过 CloudCLI SDK 读取当前账号的实时模型目录，并根据协议标记客户端兼容性：

- 支持 `anthropic` 协议的模型可以用于 Claude Code。
- 只支持 `response` 协议的模型会显示为“仅 OpenCode”，例如 `gpt-5.6-sol`，不会被错误写入 Claude Code 配置。

这个限制是针对**直连** CloudCLI 网关说的：Claude Code 只会讲 Anthropic 协议，而这些模型只有 `response` 协议入口。`codex` profile 走的是另一条路——由 Anthropic 兼容网关在服务端完成协议转换，所以同样的 GPT 模型在那边是可用的，只是 Claude Code 侧请求的仍然是 Claude 系列名，不是 GPT 模型 ID。

CloudCLI SDK 不存在、请求失败或超过 10 秒时，脚本会回退到内置目录并给出提示。实时目录可用时，显式传入未知模型会被拒绝；回退模式下允许传入新模型 ID，以免网关新增模型后脚本阻塞使用。

2026-09-04 在 Claude CLI 2.1.234 + CloudCLI / Ducky 网关实测：`claude-opus-5`、`claude-sonnet-5` 的 CLI `contextWindow` 是 `200000`；`claude-opus-5[1m]`、`claude-sonnet-5[1m]` 的 CLI `contextWindow` 是 `1000000`。因此 ccswitch 会为这些 Claude 模型写入 `[1m]`，避免 Claude Code 在约 200K 时提前压缩上下文。

## 更新

查看当前安装版本以及是否有新版本：

```bash
ccswitch version
```

`ccswitch status` 只显示本地版本，不联网；`ccswitch version` 才会访问 GitHub 的 `ccswitch/VERSION` 检查更新。

已经安装新版后，直接运行：

```bash
ccswitch update
```

从不支持 `ccswitch update` 的旧版本首次升级，重新运行安装器的更新模式：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash -s -- --update
```

更新模式只替换 ccswitch 程序文件，不会询问、删除或覆盖现有的 `CODEX_ANTHROPIC_BASE_URL` 和 `CODEX_ANTHROPIC_API_KEY`。

切换后需要重启已经在跑的 Claude Code 进程才会生效；新开的 `claude` 会立即用上新配置。

## 文件说明

| 路径 | 作用 |
|---|---|
| `lib/ccswitch_backend.py` | 模型目录、Claude Code 模型槽位和 `settings.json` 读写逻辑；shell 无关 |
| `VERSION` | ccswitch 的单一版本号来源 |
| `fish/ccswitch.fish` | fish 包装函数 |
| `fish/_ccswitch_normalize_model.fish` | fish 工具函数：规范化 Claude 1M 模型选择项 |
| `bash/ccswitch.bash` | bash/zsh 包装函数（source 到 shell 里用） |
| `install.sh` | 一键安装脚本，自动检测 shell |

运行时会在 `~/.claude/` 下产生两个本机状态文件：

- `ccswitch-defaults.json` — 默认端点快照（`ccswitch init` 保存，或 `ccswitch codex` 首次切换时从 `settings.json` 自动生成）
- `ccswitch-profile` — 记录当前处于 `codex` 还是 `default`

## 设计取舍

- **只有两个 profile**（`codex` / `default`），不是通用的多端点管理器。如果你需要三个以上端点，简单的做法是复制一份改个名字。
- **原地改写 `settings.json`**，而不是切换多份配置文件再软链——这样和 Claude Code 自己的配置读取逻辑保持一致。

## 安全说明

- 脚本本身不包含任何密钥或内网地址，端点信息完全来自你自己设置的环境变量。
- `ccswitch_backend.py` 用环境变量而不是命令行参数传递密钥，避免密钥出现在 `ps aux` 这类进程列表里。
- 写 `settings.json` 时先写临时文件再原子替换（`os.replace`），避免中途崩溃导致配置文件损坏。
