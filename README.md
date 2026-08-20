# Skills Hub — 个人能力中心

自研技能中心：存放可复用的 agent skills（Hermes / 任意支持 SKILL.md 的 agent）。

## 结构

```
skills/<skill-name>/SKILL.md
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

## 通过 MCP 使用（方案 C）

本仓库是能力中心的**存储层**；接入 MCP 服务器（如 `mcp-server-skills-hub`，见 `mcp/` 目录）后，
任意 MCP 客户端可动态发现/拉取 skill。

## Skills

| Skill | 说明 |
|-------|------|
| [pr-ai-review-loop](skills/pr-ai-review-loop/) | Push → 发起 PR → 监听 CI/AI review → 按意见循环改进（成本敏感版） |
