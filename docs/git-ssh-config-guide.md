# Git & SSH 多平台配置指南

本文档记录了 GitHub（个人）和 GitLab（公司）的 Git + SSH 配置方式，便于在新机器上快速恢复环境。

---

## 1. 整体架构

```
~/.gitconfig                  # 主配置，默认 include 公司配置
├── include .gitconfig-work   # 公司 GitLab 用户信息（全局默认）
├── includeIf ~/Repository/sandbox/
│   └── .gitconfig-sandbox    # 个人 GitHub 用户信息（sandbox 目录下自动切换）
└── git-lfs 配置

~/.ssh/config                 # SSH 多 Host 密钥分离
├── gitlab_rsa                # GitLab (RSA)
├── id_ed25519                # GitHub (Ed25519)
└── 其他 VPS 密钥
```

核心思路：**用 Git 的 `includeIf` 按目录自动切换用户身份，用 SSH config 按 Host 自动选择密钥。**

---

## 2. SSH 密钥生成

### GitHub（Ed25519，推荐）

```bash
ssh-keygen -t ed25519 -C "<your-personal-email>" -f ~/.ssh/id_ed25519
```

### GitLab（RSA）

```bash
ssh-keygen -t rsa -b 4096 -C "<your-work-email>" -f ~/.ssh/gitlab_rsa
```

生成后将 `.pub` 公钥内容分别添加到：
- GitHub: https://github.com/settings/keys
- GitLab: https://<your-gitlab-domain>/-/profile/keys

---

## 3. SSH 配置

编辑 `~/.ssh/config`：

```ssh-config
Host *
    ControlPath /tmp/ssh-%r@%h:%p
    ControlMaster auto
    ServerAliveInterval 60

# GitHub
Host github.com
    HostName github.com
    PreferredAuthentications publickey
    IdentityFile ~/.ssh/id_ed25519

# GitLab（公司内网）
Host <your-gitlab-domain>
    HostName <your-gitlab-domain>
    PreferredAuthentications publickey
    IdentityFile ~/.ssh/gitlab_rsa

# 公司内网域名兼容旧算法
Host *.<your-corp-domain>
    KexAlgorithms +diffie-hellman-group1-sha1,diffie-hellman-group14-sha1
```

验证连通性：

```bash
ssh -T git@github.com
ssh -T git@<your-gitlab-domain>
```

---

## 4. Git 用户配置

### 4.1 主配置 `~/.gitconfig`

```ini
[include]
    path = .gitconfig-work

[includeIf "gitdir:~/Repository/sandbox/"]
    path = .gitconfig-sandbox

[filter "lfs"]
    clean = git-lfs clean -- %f
    smudge = git-lfs smudge -- %f
    process = git-lfs filter-process
    required = true

[core]
    symlinks = false
```

### 4.2 公司配置 `~/.gitconfig-work`（默认生效）

```ini
[user]
    name = <your-work-username>
    email = <your-work-email>
```

### 4.3 个人配置 `~/.gitconfig-sandbox`（sandbox 目录下生效）

```ini
[user]
    name = <your-github-username>
    email = <your-personal-email>
```

---

## 5. 目录规划

| 路径 | 用途 | Git 身份 |
|------|------|----------|
| `~/Repository/` | 公司项目（默认） | <your-work-username> / <your-work-email> |
| `~/Repository/sandbox/` | 个人项目 (GitHub) | <your-github-username> / <your-personal-email> |

新克隆项目时，放到对应目录即可自动使用正确的用户身份，无需手动设置。

---

## 6. 新机器快速配置步骤

```bash
# 1. 生成密钥
ssh-keygen -t ed25519 -C "<your-personal-email>" -f ~/.ssh/id_ed25519
ssh-keygen -t rsa -b 4096 -C "<your-work-email>" -f ~/.ssh/gitlab_rsa

# 2. 将公钥添加到 GitHub / GitLab 网站

# 3. 创建 SSH config
cat > ~/.ssh/config << 'EOF'
Host *
    ControlPath /tmp/ssh-%r@%h:%p
    ControlMaster auto
    ServerAliveInterval 60

Host github.com
    HostName github.com
    PreferredAuthentications publickey
    IdentityFile ~/.ssh/id_ed25519

Host <your-gitlab-domain>
    HostName <your-gitlab-domain>
    PreferredAuthentications publickey
    IdentityFile ~/.ssh/gitlab_rsa

Host *.<your-corp-domain>
    KexAlgorithms +diffie-hellman-group1-sha1,diffie-hellman-group14-sha1
EOF
chmod 600 ~/.ssh/config

# 4. 创建 Git 配置
cat > ~/.gitconfig-work << 'EOF'
[user]
    name = <your-work-username>
    email = <your-work-email>
EOF

cat > ~/.gitconfig-sandbox << 'EOF'
[user]
    name = <your-github-username>
    email = <your-personal-email>
EOF

cat > ~/.gitconfig << 'EOF'
[include]
    path = .gitconfig-work

[includeIf "gitdir:~/Repository/sandbox/"]
    path = .gitconfig-sandbox

[filter "lfs"]
    clean = git-lfs clean -- %f
    smudge = git-lfs smudge -- %f
    process = git-lfs filter-process
    required = true
EOF

# 5. 创建目录
mkdir -p ~/Repository/sandbox

# 6. 验证
ssh -T git@github.com
ssh -T git@<your-gitlab-domain>
cd ~/Repository/sandbox && git init && git config user.email  # 应显示个人邮箱
cd ~/Repository && git init test-work && cd test-work && git config user.email  # 应显示公司邮箱
```

---

## 7. 常见问题

**Q: `includeIf` 不生效？**
A: `gitdir` 路径必须以 `/` 结尾，且目录必须是 git 仓库（有 `.git` 目录）。

**Q: SSH 连接超时？**
A: 检查是否在内网环境（GitLab 需要），或尝试 `ssh -vT git@host` 查看详细日志。

**Q: 提交用了错误的用户名？**
A: 用 `git config user.name` 在仓库内确认当前生效的身份，检查仓库路径是否在正确的目录下。
