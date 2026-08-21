#!/usr/bin/env bash
# 把 skills-hub 的 skills 安装到 Claude Code，并可选择注册 MCP 服务器。
# 与 Hermes 方案 B（复制）/ 方案 C（MCP）完全对等。
#
# 用法:
#   ./claude/install.sh                      # 安装到个人级 ~/.claude/skills
#   ./claude/install.sh project              # 安装到当前项目 .claude/skills
#   ./claude/install.sh user /custom/dir 0   # 自定义目录，不注册 MCP
#   FORCE=1 ./claude/install.sh              # 覆盖已存在的 skill
set -euo pipefail

SCOPE="${1:-user}"
TARGET_DIR="${2:-}"
REGISTER_MCP="${3:-1}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/skills"

if [[ ! -d "$SRC" ]]; then
  echo "错误: 未找到 skills 目录: $SRC" >&2
  exit 1
fi

if [[ -n "$TARGET_DIR" ]]; then
  TARGET="$TARGET_DIR"
elif [[ "$SCOPE" == "project" ]]; then
  TARGET="$(pwd)/.claude/skills"
else
  TARGET="$HOME/.claude/skills"
fi

mkdir -p "$TARGET"

echo ""
echo "=== skills 安装结果 → $TARGET ==="
installed=0
skipped=0
for skill_dir in "$SRC"/*/; do
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  name="$(basename "$skill_dir")"
  dest="$TARGET/$name"
  if [[ -e "$dest" && "${FORCE:-0}" != "1" ]]; then
    echo "  [skipped]   $name (已存在，用 FORCE=1 覆盖)"
    skipped=$((skipped + 1))
    continue
  fi
  rm -rf "$dest"
  cp -r "$skill_dir" "$dest"
  echo "  [installed] $name"
  installed=$((installed + 1))
done

if [[ "$REGISTER_MCP" == "1" ]]; then
  if ! command -v claude >/dev/null 2>&1; then
    echo "警告: 未找到 claude 命令（先安装 Claude Code）。skills 已复制，MCP 注册跳过。" >&2
  else
    MCP_SCRIPT="$REPO_DIR/mcp/mcp_server.py"
    echo ""
    echo "=== 注册 MCP: skills-hub → $MCP_SCRIPT ==="
    claude mcp remove skills-hub >/dev/null 2>&1 || true
    claude mcp add skills-hub --env "SKILLS_HUB_INSTALL_DIR=$TARGET" -- python "$MCP_SCRIPT"
  fi
fi

echo ""
echo "=== 验证 ==="
echo "  1. claude mcp list          # 应看到 skills-hub"
echo "  2. 重启 Claude Code 会话（skills 在启动时扫描）"
echo "  3. 提问「列出可用 skills」或直接说「执行 pr-ai-review-loop 工作流」"
