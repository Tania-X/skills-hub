#!/usr/bin/env bash
# 把 skills-hub 的 skills 安装到 Hermes，与 claude/（Claude Code 客户端）结构完全对等。
# 实现方案 B（复制）：复制 skills/* 到 $HERMES_HOME/skills（未设置时回退 ~/.hermes/skills）。
#
# 用法:
#   ./hermes/install.sh                        # 安装到 $HERMES_HOME/skills
#   ./hermes/install.sh /custom/skills-dir     # 指定目录
#   FORCE=1 ./hermes/install.sh                # 覆盖已存在的 skill
set -euo pipefail

TARGET_DIR="${1:-}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/skills"

if [[ ! -d "$SRC" ]]; then
  echo "错误: 未找到 skills 目录: $SRC" >&2
  exit 1
fi

if [[ -n "$TARGET_DIR" ]]; then
  TARGET="$TARGET_DIR"
elif [[ -n "${HERMES_HOME:-}" ]]; then
  TARGET="$HERMES_HOME/skills"
else
  TARGET="$HOME/.hermes/skills"
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

echo ""
echo "=== 验证 ==="
echo "  1. hermes skills list          # 应看到 4 个 enabled skills"
echo "  2. 重启 Hermes 会话后，在对话中描述任务即可自动加载对应 skill"
echo "  3. 方案 A（tap）/ 方案 C（MCP config）见 hermes/README.md"
