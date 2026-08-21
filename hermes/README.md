# Hermes 客户端（与 claude/ 目录结构完全对等）

每个 agent 一个平级目录（`hermes/` ↔ `claude/`，后续 `codex/`、`gemini/` 同理），
三件套同构：`install.ps1` + `install.sh` + `README.md`。

## 与 claude/ 结构对照

| | Hermes（本目录） | Claude Code（`../claude/`） |
|---|---|---|
| 方案 A：注册仓库即装 | `hermes skills tap add https://github.com/Tania-X/skills-hub` + `hermes skills install <name>` | 无原生对等命令（用安装脚本或 plugin marketplace，未实现） |
| 方案 B：复制安装 | `hermes/install.ps1` / `install.sh` → `$HERMES_HOME/skills` | `claude/install.ps1` / `install.sh` → `~/.claude/skills` |
| 方案 C：MCP | 手写 config.yaml（见下） | `claude mcp add skills-hub`（CLI 命令） |
| `install_skill` 写入位置 | `$HERMES_HOME/skills/`（MCP 默认） | `~/.claude/skills/`（`SKILLS_HUB_INSTALL_DIR` 指定） |

## 前置

- 已安装 Hermes Agent（`hermes --version`），Python 3.10+
- 方案 C 需要：`pip install "mcp>=1.26,<2" fastmcp`
  （⚠️ Hermes 0.19 兼容 `mcp==1.26.x`；mcp 2.x 改了 API 名，会报 `streamable_http is not available`）

## 方案 A：tap（原生命令，无需脚本）

```bash
hermes skills tap add https://github.com/Tania-X/skills-hub
hermes skills install pr-ai-review-loop
```

## 方案 B：复制安装（脚本，与 claude/ 对等）

```bash
# Windows（PowerShell）
powershell -ExecutionPolicy Bypass -File hermes/install.ps1                          # → $HERMES_HOME/skills
powershell -ExecutionPolicy Bypass -File hermes/install.ps1 -TargetDir "$env:HERMES_HOME\skills" -Force

# macOS / Linux
bash hermes/install.sh              # → $HERMES_HOME/skills（未设置则 ~/.hermes/skills）
FORCE=1 bash hermes/install.sh      # 覆盖已存在
```

## 方案 C：MCP（手写 config.yaml）

Hermes 没有 `hermes mcp add` CLI，需要编辑 Hermes 的 config.yaml：

```yaml
mcp_servers:
  skills_hub:
    command: "python"
    args: ["C:/Users/001/skills-hub/mcp/mcp_server.py"]
```

> `install_skill` 默认写入 `$HERMES_HOME/skills`（回退 `~/.hermes/skills`）；
> 需要改目标时设置环境变量 `SKILLS_HUB_INSTALL_DIR`。

## 使用 skills

重启 Hermes 会话后，在对话中描述任务即可自动加载对应 skill（Hermes 按 description 匹配），
例如「对当前 PR 跑 pr-ai-review-loop 工作流」；也可用 `hermes skills list` 确认安装状态。

## 相关

- 把 Hermes gateway（webhook）部署到云服务器的完整实录：
  `../skills/hermes-gateway-deploy/`（systemd + caddy + 双重认证，含 mcp==1.26.x 坑）
- MCP 服务器文档：`../mcp/README.md`
