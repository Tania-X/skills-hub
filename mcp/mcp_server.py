#!/usr/bin/env python3
"""
mcp-server-skills-hub — 能力中心 MCP 服务器

把 skills-hub 仓库中的 skills 通过 MCP 协议暴露给任何 MCP 客户端。

特性：
- list_skills: 列出所有可用 skills（含描述）
- get_skill: 获取 skill 的完整 SKILL.md + 元信息
- install_skill: 安装到本地 skills 目录（Hermes / Claude Code，目录由 SKILLS_HUB_INSTALL_DIR 指定）
- refresh_cache: 重新同步仓库索引

安全：
- skill 名称经白名单校验（防路径穿越 / URL 注入）

数据来源（按优先级）：
1. 本地仓库副本（$SKILLS_HUB_LOCAL_REPO，若设置且存在）
2. GitHub API（$SKILLS_HUB_REPO，走代理或直连，环境变量控制）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 配置

REPO = os.environ.get("SKILLS_HUB_REPO", "Tania-X/skills-hub")
BRANCH = os.environ.get("SKILLS_HUB_BRANCH", "main")
LOCAL_REPO = os.environ.get("SKILLS_HUB_LOCAL_REPO", "")  # 本地克隆路径（可选）
CACHE_TTL = int(os.environ.get("SKILLS_HUB_CACHE_TTL", "300"))
PROXY = os.environ.get("SKILLS_HUB_PROXY", "")  # 如 http://127.0.0.1:7890（可选）
GITHUB_TOKEN = os.environ.get("SKILLS_HUB_TOKEN", os.environ.get("GITHUB_TOKEN", ""))


def default_install_dir() -> str:
    """Hermes skills 目录：$HERMES_HOME/skills，回退 ~/.hermes/skills"""
    hh = os.environ.get("HERMES_HOME", "")
    if hh:
        return str(Path(hh) / "skills")
    return str(Path.home() / ".hermes" / "skills")


INSTALL_DIR = os.environ.get("SKILLS_HUB_INSTALL_DIR", default_install_dir())

API_BASE = f"https://api.github.com/repos/{REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

_cache: dict[str, Any] = {
    "skills": None,              # 索引缓存（list_skills）
    "fetched_at": 0.0,
    "contents": {},              # 内容缓存（get_skill，按 name）
    "contents_fetched_at": {},   # 各条内容的缓存时间
}

# ---------------------------------------------------------------- 名称校验

# skill 名称白名单：字母/数字/点/下划线/连字符，且不能以 . 或 - 开头。
# 防止 install_skill / get_skill 传入 "../xxx" 之类的名称造成路径穿越或 URL 注入。
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)


def _validate_skill_name(name: str) -> None:
    """校验 skill 名称；非法时抛 RuntimeError（会被 MCP 工具转成 error JSON）。"""
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        raise RuntimeError(
            f"非法 skill 名称: {name!r}（仅允许字母、数字、点、下划线、连字符，且不以 . 或 - 开头）"
        )


# ---------------------------------------------------------------- 数据获取

def _gh_request(url: str, retries: int = 2) -> Any:
    """GitHub API 请求（可选代理/Token）。失败自动重试 retries 次，仍失败抛异常。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "mcp-server-skills-hub",
                "Accept": "application/vnd.github+json",
            })
            if GITHUB_TOKEN:
                req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
            opener = urllib.request.build_opener()
            if PROXY:
                proxy = urllib.request.ProxyHandler({
                    "http": PROXY,
                    "https": PROXY,
                })
                opener = urllib.request.build_opener(proxy)
            with opener.open(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < retries:
                import time as _time
                _time.sleep(2 * (attempt + 1))  # 2s, 4s 退避
    raise RuntimeError(f"GitHub API 请求失败(重试 {retries} 次): {last_exc}") from last_exc


def _local_skills() -> list[dict] | None:
    """从本地仓库副本读 skills 索引。"""
    if not LOCAL_REPO:
        return None
    skills_dir = Path(LOCAL_REPO) / "skills"
    if not skills_dir.is_dir():
        return None
    result = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
        result.append({
            "name": child.name,
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "source": "local",
        })
    return result or None


def _remote_skills() -> list[dict]:
    """从 GitHub API 拉 skills 目录。"""
    items = _gh_request(f"{API_BASE}/contents/skills?ref={BRANCH}")
    result = []
    for item in items:
        if item.get("type") != "dir":
            continue
        result.append({
            "name": item["name"],
            "description": "",
            "version": "",
            "source": "github",
        })
    return result


def _fetch_skill_meta(name: str) -> dict:
    """远程拉取单个 skill 的 SKILL.md 并解析 frontmatter。"""
    text = _gh_request(f"{API_BASE}/contents/skills/{name}/SKILL.md?ref={BRANCH}")
    import base64
    content = base64.b64decode(text["content"]).decode("utf-8", errors="replace")
    meta = _parse_frontmatter(content)
    return {"name": name, **meta}


def _parse_frontmatter(text: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter（极简版，不引第三方 YAML 依赖）。"""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 4)
    if end < 0:
        return meta
    block = text[4:end]
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def get_skills_index(force: bool = False) -> list[dict]:
    """获取 skills 索引（带缓存）。force=True 时同时清空内容缓存。"""
    now = time.time()
    if force:
        _cache["contents"].clear()
        _cache["contents_fetched_at"].clear()
    if not force and _cache["skills"] and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["skills"]

    skills = _local_skills()
    if skills is None:
        try:
            skills = _remote_skills()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"无法从仓库获取 skills 列表: {e}") from e

    _cache["skills"] = skills
    _cache["fetched_at"] = now
    return skills


def get_skill_content(name: str, force: bool = False) -> dict:
    """获取单个 skill 的完整内容（带 TTL 缓存；force=True 强制重新拉取并回写缓存）。"""
    _validate_skill_name(name)
    now = time.time()
    if not force:
        cached = _cache["contents"].get(name)
        if cached and (now - _cache["contents_fetched_at"].get(name, 0.0)) < CACHE_TTL:
            return cached
    # 1) 本地副本优先
    if LOCAL_REPO:
        p = Path(LOCAL_REPO) / "skills" / name / "SKILL.md"
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            meta = _parse_frontmatter(text)
            result = {"name": name, "content": text, "version": meta.get("version", ""), "source": "local"}
            _cache["contents"][name] = result
            _cache["contents_fetched_at"][name] = now
            return result
    # 2) GitHub 兜底
    try:
        import base64
        text = _gh_request(f"{API_BASE}/contents/skills/{name}/SKILL.md?ref={BRANCH}")
        content = base64.b64decode(text["content"]).decode("utf-8", errors="replace")
        meta = _parse_frontmatter(content)
        result = {"name": name, "content": content, "version": meta.get("version", ""), "source": "github"}
        _cache["contents"][name] = result
        _cache["contents_fetched_at"][name] = now
        return result
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"无法获取 skill '{name}': {e}") from e


# ---------------------------------------------------------------- 依赖解析

def _parse_deps(meta: dict) -> list[str]:
    """从 frontmatter 解析**硬依赖** skill 列表。

    仅顶层 `dependencies` 字段（列表或逗号分隔字符串）会被安装器递归安装；
    `related_skills` 只作关联提示（相关 ≠ 依赖），**不安装、缺失不阻塞**。
    """
    raw = meta.get("dependencies", "")
    deps: list[str] = []
    if isinstance(raw, list):
        deps = [str(d).strip() for d in raw]
    elif isinstance(raw, str) and raw.strip():
        deps = [d.strip().strip("'\"") for d in raw.replace("[", "").replace("]", "").split(",")]
    return [d for d in deps if d and d != "none"]


def _install_one(name: str, force: bool) -> dict:
    """安装单个 skill（无依赖），返回安装结果。force=True 保证安装时拉取最新内容。"""
    _validate_skill_name(name)
    data = get_skill_content(name, force=True)
    target = Path(INSTALL_DIR) / name
    if target.exists() and not force:
        return {
            "name": name,
            "status": "skipped",
            "reason": f"已存在于 {target}（force=True 覆盖）",
        }
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(data["content"], encoding="utf-8")
    return {
        "name": name,
        "status": "installed",
        "installed_to": str(target),
        "version": data.get("version", ""),
    }


def _install_with_deps(name: str, force: bool, with_deps: bool) -> dict:
    """安装 skill 及其依赖（BFS，带 visited 防循环）。"""
    installed: list[dict] = []
    failed: list[str] = []
    visited: set[str] = set()

    def visit(n: str) -> None:
        if n in visited:
            return
        visited.add(n)
        try:
            res = _install_one(n, force)
            installed.append(res)
            # 解析该 skill 的依赖（需重新拉元信息）
            if with_deps and res.get("status") in ("installed", "skipped"):
                try:
                    data = get_skill_content(n)
                    meta = _parse_frontmatter(data["content"])
                    for dep in _parse_deps(meta):
                        visit(dep)
                except RuntimeError:
                    pass  # 依赖解析失败不阻塞主安装
        except RuntimeError as e:
            failed.append(f"{n}: {e}")

    visit(name)
    return {
        "ok": not failed,
        "installed": installed,
        "failed": failed,
        "install_dir": str(Path(INSTALL_DIR)),
    }


# ---------------------------------------------------------------- MCP 工具

def _make_mcp():
    from fastmcp import FastMCP

    mcp = FastMCP("skills-hub", instructions=(
        "能力中心 MCP 服务器：管理可复用的 agent skills（Hermes / Claude Code 等）。"
        "可用工具：list_skills 列出 skills；get_skill 读取内容；"
        "install_skill 安装到本地 skills 目录（目录由 SKILLS_HUB_INSTALL_DIR 指定，"
        "Hermes 默认 $HERMES_HOME/skills，Claude Code 设为 ~/.claude/skills）。"
    ))

    @mcp.tool()
    def list_skills() -> str:
        """列出能力中心所有可用 skills 及其描述、版本。"""
        try:
            skills = get_skills_index()
        except RuntimeError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"skills": skills}, ensure_ascii=False)

    @mcp.tool()
    def get_skill(name: str) -> str:
        """获取指定 skill 的完整 SKILL.md 内容与元信息。

        Args:
            name: skill 名称，如 "pr-ai-review-loop"
        """
        try:
            return json.dumps(get_skill_content(name), ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def install_skill(name: str, force: bool = False, with_deps: bool = True) -> str:
        """安装 skill 到本地 skills 目录（目录由环境变量 SKILLS_HUB_INSTALL_DIR 指定：
        Hermes 默认 $HERMES_HOME/skills，Claude Code 设为 ~/.claude/skills 或项目 .claude/skills）。

        Args:
            name: skill 名称（仅字母/数字/点/下划线/连字符）
            force: 已存在时是否覆盖（默认 False）
            with_deps: 是否递归安装 frontmatter `dependencies` 声明的硬依赖（默认 True；
                       `related_skills` 仅提示、不安装）
        """
        try:
            result = _install_with_deps(name, force=force, with_deps=with_deps)
            return json.dumps(result, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def refresh_cache() -> str:
        """强制重新同步 skills 索引（本地副本或 GitHub）。"""
        try:
            skills = get_skills_index(force=True)
            return json.dumps({"ok": True, "count": len(skills), "skills": skills}, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    return mcp


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="skills-hub MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8910)
    args = parser.parse_args()

    mcp = _make_mcp()
    if args.transport == "http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
