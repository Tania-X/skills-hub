# mcp-server-skills-hub

能力中心 MCP 服务器（方案 C 门面层）：把 [skills-hub](https://github.com/Tania-X/skills-hub) 仓库中的
skills 通过 MCP 协议暴露给任何支持 MCP 的 agent（Hermes / Claude / Codex 等）。

## 功能

| 工具 | 说明 |
|------|------|
| `list_skills` | 列出能力中心所有可用 skills |
| `get_skill` | 获取某个 skill 的完整 SKILL.md 内容（+ 元信息） |
| `install_skill` | 把 skill 安装到本地 Hermes skills 目录（`$HERMES_HOME/skills/<name>/`） |
| `refresh_cache` | 重新拉取远端仓库索引（本地缓存失效时用） |

## 运行方式

### stdio（推荐，Hermes 原生支持）

```bash
# 方式 1：直接跑（需要本目录可被找到）
python mcp_server.py

# 方式 2：Hermes config.yaml 注册
mcp_servers:
  skills_hub:
    command: "python"
    args: ["C:/Users/001/skills-hub/mcp/mcp_server.py"]
```

### HTTP（远程共享）

```bash
python mcp_server.py --transport http --host 0.0.0.0 --port 8910
# Hermes:
mcp_servers:
  skills_hub:
    url: "http://localhost:8910/mcp"
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `SKILLS_HUB_REPO` | `Tania-X/skills-hub` | 能力中心仓库（owner/repo） |
| `SKILLS_HUB_BRANCH` | `main` | 拉取的分支 |
| `SKILLS_HUB_INSTALL_DIR` | `$HERMES_HOME/skills` | install_skill 的目标目录 |
| `SKILLS_HUB_CACHE_TTL` | `300` | 索引缓存秒数 |

## 与仓库关系

- 本目录（`mcp/`）是 skills-hub 仓库的一部分 —— 存储层 + 门面层同仓
- `install_skill` 写入的目录是运行 MCP 的机器本地（`$HERMES_HOME/skills/`），
  实现"任意机器连上即可安装"
