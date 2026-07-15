# Shells

macOS 下代理工具的一键部署与管理脚本集合。

## 脚本说明

### sub2xray.sh

订阅链接转 Xray 配置 + 一键部署，支持通过 `curl | bash` 远程执行。

**功能：**
- 解析 base64 编码的 vless 订阅链接
- 自动安装 Homebrew 和 Xray（如未安装）
- 生成 Xray 配置并启动服务
- 本地监听 SOCKS5 (28880) 和 HTTP (28881) 代理端口
- 支持 reality / tls 等传输协议
- 国内 IP 和域名自动直连

**用法：**

```bash
# 远程一键部署
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/master/sub2xray.sh | bash -s -- "<订阅URL>"

# 仅查看生成的配置，不安装
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/master/sub2xray.sh | bash -s -- "<订阅URL>" --dry-run

# 本地执行
./sub2xray.sh <订阅URL>
./sub2xray.sh <订阅URL> --dry-run
```

### install-proxy-wrapper.sh

为 `claude` 和 `codex` 命令安装代理检查 wrapper，自动识别用户的 shell 环境。

**功能：**
- 自动检测 bash / zsh / fish 并安装对应格式的 wrapper
- `claude` wrapper：检查代理连通性、校验出口 IP、确认后启动
- `codex` wrapper：设置代理环境变量、检查连通性后启动
- `opencodex` wrapper：设置代理、检查出口 IP 后打开 Codex 桌面应用
- `codex app` 会优先按 bundle identifier 打开已安装的桌面应用，避免旧版 CLI
  只查找 `/Applications/Codex.app` 时误判缺失并重新下载安装器
- 支持卸载和预览模式

**用法：**

```bash
# 远程执行（自动检测 shell，兼容 Bash / Zsh / Fish）
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/install-proxy-wrapper.sh | bash

# 指定目标 shell，例如在 Fish 中安装 Zsh wrapper
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/install-proxy-wrapper.sh | bash -s -- --shell zsh

# 预览生成内容
./install-proxy-wrapper.sh --dry-run

# 仅输出 shell 与 Codex CLI 诊断信息，不检查代理或修改配置
./install-proxy-wrapper.sh --diagnose

# 卸载
./install-proxy-wrapper.sh --uninstall
```

安装器优先识别执行命令时的实际 shell。例如默认 shell 为 Fish、但当前手动
进入 Zsh 后执行安装命令时，会更新 `~/.zshrc`。`--shell zsh` 可用于显式覆盖。

`opencodex` 通过 bundle identifier `com.openai.codex` 启动应用，而不是依赖
`Codex.app` 的文件名；当前安装包显示为 `ChatGPT.app` 时也可以正常启动。

安装器会移除与 `claude`、`codex`、`opencodex` 同名的 shell alias，避免 Zsh
在定义 wrapper 时出现 `parse error near '()'`，或由 alias 绕过代理检查。

`codex` wrapper 会验证 PATH 中的每个 Codex CLI 候选项，自动跳过损坏的 npm
安装；若 PATH 中没有可用版本，会尝试 ChatGPT/Codex 桌面应用内置的 CLI。
当 `codex app` 检测到当前机器已安装 bundle identifier 为 `com.openai.codex`
的桌面应用时，会直接打开它；带 `--help`、`--download-url` 等选项时仍交给
官方 Codex CLI 处理。

## 代理端口

| 协议 | 地址 |
|------|------|
| SOCKS5 | `127.0.0.1:28880` |
| HTTP | `127.0.0.1:28881` |

## 测试代理

```bash
# 验证代理是否工作
curl -x socks5://127.0.0.1:28880 https://www.google.com

# 查看出口 IP
curl --proxy http://127.0.0.1:28881 https://claude.ai/cdn-cgi/trace
```
