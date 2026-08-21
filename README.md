# Skills Hub — 个人能力中心

自研技能中心：存放可复用的 agent skills（Hermes / 任意支持 SKILL.md 的 agent）。

## 结构

```
skills/<skill-name>/SKILL.md   # 存储层：跨 agent 标准 skill 格式
mcp/                           # 门面层：MCP 服务器（任意 MCP 客户端可用）
claude/                        # Claude Code 客户端：安装脚本 + 使用文档
```

## 安装到 Hermes

```bash
# 方案 A：作为 skill 源（tap）
hermes skills tap add https://github.com/Tania-X/skills-hub
hermes skills install pr-ai-review-loop

# 方案 B：手动复制
git clone https://github.com/Tania-X/skills-hub.git
# 把 skills/<name> 目录复制到 $HERMES_HOME/skills/ 下
```

## 安装到 Claude Code

Claude Code 原生支持 SKILL.md（`~/.claude/skills/<name>/SKILL.md` 启动时自动发现），
本仓库 skills 可直接复用，功能与 Hermes 完全对等：

```bash
# 方案 B（推荐）：一键安装到 ~/.claude/skills
powershell -ExecutionPolicy Bypass -File claude/install.ps1   # Windows
bash claude/install.sh                                        # macOS / Linux

# 方案 C：注册 MCP（install_skill 写入 ~/.claude/skills）
claude/install.ps1 -RegisterMcp   # 或见 claude/README.md 手动命令
```

详见 [claude/README.md](claude/README.md)。

## 通过 MCP 使用（方案 C）

本仓库是能力中心的**存储层**；接入 MCP 服务器（如 `mcp-server-skills-hub`，见 `mcp/` 目录）后，
任意 MCP 客户端可动态发现/拉取 skill。

## Skills

| Skill | 说明 |
|-------|------|
| [pr-ai-review-loop](skills/pr-ai-review-loop/) | Push → 发起 PR → 监听 CI/AI review → 按意见循环改进（三角色模型，成本敏感版） |
| [ai-review-method](skills/ai-review-method/) | AI 代码评审方法论壳：上下文收集、agentic 代码访问、两轴严重度、质量门、issues JSON 输出 |
| [review-severity-policy](skills/review-severity-policy/) | 严重度判定策略插件（LLM 只判事实、代码映射数字），可插拔可校准 |
| [hermes-gateway-deploy](skills/hermes-gateway-deploy/) | 在远程服务器部署 Hermes gateway 暴露 webhook，双重认证 + systemd/caddy 实录 |
