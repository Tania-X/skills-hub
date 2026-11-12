# mcp-server-skills-hub

能力中心 MCP 服务器（方案 C 门面层）：把 [skills-hub](https://github.com/Tania-X/skills-hub) 仓库中的
skills 通过 MCP 协议暴露给任何支持 MCP 的 agent（Hermes / Claude Code / Codex / Coze / Dify 等）。

> **各客户端接入手册（含 Dify 1.17 踩坑）见 [CLIENT-INTEGRATIONS.md](CLIENT-INTEGRATIONS.md)**。
> **凭据约定**：服务器 IP/端口/用户名/密码在文档中以占位符出现，实际值见本地 `cloud-services.md`（勿提交公开仓库）。

## 功能

| 工具 | 说明 |
|------|------|
| `list_skills` | 列出能力中心所有可用 skills（含远程版本、本地已安装版本、是否可升级） |
| `get_skill` | 获取某个 skill 的完整 SKILL.md 内容（+ 元信息） |
| `get_skill_changelog` | 获取某个 skill 的 CHANGELOG.md 内容和解析后的版本历史 |
| `list_skill_versions` | 列出某个 skill 的所有历史版本（从 CHANGELOG.md 解析） |
| `install_skill` | 把 skill（含 `dependencies` 硬依赖）安装到本地 skills 目录（目录由 `SKILLS_HUB_INSTALL_DIR` 指定） |
| `upgrade_skill` | 升级已安装的 skill 到最新版本（强制重新拉取并覆盖本地） |
| `refresh_cache` | 重新拉取远端仓库索引（本地缓存失效时用） |

> **依赖语义**：frontmatter 的 `dependencies`（列表或逗号分隔字符串）是**硬依赖**，
> `install_skill(with_deps=True)` 会递归安装（BFS，防环）；`related_skills` 只是关联提示，
> **不安装**、缺失不阻塞。
>
> **安全**：skill 名称经白名单校验（仅字母/数字/点/下划线/连字符），
> `../../xxx` 之类的路径穿越名称会被拒绝并返回 error。

## 依赖要求

```bash
pip install "mcp>=1.26,<2" fastmcp redis
```

> `redis` 为**可选依赖**：未安装或未配置连接串时，缓存与限流自动降级到进程内内存，服务照常运行。

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
# 启动远程服务（带 API Key 认证）
export SKILLS_HUB_API_KEY="your-secret-key-here"
python mcp_server.py --transport http --host 0.0.0.0 --port 8910

# 健康检查（无需认证）
curl http://localhost:8910/health
# {"status":"ok","service":"skills-hub-mcp","auth_enabled":true,...}

# Hermes 客户端连接（带认证）
mcp_servers:
  skills_hub:
    url: "http://your-server:8910/mcp"
    headers:
      Authorization: "Bearer your-secret-key-here"
```

> **安全说明**：
> - 设置 `SKILLS_HUB_API_KEY` 环境变量后，所有 `/mcp` 端点需要带 `Authorization: Bearer <key>` 请求头
> - `/health` 端点无需认证，可用于负载均衡健康检查
> - 生产环境建议前面再加一层 HTTPS 反代（Nginx/Caddy）

## 缓存与限流

- **缓存层**：索引、单条 skill 内容、changelog 都带 TTL 缓存。配置 `SKILLS_HUB_REDIS_URL` 后走 Redis 分布式缓存（多实例共享、重启不丢）；**Redis 不可用时自动降级到进程内内存字典**，缓存故障不会拖垮服务。`refresh_cache` 会同时清空 Redis 与内存中的索引 / 内容 / changelog 缓存。
- **限流层**：HTTP 模式按身份（API Key；未配 API Key 时按匿名 / `x-tenant-id`）做**固定窗口限流**，用 Redis `INCR + EXPIRE` 计数，超阈值返回 `429`（带 `Retry-After`）；Redis 不可用时降级为进程内内存计数器。`/health` 不限流。

```bash
# 可选：启用 Redis（不配置则纯内存降级）
export SKILLS_HUB_REDIS_URL="redis://127.0.0.1:6379/0"
# 限流阈值与窗口（默认 60 次 / 60 秒）
export SKILLS_HUB_RATE_LIMIT="60"
export SKILLS_HUB_RATE_WINDOW="60"
```

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
| `SKILLS_HUB_API_KEY` | 空 | HTTP 模式认证密钥（设置后客户端需带 `Authorization: Bearer <key>` 请求头） |
| `SKILLS_HUB_REDIS_URL` | 空 | Redis 连接串（可选，如 `redis://127.0.0.1:6379/0`）；未配置或连接失败时降级内存缓存 / 内存限流 |
| `SKILLS_HUB_RATE_LIMIT` | `60` | 限流阈值：每个身份在一个窗口内允许的最大请求数 |
| `SKILLS_HUB_RATE_WINDOW` | `60` | 限流窗口秒数（固定窗口） |

## 与仓库关系

- 本目录（`mcp/`）是 skills-hub 仓库的一部分 —— 存储层 + 门面层同仓
- `install_skill` 写入的目录是运行 MCP 的机器本地（Hermes: `$HERMES_HOME/skills/`；
  Claude Code: `SKILLS_HUB_INSTALL_DIR` 指向的 `~/.claude/skills/`），
  实现"任意机器连上即可安装"
