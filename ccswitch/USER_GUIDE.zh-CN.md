# ccswitch 使用指南：用方向键选择

适用版本：0.6.6。本机已安装。菜单统一使用 **↑ / ↓ 移动、回车确认、Esc 返回**。

## 1. 更换槽位对应的模型

下面以“把 current 配置的 Sonnet 档位改用已有的 Qwen 模型”为例，全程通过菜单选择。

**第一步：在终端执行。**

```bash
ccswitch slots
```

程序会打开当前配置的编辑菜单。认不出当前配置时，会先让你选择要编辑哪套；选 `current`，回车即可。

**第二步：按 ↓ 移动到 Sonnet，回车。**

```text
编辑槽位
  Opus：claude-opus-5[1m]
> Sonnet：claude-sonnet-5[1m]
  Haiku：qwen3.8-max
  Fable：未设置
  默认启动：claude-opus-4-6[1m]
  子代理默认：claude-opus-4-6[1m]
  更多设置：额外模型菜单、统一模型
  保存并应用
  只保存
  取消修改
↑/↓ 选择 · Enter 确认 · Esc 返回
```

`>` 表示当前选中项。上面的模型值仅为示例，实际菜单展示保存的值。

**第三步：在模型列表中选中目标模型，回车。**

例如选 `qwen3.8-max`：

```text
选择 Sonnet 模型
  claude-sonnet-5[1m]  [当前]
  claude-opus-5[1m]
> qwen3.8-max
  claude-opus-4-6[1m]
  更多模型：CloudCLI 目录…
  手动输入模型 ID…
↑/↓ 选择 · Enter 确认 · Esc 返回
```

模型列表优先显示这套配置已有的模型，并保留完整 ID。已有自定义菜单或兼容字段包含其他模型时，也会显示。

列表里没有想要的模型，选择“更多模型：CloudCLI 目录…”，进入完整目录后继续用 ↑↓ 和回车选择。显示“CloudCLI 本地模型清单 · 15 个 · 2026-10-16”，直接读取本机静态数据，不联网刷新。后续需要时再统一更新清单并同步。清单也没有的自定义模型，才需要选择“手动输入模型 ID…”。

Claude 模型在完整目录中显示为“Claude Opus 5.5（1M）”等，选中后会保存 `claude-opus-5-5[1m]`。Opus 4.6、4.7、4.8、5、5.5 和 Sonnet 5 都显式带 `[1m]`。已有配置需要在完整目录重新选择一次，再“保存并应用”，才能更新对应槽位。

**第四步：回到编辑菜单，确认“保存并应用”，回车。**

选完模型后，Sonnet 那一行会更新，光标会自动停在“保存并应用”：

```text
编辑槽位
  Opus：claude-opus-5[1m]
  Sonnet：qwen3.8-max
  Haiku：qwen3.8-max
  Fable：未设置
  默认启动：claude-opus-4-6[1m]
  子代理默认：claude-opus-4-6[1m]
  更多设置：额外模型菜单、统一模型
> 保存并应用
  只保存
  取消修改
```

再按一次回车。看到 `Saved current; Applied current.` 就完成了。

也可以继续移动到其他槽位，修改完后一起保存。

| 最后选择 | 结果 |
| --- | --- |
| 保存并应用 | 保存并立即应用整套配置，退出编辑器 |
| 只保存 | 保存组合，稍后用 `ccswitch use` 选择启用 |
| 取消修改，或在编辑菜单按 Esc | 放弃本轮全部草稿修改 |

第一次只想试试界面：做到第三步后，在编辑菜单按 **Esc** 即可。

## 2. 当前聊天想用 Sonnet

在 **Claude 对话输入框**里输入：

```text
/model
```

然后在 Claude 菜单里选择 Sonnet，回车。

这会让当前聊天使用 Sonnet 档位对应的模型。本例已经把该档位映射为 `qwen3.8-max`，所以会请求这个模型。

当前聊天若已固定选择了模型，编辑槽位后需要在 `/model` 中重新选择；配置热加载也可能稍有延迟。

## 3. 公司、个人配置整套切换

在终端执行：

```bash
ccswitch use
```

先用方向键选择配置：

```text
选择配置
> current
  删除配置…
```

回车后会显示地址、认证方式、模型和目标文件。检查正确，再选择“确认应用”：

```text
确认应用到以上全局配置？
  取消
> 确认应用
```

回车完成切换。确认界面默认选中“取消”，需要移动到“确认应用”再提交。

本机现只保留 `current` 一份配置。以后新增公司或个人连接，会出现在这里；“删除配置…”是操作入口。熟悉以后，可以直接执行 `ccswitch use current`，带名字会直接应用。

## 4. 其他操作，需要时再看

<details>
<summary>删除配置 / provider</summary>

这里一份配置就包含一个 provider 的地址、认证和模型组合。

`ccswitch use` → “删除配置…” → 选择要删除的配置 → 检查预览 → “确认删除”。也可以直接运行 `ccswitch remove`，从选择配置这一步开始。

确认菜单默认选中“取消”，需要按 ↓ 再回车才会删除。删除只移除保存项，当前 Claude settings 保留。若提示配置正在使用，先切换到其他配置，再回来删除。

</details>

<details>
<summary>以后默认启动就用 Sonnet</summary>

`ccswitch slots` → 选择“默认启动” → 选择“跟随 Sonnet 槽位” → 选择“保存并应用”。

新启动的 Claude 默认选择 Sonnet。已打开的聊天按需要在 `/model` 中重选。

</details>

<details>
<summary>添加配置、更换地址或密钥</summary>

新增：`ccswitch add work`。填写地址，通过菜单选择认证方式，输入密钥；随后在槽位菜单里设置模型，选择保存或应用。

修改：`ccswitch edit work`。地址可回车保留；认证菜单可选择保持当前认证，或选择类型并填写新密钥。密钥输入不回显。

另存当前磁盘配置：`ccswitch save personal --from current`，只保存，之后用 `ccswitch use` 启用。

</details>

<details>
<summary>更多模型、额外菜单、数量限制</summary>

`ccswitch slots` → “更多设置：额外模型菜单、统一模型”，可添加、删除、改名或调整自定义模型菜单顺序。

四个基础档位是 Opus、Sonnet、Haiku、Fable；默认启动和子代理是另外两种用途的默认选择。

修改 Fable：`ccswitch slots` → “Fable” → 选择模型 → “保存并应用”。默认启动和子代理也可选择“跟随 Fable 槽位”。未配置的 Fable 显示“未设置”；当前静态目录没有 Fable 模型条目，可按网关实际支持情况映射到已有模型，或输入网关提供的完整 Fable ID。

额外菜单已实测 12 项及新增第 13 项，Claude 最大容量尚未确定。保存的配置套数没有固定上限。

“统一所有模型”也会修改已有自定义菜单项的模型。

</details>

<details>
<summary>兼容、生效范围和恢复</summary>

- 使用当前保存项：`ccswitch use current`；编辑它用 `ccswitch slots edit current`。旧的 `default` 命令及内置模型模板已删除，本机多余的 default 保存项和旧快照已备份移出。
- 全部用同一模型：槽位菜单 → “更多设置” → “统一所有模型”。旧 `single MODEL` 仅作兼容入口。
- 看当前状态：`ccswitch`；看保存项：`ccswitch list`。
- 迁移旧配置：`ccswitch migrate`。只导入缺失的 current/default，不应用，不覆盖已有同名项。
- 撤销上一次应用：`ccswitch undo`。它恢复应用前的 Claude 配置，已保存组合仍保留新值。
- 保存并应用时，会应用所编辑的整套配置，包括地址和认证；预先准备另一套配置时选择“只保存”。
- 多个会话使用同一配置目录，会共享全局切换。其他终端的旧环境变量不会自动更新。
- cloudcli-ssh 的 Claude，要登录目标远端后，在远端运行 ccswitch。
- 本版支持静态 API Key 和 Bearer Token；OAuth、云认证和 apiKeyHelper 不自动转换。
- 配置写入成功不代表网关已经验证可调用；失败或冲突用 `ccswitch doctor` 检查。
- 极简终端不支持方向键菜单时，会退为编号选择；普通终端直接使用方向键。

完整命令和安装方式见 [README](README.md)。

</details>
