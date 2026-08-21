# Claude Code 客户端（与 Hermes 完全对等的接入方式）

skills-hub 的 SKILL.md 是跨 agent 标准格式（Anthropic Agent Skills 同款），**Claude Code 原生支持**：
放在 `~/.claude/skills/<name>/SKILL.md`（个人级）或 `<项目>/.claude/skills/<name>/SKILL.md`（项目级），
启动时自动发现、按需加载。同时 Claude Code 原生支持 MCP，可**复用同一个 `mcp/mcp_server.py`**。

## 与 Hermes 方案对照

| 能力 | Hermes | Claude Code（本目录实现） |
|---|---|---|
| 方案 A：注册仓库即装 | `hermes skills tap add <repo>` | 无原生对等命令 → 用本目录安装脚本（方案 B），或把仓库做成 plugin marketplace（未实现） |
| 方案 B：复制安装 | 手动 `cp skills/* $HERMES_HOME/skills/` | `install.ps1` / `install.sh`（复制到 `~/.claude/skills` 或项目 `.claude/skills`） |
| 方案 C：MCP 动态拉取 | `mcp_servers.skills_hub` 注册 | `claude mcp add skills-hub`（`--env SKILLS_HUB_INSTALL_DIR` 指向 Claude 目录） |
| `install_skill` 写入位置 | `$HERMES_HOME/skills/` | `~/.claude/skills/`（由 `SKILLS_HUB_INSTALL_DIR` 指定） |
| 依赖安装 | frontmatter `dependencies` 硬依赖递归 | 同左（MCP 服务器逻辑共享） |

## 前置

- Node.js + Claude Code：`claude --version`（官方安装：`npm install -g @anthropic-ai/claude-code`）
- Python 3.10+（仅方案 C 需要）：`pip install "mcp>=1.26,<2" fastmcp`

## 方案 B：复制安装（推荐，无需 MCP）

```bash
# Windows（PowerShell）
powershell -ExecutionPolicy Bypass -File claude/install.ps1                # 个人级 ~/.claude/skills
powershell -ExecutionPolicy Bypass -File claude/install.ps1 -Scope project # 项目级 ./.claude/skills
powershell -ExecutionPolicy Bypass -File claude/install.ps1 -Force         # 覆盖已存在
powershell -ExecutionPolicy Bypass -File claude/install.ps1 -RegisterMcp   # 复制 + 注册 MCP

# macOS / Linux
bash claude/install.sh              # 个人级
bash claude/install.sh project      # 项目级
FORCE=1 bash claude/install.sh      # 覆盖
```

安装后**重启 Claude Code 会话**，skills 自动生效。

## 方案 C：MCP 注册（动态发现 / 安装）

```bash
# 手动注册（install_skill 会写入 ~/.claude/skills）
claude mcp add skills-hub \
  --env SKILLS_HUB_INSTALL_DIR="$HOME/.claude/skills" \
  -- python "$(pwd)/mcp/mcp_server.py"

# 验证
claude mcp list
```

然后在 Claude Code 里直接问：

- 「列出 skills-hub 有哪些 skills」→ `list_skills`
- 「安装 pr-ai-review-loop 到本地」→ `install_skill`（写进 `SKILLS_HUB_INSTALL_DIR`，下次会话生效）

（`claude mcp add` 默认注册到 user 作用域；项目级加 `--scope project`。）

## 使用 skills

Claude Code 按 skill 描述自动决定何时加载：直接描述任务即可，例如
「对这个 PR 跑一遍 pr-ai-review-loop 工作流」→ 自动加载 `pr-ai-review-loop`，
按「三角色模型 → 待命 → push → 监听 CI/AI review → Judge 裁决 → 循环（≤3 轮）」执行。
也可在会话里输入 `/skills` 查看已发现的 skills。

## 与 Hermes 的差异（已处理）

1. **frontmatter**：Claude Code 只认 `name` / `description`（必填）与可选 `allowed-tools`；
   `metadata.hermes.*`、`related_skills`、`dependencies` 等扩展字段会被忽略（无害）。
   `dependencies` 仅由 MCP `install_skill` 使用，Claude Code 原生不安装依赖。
2. **工具名差异**：`ai-review-method` §2.2 的工具白名单已注明两套工具名
   （Hermes: read_file / grep / ast_grep / list_dir；Claude Code: Read / Grep / Glob / Bash），能力等价。
3. **skill_view**：Hermes 用 `skill_view` 手动加载关联 skill；Claude Code 中关联 skill 位于
   skills 目录自动发现，按需引用其内容即可（SKILL.md 内已注明）。
4. **方案 A 无对等命令**：Claude Code 没有 `skills tap add`；若想要"注册仓库即装"，
   可后续把本仓库做成 Claude plugin marketplace（`.claude-plugin/marketplace.json`），暂未实现。

## 验证清单

```bash
claude mcp list                    # 方案 C：看到 skills-hub
# 新开 Claude Code 会话后：
#   /skills                          # 应看到 pr-ai-review-loop 等 4 个 skills
#   问「列出可用 skills」            # 方案 C：MCP list_skills 返回 4 个
```
