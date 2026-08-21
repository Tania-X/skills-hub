# mcp-server-skills-hub

能力中心 MCP 服务器（方案 C 门面层）：把 [skills-hub](https://github.com/Tania-X/skills-hub) 仓库中的
skills 通过 MCP 协议暴露给任何支持 MCP 的 agent（Hermes / Claude Code / Codex 等）。

## 功能

| 工具 | 说明 |
|------|------|
| `list_skills` | 列出能力中心所有可用 skills |
| `get_skill` | 获取某个 skill 的完整 SKILL.md 内容（+ 元信息） |
| `install_skill` | 把 skill（含 `dependencies` 硬依赖）安装到本地 skills 目录（目录由 `SKILLS_HUB_INSTALL_DIR` 指定） |
| `refresh_cache` | 重新拉取远端仓库索引（本地缓存失效时用） |

> **依赖语义**：frontmatter 的 `dependencies`（列表或逗号分隔字符串）是**硬依赖**，
> `install_skill(with_deps=True)` 会递归安装（BFS，防环）；`related_skills` 只是关联提示，
> **不安装**、缺失不阻塞。
>
> **安全**：skill 名称经白名单校验（仅字母/数字/点/下划线/连字符），
> `../../xxx` 之类的路径穿越名称会被拒绝并返回 error。

## 依赖要求

```bash
pip install "mcp>=1.26,<2" fastmcp
```

> ⚠️ **mcp 包版本约束**：Hermes 0.19 兼容 `mcp==1.26.x`；**mcp 2.x 改了 API 名
> （`streamable_http_client`），Hermes 会报 `streamable_http is not available`**。
> 用 `pip install 'mcp==1.26.0'` 固定版本。其他 MCP 客户端（如 Claude Code）无此限制。

## 运行方式

### stdio（推荐，Hermes / Claude Code 原生支持）

```bash
# 方式 1：直接跑（需要本目录可被找到）
python mcp_server.py

# 方式 2：Hermes config.yaml 注册
mcp_servers:
  skills_hub:
    command: "python"
    args: ["C:/Users/001/skills-hub/mcp/mcp_server.py"]

# 方式 3：Claude Code 注册（install_skill 会装到 ~/.claude/skills）
claude mcp add skills-hub --env SKILLS_HUB_INSTALL_DIR="$HOME/.claude/skills" -- python C:/Users/001/skills-hub/mcp/mcp_server.py
# 两种客户端的完整接入方式（方案 A/B/C 对照）见 ../hermes/README.md 与 ../claude/README.md
```

### HTTP（远程共享）

```bash
python mcp_server.py --transport http --host 0.0.0.0 --port 8910
# Hermes:
mcp_servers:
  skills_hub:
    url: "http://localhost:8910/mcp"
```

> ⚠️ HTTP 模式**没有内置认证**，且 server 可读/可写本地 skills 目录——只应在可信内网使用，
> 或前面加 basic_auth 反代（参考 `skills/hermes-gateway-deploy` 的双重认证做法）。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `SKILLS_HUB_REPO` | `Tania-X/skills-hub` | 能力中心仓库（owner/repo） |
| `SKILLS_HUB_BRANCH` | `main` | 拉取的分支 |
| `SKILLS_HUB_LOCAL_REPO` | 空 | 本地克隆路径（可选，优先于 GitHub API，便于离线/省配额） |
| `SKILLS_HUB_INSTALL_DIR` | `$HERMES_HOME/skills`（回退 `~/.hermes/skills`） | install_skill 的目标目录。**Claude Code 场景设为 `~/.claude/skills`（个人）或 `<项目>/.claude/skills`（项目级）** |
| `SKILLS_HUB_CACHE_TTL` | `300` | 索引与内容缓存秒数（`refresh_cache` 同时清空两者；`install_skill` 始终拉取最新内容） |
| `SKILLS_HUB_PROXY` | 空 | GitHub API 代理，如 `http://127.0.0.1:7890` |
| `SKILLS_HUB_TOKEN` / `GITHUB_TOKEN` | 空 | GitHub API Token（提高限流配额） |

## 与仓库关系

- 本目录（`mcp/`）是 skills-hub 仓库的一部分 —— 存储层 + 门面层同仓
- `install_skill` 写入的目录是运行 MCP 的机器本地（Hermes: `$HERMES_HOME/skills/`；
  Claude Code: `SKILLS_HUB_INSTALL_DIR` 指向的 `~/.claude/skills/`），
  实现"任意机器连上即可安装"
