# ccswitch 0.6.0

为 Claude Code 保存多套连接，并管理每套连接的模型组合。支持 bash、zsh、fish 和独立命令。

日常只有两个入口：

```bash
ccswitch use                     # 终端中选择连接、预览目标并确认应用
ccswitch use personal            # 直接应用已保存连接
ccswitch slots                   # 编辑当前连接的槽位和菜单
ccswitch slots personal          # 查看某套已保存的组合
ccswitch slots edit personal     # 交互编辑，选择保存或保存并应用
```

`use` 会修改全局 Claude 配置，并同步当前 Shell 的受管环境变量。默认目标为 `~/.claude/settings.json`；设置 `CLAUDE_CONFIG_DIR` 可指定另一目录。这会影响使用同一目录的 Claude 会话。远端 Claude 需要在远端运行 ccswitch。项目配置、策略或其他认证来源可能覆盖全局设置，使用 `ccswitch doctor` 查看冲突。

已运行的 Claude Code 支持的设置热更新可能有延迟。当前会话若固定选择了主模型，需要在 Claude 内用 `/model` 重新选择；新启动的 Claude 会读取应用后的配置。

## 安装与更新

依赖 Python 3，以及 bash、zsh、fish 中的一种；联网安装和检查更新还需要 curl。安装过程不录入密钥、不启动 Claude。

```bash
# 联网安装；从进程树识别当前 Shell，也可显式指定
curl -fsSL https://raw.githubusercontent.com/puchunwei/Shells/master/ccswitch/install.sh | bash -s -- --shell bash

# 从本地检出的目录安装，完全不联网
bash ccswitch/install.sh --local --shell bash
bash ccswitch/install.sh --local --shell fish
bash ccswitch/install.sh --local --shell zsh
```

程序及五个 Python 模块统一位于 `~/.local/share/ccswitch`。bash/zsh 的 rc 文件只追加一次 source；fish 自动加载函数安装到 `${XDG_CONFIG_HOME:-~/.config}/fish/functions/ccswitch.fish`。安装后新开终端，或 bash/zsh 执行：

```bash
source "$HOME/.local/share/ccswitch/ccswitch.bash"
```

独立命令安装到 `~/.local/bin/ccswitch`，请将 `~/.local/bin` 放入 PATH。它可以修改磁盘配置，但子进程无法更新父 Shell 的环境；需同步环境时使用 Shell 函数。

```bash
ccswitch version                 # 本地版本及 GitHub 最新版本检查
ccswitch version --json          # 仅查询本地版本，不联网
ccswitch update                  # 更新程序并重新加载当前 Shell 包装层
bash ccswitch/install.sh --local --shell bash --update  # 本地更新
```

`update` 在下载安装器之前先检查远端 VERSION；远端版本低于本地或格式无效时拒绝更新，保留当前安装。安装器也检查候选包版本，拒绝降级。网络失败时返回失败；安装器先准备完整文件，下载未完成不会替换程序。更新与重新安装都不修改 Claude settings、旧快照和配置库，也不执行迁移。

旧安装器的 `--url` / `--key` 已移除，改用下面的通用录入或私有文件导入。

## 保存连接与迁移

```bash
ccswitch add personal            # 真实终端中输入 URL、静态认证方式和密钥
ccswitch import work --from /path/to/private-settings.json
ccswitch save work --from current           # 只保存当前全局 settings，不应用
ccswitch save work --from current --replace # 明确覆盖同名配置
ccswitch edit work              # 终端修改连接
ccswitch list                   # 脱敏列表
ccswitch status                 # 当前磁盘、保存组合与 Shell 状态
ccswitch doctor                 # 认证、策略、项目覆盖和迁移诊断
ccswitch migrate                # 显式导入旧配置，不应用
```

非交互输入使用 `--from FILE`，文件可以是 Claude settings、导出的 profile，或旧版平铺快照。普通 `current` 导入只读取目标 settings。只支持静态 API Key 和 Bearer Token；同时存在两种有效凭据时，用 `--auth api_key` 或 `--auth bearer_token` 明确选择。不转换 OAuth、云提供商认证或 `apiKeyHelper`。

连接名称为 1～48 位小写字母、数字、短横线、下划线，以字母或数字开头；命令关键字不能作为名称，`default` 可用于迁移。保存缺少静态认证的连接是允许的，应用前必须补齐。

迁移分别读取目标目录里的 `settings.json` 和 `ccswitch-defaults.json`，保存为 `current` 和 `default`。保留原始模型 ID 和 `[1m]`；重名时保留已保存配置，重复执行不会覆盖。旧源文件不修改，也不会自动应用模板。首次写操作会尝试迁移一次；只读命令不会创建配置库，显式 `migrate` 可再次检查来源。

配置库位于 `$XDG_CONFIG_HOME/ccswitch`，未设置时为 `~/.config/ccswitch`。密钥保存在本地配置库中：目录权限 `0700`、含认证信息的文件 `0600`。普通输出、JSON 和交互预览均脱敏。不要提交私有导入文件、配置库或备份到版本控制。

## 槽位和 `/model` 菜单

每套连接维护一份组合；仅保存不会改当前 settings，`--apply` 才会同时应用并同步 Shell。

```bash
ccswitch slots set personal opus Vendor/Opus[1m]
ccswitch slots set personal sonnet Vendor/Sonnet --apply
ccswitch slots set personal haiku Vendor/Fast
ccswitch slots set personal startup sonnet        # 主模型跟随 Sonnet 槽位
ccswitch slots set personal startup Vendor/Fixed  # 固定主模型
ccswitch slots set personal subagent Vendor/Worker

ccswitch slots menu add personal --model Vendor/Extra --label 'Extra model' --description 'My model' --behaves-as sonnet
ccswitch slots menu rename personal --index 0 --label 'New label'
ccswitch slots menu move personal --index 0 --to 1
ccswitch slots menu remove personal --index 0
ccswitch slots menu builtins personal --replace-builtins false --apply
```

菜单索引从 0 开始。菜单默认追加在内置选项之后；`--replace-builtins true` 明确替换内置菜单。导入的高级 `modelPicker` 属性会保留。交互槽位编辑还支持统一模型、预览、保存、保存并应用和取消；取消不保存草稿。手工连接的模型 ID 原值保存，不自动添加或移除 `[1m]`。

## 撤销与兼容入口

```bash
ccswitch undo                    # 撤销最近一次成功应用
ccswitch init                    # 将当前配置保存为 default；覆盖需 --replace
ccswitch default --restore       # 应用保存的 default
ccswitch default [MODEL]         # default 连接上的临时兼容槽位覆盖
ccswitch single MODEL            # default 连接上临时统一模型
```

`undo` 恢复最近一次应用前的受管配置，保留其他设置；不会回滚保存的连接组合。它会显式清空失效的认证/环境值，优先保证切换正确，不承诺 settings 字节级还原。认证互换时旧认证字段显式为空，防止旧 Shell 或热更新残留。

`default [MODEL]` 和 `single MODEL` 是兼容入口，使用已保存的 default 连接，不修改保存的 default 组合。日常使用命名连接的 `use` 和 `slots`。

## 模型目录

```bash
ccswitch models                  # 模型目录及协议兼容性
ccswitch models --json
ccswitch help
```

安装 CloudCLI SDK 时，目录优先读取账号实时结果；缺失、失败或超时则回退到内置目录。`default MODEL` / `single MODEL` 的兼容入口使用已有目录校验和模型名规范化；命名连接支持自行维护上游模型 ID。目录可见或写入成功都不能证明网关有权限或实际支持该模型，ccswitch 不发起真实模型推理验证。

## 开发验证

```bash
python3 -B -m unittest discover -s ccswitch/tests -v
bash -n ccswitch/install.sh ccswitch/bash/ccswitch.bash ccswitch/bin/ccswitch
zsh -n ccswitch/bash/ccswitch.bash
fish --no-execute ccswitch/fish/ccswitch.fish
```

测试在临时 HOME 中使用真实文件、CLI、Shell 和 PTY，不修改用户配置。
