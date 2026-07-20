# Shells

macOS 下代理工具的一键部署与管理脚本集合。

## 脚本说明

### sub2xray.sh

订阅链接或单条 VLESS 节点转 Xray 配置 + 一键部署，支持通过 `curl | bash` 远程执行。

**功能：**
- 解析 base64 编码的 vless 订阅链接
- 支持直接传入单条 `vless://` 节点
- 自动安装 Homebrew 和 Xray（如未安装）
- 生成 Xray 配置并启动服务
- 部署失败时自动输出 Xray/Homebrew/launchd 诊断信息
- 本地监听 SOCKS5 (28880) 和 HTTP (28881) 代理端口
- 支持 reality / tls 等传输协议
- 国内 IP 和域名自动直连

**用法：**

```bash
# 远程一键部署（订阅 URL）
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/master/sub2xray.sh | bash -s -- "<订阅URL>"

# 远程一键部署（单条 VLESS 节点）
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/master/sub2xray.sh | bash -s -- 'vless://uuid@host:443?security=reality&type=tcp&sni=example.com&fp=chrome&pbk=publicKey&sid=shortId#node-name'

# 仅查看生成的配置，不安装
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/master/sub2xray.sh | bash -s -- "<订阅URL>" --dry-run

# 输出诊断摘要
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash

# 诊断并做一次 4 秒前台启动探测
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash -s -- --run-check

# 输出完整诊断明细
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash -s -- --verbose

# 本地执行
./sub2xray.sh <订阅URL>
./sub2xray.sh 'vless://uuid@host:443?security=reality&type=tcp&sni=example.com&fp=chrome&pbk=publicKey&sid=shortId#node-name'
./sub2xray.sh <订阅URL> --dry-run
./sub2xray.sh --diagnose
./sub2xray.sh --diagnose --run-check
./sub2xray.sh --diagnose --verbose
```

直接传 `vless://` 时请用单引号包起来，避免 shell 把 `&`、`?`、`#` 等字符当作命令语法处理。

默认诊断会输出摘要：Homebrew/Xray 路径、配置验证、服务状态、端口占用和
launchctl 摘要。它不会主动打印完整 `config.json`，避免泄露节点信息。需要完整
PATH、Zsh/Fish、plist 和系统日志时再加 `--verbose`。

### diagnose-xray.sh

Xray/Homebrew 服务诊断脚本，用于排查“配置验证通过但服务未启动”等问题。

**功能：**
- 默认输出简洁摘要，便于用户直接复制回来
- 检查 Homebrew、Xray 安装路径和版本
- 检查 Xray 配置文件是否存在并运行 `xray run -test`
- 输出 `brew services info/list xray`
- 输出 launchd 的用户服务摘要
- 检查 `28880` / `28881` 端口是否被占用
- 默认跳过较慢的系统日志扫描
- 可选执行 4 秒前台启动探测，观察 Xray 是否立即崩溃
- `--verbose` 输出完整 PATH、Zsh/Fish、plist、launchctl 和系统日志明细

**用法：**

```bash
# 远程诊断
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash

# 远程诊断 + 前台启动探测
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash -s -- --run-check

# 远程完整诊断
curl -Ls https://raw.githubusercontent.com/puchunwei/Shells/refs/heads/master/diagnose-xray.sh | bash -s -- --verbose

# 本地诊断
./diagnose-xray.sh
./diagnose-xray.sh --run-check
./diagnose-xray.sh --verbose
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
安装完成后脚本会输出当前终端立即生效命令；由于 `curl | bash` 运行在子进程中，
无法替当前父终端自动执行 `source`，执行提示命令或重新打开终端即可生效。

常见立即生效命令:

```text
# Fish
for f in claude codex opencodex; functions -e $f; source ~/.config/fish/functions/$f.fish; end

# Zsh
source ~/.zshrc
```

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
