# Skills Hub — 个人能力中心

自研技能中心：存放可复用的 agent skills（Hermes / 任意支持 SKILL.md 的 agent）。

## 结构

```
skills/<skill-name>/SKILL.md   # 存储层：跨 agent 标准 skill 格式
mcp/                           # 门面层：MCP 服务器（任意 MCP 客户端可用）
hermes/                        # Hermes 客户端：安装脚本 + 使用文档
claude/                        # Claude Code 客户端：安装脚本 + 使用文档
```

## 客户端（每个 agent 一个平级目录，结构对等）

| 客户端 | 目录 | 方案 A（注册即装） | 方案 B（复制安装） | 方案 C（MCP） |
|--------|------|-------------------|-------------------|--------------|
| Hermes | [hermes/](hermes/README.md) | `hermes skills tap add` | `hermes/install.ps1` / `install.sh` | config.yaml 手写 |
| Claude Code | [claude/](claude/README.md) | 无对等命令（脚本或 plugin marketplace） | `claude/install.ps1` / `install.sh` | `claude mcp add skills-hub` |

```bash
# Hermes
powershell -ExecutionPolicy Bypass -File hermes/install.ps1   # Windows；Linux 用 bash hermes/install.sh
# Claude Code
powershell -ExecutionPolicy Bypass -File claude/install.ps1   # Windows；Linux 用 bash claude/install.sh
```

详细用法见 [hermes/README.md](hermes/README.md) 与 [claude/README.md](claude/README.md)。

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
