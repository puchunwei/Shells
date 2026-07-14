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
- 支持卸载和预览模式

**用法：**

```bash
# 远程执行（自动检测 shell）
bash <(curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/install-proxy-wrapper.sh)

# 指定 shell
bash <(curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/install-proxy-wrapper.sh) --shell fish

# 预览生成内容
./install-proxy-wrapper.sh --dry-run

# 卸载
./install-proxy-wrapper.sh --uninstall
```

`opencodex` 通过 bundle identifier `com.openai.codex` 启动应用，而不是依赖
`Codex.app` 的文件名；当前安装包显示为 `ChatGPT.app` 时也可以正常启动。

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
