# ccswitch

在 [Claude Code](https://claude.com/claude-code) 的两套 API 端点之间快速切换——比如本地/官方端点和一个走内部代理的备用端点。

支持 **fish**、**bash**、**zsh**。

切换时会同步做两件事：

1. 改写 `~/.claude/settings.json` 里的 `env` 块（Claude Code 启动时读取的配置）
2. 设置当前 shell 的环境变量（当前终端立即生效）

## 快速安装

一行命令，自动检测你的 shell（fish / bash / zsh）并安装到正确的位置：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash
```

安装过程中会交互式提示输入备用端点地址和 API Key。也可以通过参数传入：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash -s -- \
  --url "https://your-endpoint/api/anthropic" \
  --key "your-api-key"
```

安装完新开一个终端：

```bash
ccswitch init      # 首次使用，保存当前默认配置（只需运行一次）
ccswitch mo        # 切到备用端点
ccswitch default   # 切回默认端点
```

## 依赖

- **fish** 或 **bash** 或 **zsh**
- Python 3（用来安全地读写 JSON，不依赖任何第三方库）
- 已经跑过至少一次 `claude`，让 `~/.claude/settings.json` 存在

## 手动安装

<details>
<summary>fish</summary>

```bash
# 复制文件
cp fish/*.fish lib/ccswitch_backend.py ~/.config/fish/functions/
```

fish 会自动 autoload，无需额外配置。然后在 `~/.config/fish/config.fish` 中加上端点配置：

```fish
set -gx MO_ANTHROPIC_BASE_URL "https://your-endpoint/api/anthropic"
set -gx MO_ANTHROPIC_API_KEY "your-api-key"
```
</details>

<details>
<summary>bash / zsh</summary>

```bash
# 复制文件
mkdir -p ~/.local/share/ccswitch
cp bash/ccswitch.bash lib/ccswitch_backend.py ~/.local/share/ccswitch/
```

在 `~/.bashrc`（bash）或 `~/.zshrc`（zsh）末尾添加：

```bash
export CCSWITCH_BACKEND="$HOME/.local/share/ccswitch/ccswitch_backend.py"
source "$HOME/.local/share/ccswitch/ccswitch.bash"

export MO_ANTHROPIC_BASE_URL="https://your-endpoint/api/anthropic"
export MO_ANTHROPIC_API_KEY="your-api-key"
```
</details>

## 用法

```bash
ccswitch status                 # 查看当前用的是哪套端点、哪个模型
ccswitch mo                     # 切到备用端点，模型默认 claude-opus-4-6[1m]
ccswitch mo claude-sonnet-5     # 切到备用端点，指定模型
ccswitch default                # 切回默认端点，恢复 opus/haiku/sonnet 各自独立的配置
ccswitch default claude-sonnet-5 # 切回默认端点，但所有模型都统一成这个
ccswitch help                   # 查看帮助
```

模型名会自动补上 `[1m]`（1M 上下文）后缀，直接输短名即可。

切换后需要重启已经在跑的 Claude Code 进程才会生效；新开的 `claude` 会立即用上新配置。

## 文件说明

| 路径 | 作用 |
|---|---|
| `lib/ccswitch_backend.py` | 实际读写 `settings.json` 的逻辑，shell 无关；所有敏感值通过环境变量传入 |
| `fish/ccswitch.fish` | fish 包装函数 |
| `fish/_ccswitch_normalize_model.fish` | fish 工具函数：给模型名补 `[1m]` 后缀 |
| `bash/ccswitch.bash` | bash/zsh 包装函数（source 到 shell 里用） |
| `install.sh` | 一键安装脚本，自动检测 shell |

运行时会在 `~/.claude/` 下产生两个本机状态文件：

- `ccswitch-defaults.json` — `ccswitch init` 保存的默认端点快照
- `ccswitch-profile` — 记录当前处于 `mo` 还是 `default`

## 设计取舍

- **只有两个 profile**（`mo` / `default`），不是通用的多端点管理器。如果你需要三个以上端点，简单的做法是复制一份改个名字。
- **原地改写 `settings.json`**，而不是切换多份配置文件再软链——这样和 Claude Code 自己的配置读取逻辑保持一致。

## 安全说明

- 脚本本身不包含任何密钥或内网地址，端点信息完全来自你自己设置的环境变量。
- `ccswitch_backend.py` 用环境变量而不是命令行参数传递密钥，避免密钥出现在 `ps aux` 这类进程列表里。
- 写 `settings.json` 时先写临时文件再原子替换（`os.replace`），避免中途崩溃导致配置文件损坏。
