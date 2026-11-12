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
API_KEY = os.environ.get("SKILLS_HUB_API_KEY", "")  # HTTP模式认证（可选，设置后客户端需带 Authorization: Bearer xxx）

# Redis（可选）：配置 SKILLS_HUB_REDIS_URL 后启用分布式缓存 + 限流计数；
# 未配置 / 连接失败时自动降级到进程内内存，服务不可用性不受影响。
REDIS_URL = os.environ.get("SKILLS_HUB_REDIS_URL", "")
# 限流：每窗口允许的请求数与窗口秒数（按 API Key 计数）
RATE_LIMIT = int(os.environ.get("SKILLS_HUB_RATE_LIMIT", "60"))
RATE_WINDOW = int(os.environ.get("SKILLS_HUB_RATE_WINDOW", "60"))


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
    "changelogs": {},            # changelog 缓存（按 name）
    "changelogs_fetched_at": {},
}

# ---------------------------------------------------------------- Redis 客户端 / 缓存降级 / 限流

# redis-py 为可选依赖：未安装时整段降级到内存，不影响服务启动。
try:
    import redis as _redis_lib  # type: ignore
    _REDIS_IMPORTABLE = True
except ImportError:  # pragma: no cover - 依赖缺失场景
    _redis_lib = None
    _REDIS_IMPORTABLE = False

_redis_client: Any = None
_redis_state = "pending"  # pending / ok / disabled
# 内存限流兜底计数：identity -> {window_index: count}
_rate_memory: dict[str, dict[int, int]] = {}

# 缓存 key 前缀（便于 refresh 时按前缀批量清理）
KEY_INDEX = "skills:index"
CONTENT_PREFIX = "skill:content:"
CHANGELOG_PREFIX = "skill:changelog:"
RATE_PREFIX = "rate:"


def _content_key(name: str) -> str:
    return f"{CONTENT_PREFIX}{name}"


def _changelog_key(name: str) -> str:
    return f"{CHANGELOG_PREFIX}{name}"


def _get_redis() -> Any:
    """惰性获取 Redis 客户端。

    - 未配置 REDIS_URL / 包未安装 / 连接失败 -> 返回 None（降级内存）；
    - 连接成功后复用单例；任何一次探测失败都记为 disabled，避免每次请求都重试拖慢响应。
    """
    global _redis_client, _redis_state
    if not REDIS_URL or not _REDIS_IMPORTABLE:
        _redis_state = "disabled"
        return None
    if _redis_state == "disabled":
        return None
    if _redis_state == "ok":
        return _redis_client
    try:
        client = _redis_lib.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            protocol=2,  # Redis 5.x 不支持 RESP3 的 HELLO 握手
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        _redis_client = client
        _redis_state = "ok"
        return client
    except Exception:  # noqa: BLE001
        _redis_client = None
        _redis_state = "disabled"
        return None


def _redis_get(key: str) -> str | None:
    """读 Redis；未连接或异常返回 None（调用方回退内存）。"""
    client = _get_redis()
    if client is None:
        return None
    try:
        return client.get(key)
    except Exception:  # noqa: BLE001
        return None


def _redis_set(key: str, value: str, ttl: int) -> None:
    """写 Redis 带 TTL；异常静默忽略（缓存失败不影响主流程）。"""
    client = _get_redis()
    if client is None:
        return
    try:
        client.set(key, value, ex=ttl)
    except Exception:  # noqa: BLE001
        pass


def _redis_delete(key: str) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:  # noqa: BLE001
        pass


def _redis_flush_prefix(prefix: str) -> None:
    """按前缀删除 Redis 中的缓存键（refresh_cache 用）。"""
    client = _get_redis()
    if client is None:
        return
    try:
        for k in client.scan_iter(match=f"{prefix}*"):
            client.delete(k)
    except Exception:  # noqa: BLE001
        pass


def check_rate_limit(identity: str) -> dict:
    """固定窗口限流：按 identity（API Key 或匿名标识）在窗口内计数。

    优先 Redis INCR + EXPIRE 做分布式计数；Redis 不可用时降级进程内内存计数器。
    返回 {"allowed", "count", "limit", "retry_after", "backend"}。
    """
    window = int(time.time() // RATE_WINDOW)
    client = _get_redis()
    if client is not None:
        try:
            key = f"{RATE_PREFIX}{identity}:{window}"
            count = client.incr(key)
            if count == 1:
                client.expire(key, RATE_WINDOW)
            allowed = count <= RATE_LIMIT
            return {
                "allowed": allowed,
                "count": int(count),
                "limit": RATE_LIMIT,
                "retry_after": RATE_WINDOW if not allowed else 0,
                "backend": "redis",
            }
        except Exception:  # noqa: BLE001 - Redis 异常时降级内存
            pass

    # 内存兜底：清理上一窗口，避免字典无限增长
    bucket = _rate_memory.setdefault(identity, {})
    bucket.pop(window - 1, None)
    count = bucket.get(window, 0) + 1
    bucket[window] = count
    allowed = count <= RATE_LIMIT
    return {
        "allowed": allowed,
        "count": count,
        "limit": RATE_LIMIT,
        "retry_after": RATE_WINDOW if not allowed else 0,
        "backend": "memory",
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


def _parse_changelog(text: str) -> list[dict]:
    """解析 CHANGELOG.md，返回版本历史列表（按时间倒序）。

    格式约定：
    ## v1.2.3 - 2024-01-15
    ### 新增
    - xxx
    ### 修复
    - yyy
    """
    versions: list[dict] = []
    current: dict | None = None

    for line in text.splitlines():
        line = line.strip()
        # 匹配版本标题：## v1.2.3 - 2024-01-15
        if line.startswith("## "):
            if current:
                versions.append(current)
            # 解析版本号和日期
            header = line[3:].strip()
            parts = header.split(" - ", 1)
            version = parts[0].strip().lstrip("vV")
            date = parts[1].strip() if len(parts) > 1 else ""
            current = {"version": version, "date": date, "changes": []}
        # 匹配变更条目：- xxx
        elif current and line.startswith("- "):
            current["changes"].append(line[2:].strip())

    if current:
        versions.append(current)

    return versions


def _get_skill_changelog(name: str) -> dict:
    """获取某个 skill 的 CHANGELOG.md 内容和解析后的版本历史（带 TTL 缓存）。"""
    _validate_skill_name(name)
    now = time.time()
    key = _changelog_key(name)

    # 1) Redis 优先
    raw = _redis_get(key)
    if raw is not None:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            pass

    # 2) 内存兜底
    cached = _cache["changelogs"].get(name)
    if cached and (now - _cache["changelogs_fetched_at"].get(name, 0.0)) < CACHE_TTL:
        return cached

    # 3) 本地副本优先
    if LOCAL_REPO:
        p = Path(LOCAL_REPO) / "skills" / name / "CHANGELOG.md"
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            result = {
                "name": name,
                "content": text,
                "versions": _parse_changelog(text),
                "source": "local",
            }
            _cache["changelogs"][name] = result
            _cache["changelogs_fetched_at"][name] = now
            _redis_set(key, json.dumps(result, ensure_ascii=False), CACHE_TTL)
            return result

    # 4) GitHub 兜底
    try:
        import base64
        text = _gh_request(f"{API_BASE}/contents/skills/{name}/CHANGELOG.md?ref={BRANCH}")
        content = base64.b64decode(text["content"]).decode("utf-8", errors="replace")
        result = {
            "name": name,
            "content": content,
            "versions": _parse_changelog(content),
            "source": "github",
        }
        _cache["changelogs"][name] = result
        _cache["changelogs_fetched_at"][name] = now
        _redis_set(key, json.dumps(result, ensure_ascii=False), CACHE_TTL)
        return result
    except Exception as e:  # noqa: BLE001
        return {
            "name": name,
            "content": "",
            "versions": [],
            "source": "none",
            "message": f"该 skill 没有 CHANGELOG.md: {e}",
        }


def get_skills_index(force: bool = False) -> list[dict]:
    """获取 skills 索引（带缓存）。force=True 时同时清空内容缓存与 Redis 缓存。

    缓存顺序：Redis -> 进程内内存 -> 本地副本 / GitHub 重新拉取。
    """
    now = time.time()
    if force:
        _cache["contents"].clear()
        _cache["contents_fetched_at"].clear()
        _cache["changelogs"].clear()
        _cache["changelogs_fetched_at"].clear()
        _redis_delete(KEY_INDEX)
        _redis_flush_prefix(CONTENT_PREFIX)
        _redis_flush_prefix(CHANGELOG_PREFIX)

    # 1) Redis 优先
    if not force:
        raw = _redis_get(KEY_INDEX)
        if raw is not None:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                pass  # 序列化异常则回退内存 / 重新拉取

    # 2) 内存兜底
    if not force and _cache["skills"] and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["skills"]

    # 3) 本地副本优先，GitHub 兜底
    skills = _local_skills()
    if skills is None:
        try:
            skills = _remote_skills()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"无法从仓库获取 skills 列表: {e}") from e

    _cache["skills"] = skills
    _cache["fetched_at"] = now
    _redis_set(KEY_INDEX, json.dumps(skills, ensure_ascii=False), CACHE_TTL)
    return skills


def get_skill_content(name: str, force: bool = False) -> dict:
    """获取单个 skill 的完整内容（带 TTL 缓存；force=True 强制重新拉取并回写缓存）。

    缓存顺序：Redis -> 进程内内存 -> 本地副本 / GitHub 重新拉取。
    """
    _validate_skill_name(name)
    now = time.time()
    key = _content_key(name)

    # 1) Redis 优先
    if not force:
        raw = _redis_get(key)
        if raw is not None:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                pass

    # 2) 内存兜底
    if not force:
        cached = _cache["contents"].get(name)
        if cached and (now - _cache["contents_fetched_at"].get(name, 0.0)) < CACHE_TTL:
            return cached

    # 3) 本地副本优先
    if LOCAL_REPO:
        p = Path(LOCAL_REPO) / "skills" / name / "SKILL.md"
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            meta = _parse_frontmatter(text)
            result = {"name": name, "content": text, "version": meta.get("version", ""), "source": "local"}
            _cache["contents"][name] = result
            _cache["contents_fetched_at"][name] = now
            _redis_set(key, json.dumps(result, ensure_ascii=False), CACHE_TTL)
            return result
    # 4) GitHub 兜底
    try:
        import base64
        text = _gh_request(f"{API_BASE}/contents/skills/{name}/SKILL.md?ref={BRANCH}")
        content = base64.b64decode(text["content"]).decode("utf-8", errors="replace")
        meta = _parse_frontmatter(content)
        result = {"name": name, "content": content, "version": meta.get("version", ""), "source": "github"}
        _cache["contents"][name] = result
        _cache["contents_fetched_at"][name] = now
        _redis_set(key, json.dumps(result, ensure_ascii=False), CACHE_TTL)
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
    """安装单个 skill（无依赖），返回安装结果。force=True 保证安装时拉取最新内容。

    多版本共存模式：安装到 <name>@<version>/ 目录，软链接指向默认版本。
    """
    _validate_skill_name(name)
    data = get_skill_content(name, force=True)
    version = data.get("version", "latest")
    versioned_dir_name = f"{name}@{version}"

    target = Path(INSTALL_DIR) / versioned_dir_name
    if target.exists() and not force:
        return {
            "name": name,
            "status": "skipped",
            "reason": f"已存在于 {target}（force=True 覆盖）",
            "version": version,
        }
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(data["content"], encoding="utf-8")

    # 创建/更新软链接指向默认版本
    link_path = Path(INSTALL_DIR) / name
    try:
        if link_path.is_symlink() or link_path.exists():
            if link_path.is_symlink():
                link_path.unlink()
            elif link_path.is_dir():
                # 旧格式（无版本号目录），备份一下
                import shutil
                backup = link_path.parent / f"{name}.legacy"
                if not backup.exists():
                    shutil.move(str(link_path), str(backup))
        # Windows 需要管理员权限或开发者模式，失败就跳过
        link_path.symlink_to(versioned_dir_name, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows 不支持软链接，跳过（不影响安装）
        pass

    return {
        "name": name,
        "status": "installed",
        "installed_to": str(target),
        "version": version,
    }


def _list_installed_versions(name: str) -> list[dict]:
    """列出本地已安装的某个skill的所有版本。"""
    _validate_skill_name(name)
    install_dir = Path(INSTALL_DIR)
    if not install_dir.is_dir():
        return []

    versions = []
    for child in sorted(install_dir.iterdir()):
        # 匹配 <name>@<version> 格式
        if child.is_dir() and child.name.startswith(f"{name}@"):
            version = child.name[len(name) + 1:]
            skill_md = child / "SKILL.md"
            has_content = skill_md.is_file()
            versions.append({
                "version": version,
                "path": str(child),
                "installed": has_content,
            })

    # 检查默认软链接指向哪个版本
    link_path = install_dir / name
    current = ""
    if link_path.is_symlink():
        current = link_path.resolve().name[len(name) + 1:] if link_path.resolve().name.startswith(f"{name}@") else link_path.resolve().name

    return {
        "name": name,
        "current_default": current,
        "versions": versions,
        "count": len(versions),
    }


def _use_version(name: str, version: str) -> dict:
    """切换默认使用的版本（更新软链接）。"""
    _validate_skill_name(name)
    versioned_dir_name = f"{name}@{version}"
    target = Path(INSTALL_DIR) / versioned_dir_name
    if not target.is_dir():
        raise RuntimeError(f"版本 {version} 未安装，已安装的版本用 list_installed_versions 查看")

    link_path = Path(INSTALL_DIR) / name
    try:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(versioned_dir_name, target_is_directory=True)
    except (OSError, NotImplementedError):
        raise RuntimeError("Windows 不支持软链接，请手动切换目录")

    return {
        "name": name,
        "switched_to": version,
        "path": str(target),
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

def _get_local_installed_version(name: str) -> str:
    """读取本地已安装 skill 的版本号（从 SKILL.md frontmatter 解析）。"""
    target = Path(INSTALL_DIR) / name / "SKILL.md"
    if not target.is_file():
        return ""
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        meta = _parse_frontmatter(text)
        return meta.get("version", "")
    except Exception:
        return ""


def _make_mcp():
    from fastmcp import FastMCP

    mcp = FastMCP("skills-hub", instructions=(
        "能力中心 MCP 服务器：管理可复用的 agent skills（Hermes / Claude Code 等）。"
        "支持多版本共存：同一个skill可以安装多个版本，随时切换。"
        "MCP三大核心能力全部实现：Tools（工具调用）、Prompts（消息模板）、Resources（数据资源）。"
        "可用工具：list_skills 列出 skills；get_skill 读取内容；"
        "get_skill_changelog 查看版本历史；list_skill_versions 列出所有版本；"
        "list_installed_versions 查看本地已安装版本；use_version 切换默认版本；"
        "install_skill 安装；upgrade_skill 升级；downgrade_skill 降级；"
        "refresh_cache 重新同步索引。"
        "可用Prompt模板：code_review（代码审查）、pr_description（PR描述）、skill_usage_guide（技能使用指南）。"
        "可用Resources：skills://index（技能索引）、skill://{name}/SKILL.md（技能内容）、skill://{name}/CHANGELOG.md（版本历史）。"
    ))

    @mcp.tool()
    def list_skills() -> str:
        """列出能力中心所有可用 skills 及其描述、远程版本、本地已安装版本。"""
        try:
            skills = get_skills_index()
            # 补充本地已安装版本
            for s in skills:
                local_ver = _get_local_installed_version(s["name"])
                s["local_version"] = local_ver
                s["upgradable"] = bool(
                    local_ver and s.get("version") and s["version"] != local_ver
                )
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

    @mcp.tool()
    def upgrade_skill(name: str, with_deps: bool = True) -> str:
        """升级已安装的 skill 到最新版本（强制重新拉取并覆盖本地）。

        Args:
            name: skill 名称
            with_deps: 是否同时升级依赖（默认 True）
        """
        try:
            local_ver = _get_local_installed_version(name)
            result = _install_with_deps(name, force=True, with_deps=with_deps)
            result["previous_version"] = local_ver
            result["current_version"] = ""
            # 获取最新版本号
            try:
                data = get_skill_content(name, force=True)
                result["current_version"] = data.get("version", "")
            except RuntimeError:
                pass
            return json.dumps(result, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_skill_changelog(name: str) -> str:
        """获取某个 skill 的 CHANGELOG.md 内容和解析后的版本历史。

        Args:
            name: skill 名称
        """
        try:
            data = _get_skill_changelog(name)
            return json.dumps(data, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def list_skill_versions(name: str) -> str:
        """列出某个 skill 的所有历史版本（从 CHANGELOG.md 解析）。

        Args:
            name: skill 名称
        """
        try:
            data = _get_skill_changelog(name)
            versions = data.get("versions", [])
            return json.dumps({
                "name": name,
                "count": len(versions),
                "versions": versions,
                "current_installed": _get_local_installed_version(name),
            }, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def list_installed_versions(name: str) -> str:
        """列出本地已安装的某个skill的所有版本（多版本共存）。

        Args:
            name: skill 名称
        """
        try:
            data = _list_installed_versions(name)
            return json.dumps(data, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def use_version(name: str, version: str) -> str:
        """切换默认使用的版本（更新软链接指向指定版本）。

        Args:
            name: skill 名称
            version: 要切换到的版本号，如 "3.0.0"
        """
        try:
            data = _use_version(name, version)
            return json.dumps(data, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def downgrade_skill(name: str, version: str = "") -> str:
        """降级已安装的 skill 到指定版本。

        Args:
            name: skill 名称
            version: 要降级到的版本号（为空则回退到上一个稳定版）
        """
        try:
            if not version:
                # 自动回退到上一个版本（按版本号排序，取倒数第二个）
                installed = _list_installed_versions(name)
                versions = [v["version"] for v in installed.get("versions", [])]
                if len(versions) < 2:
                    return json.dumps({"error": "没有可回退的旧版本"})
                version = versions[-2]  # 倒数第二个就是上一个版本

            result = _use_version(name, version)
            result["action"] = "downgrade"
            return json.dumps(result, ensure_ascii=False)
        except RuntimeError as e:
            return json.dumps({"error": str(e)})

    # ----------------------------------------------------------------
    # Prompts（MCP标准三大能力之一：预定义消息模板）
    # ----------------------------------------------------------------

    @mcp.prompt()
    def code_review(code_snippet: str, focus_area: str = "全部") -> str:
        """生成代码审查prompt模板。

        Args:
            code_snippet: 要审查的代码片段
            focus_area: 审查重点（全部/性能/安全/可读性/错误处理）
        """
        focus_map = {
            "全部": "全面审查：性能、安全、可读性、错误处理、边界情况",
            "性能": "重点关注：时间复杂度、空间复杂度、I/O效率、缓存使用",
            "安全": "重点关注：SQL注入、XSS、路径穿越、敏感信息泄露、权限校验",
            "可读性": "重点关注：命名规范、代码结构、注释完整性、函数长度",
            "错误处理": "重点关注：异常捕获边界、错误信息完整性、资源释放、边界条件",
        }
        focus_text = focus_map.get(focus_area, focus_area)

        return f"""请作为资深工程师，对以下代码进行代码审查。

审查重点：{focus_text}

代码片段：
```
{code_snippet}
```

请按以下格式输出审查结果：
1. 严重问题（必须修复）
2. 建议改进（推荐优化）
3. 亮点（写得好的地方）
"""

    @mcp.prompt()
    def pr_description(change_summary: str, test_coverage: str = "已覆盖核心场景") -> str:
        """生成PR描述prompt模板。

        Args:
            change_summary: 改动概述（做了什么）
            test_coverage: 测试覆盖情况
        """
        return f"""请根据以下改动信息，生成一个专业的Pull Request描述。

改动概述：
{change_summary}

测试覆盖：
{test_coverage}

请按以下结构生成：
## 改动说明
（解决了什么问题，为什么要改）

## 主要变更
（列出关键改动点）

## 测试验证
（测试了什么，怎么验证的）

## 影响范围
（可能影响哪些功能，有没有 breaking change）
"""

    @mcp.prompt()
    def skill_usage_guide(skill_name: str, task_description: str) -> str:
        """生成技能使用指南prompt模板，告诉LLM怎么使用某个skill。

        Args:
            skill_name: 技能名称（如 pr-ai-review-loop）
            task_description: 你要完成的任务描述
        """
        return f"""我需要使用技能 "{skill_name}" 来完成以下任务：

任务描述：
{task_description}

请按以下步骤操作：
1. 先调用 list_skills 确认技能存在和当前版本
2. 调用 get_skill 读取技能完整内容
3. 按照技能文档的指引完成任务
4. 如果遇到问题，调用 get_skill_changelog 查看版本历史和已知问题

请开始。
"""

    # ----------------------------------------------------------------
    # Resources（MCP标准三大能力之一：暴露数据给客户端）
    # ----------------------------------------------------------------

    @mcp.resource("skills://index")
    def skills_index() -> str:
        """所有可用skills的索引列表（名称、描述、版本）。"""
        try:
            skills = get_skills_index()
            return json.dumps({"skills": skills}, ensure_ascii=False, indent=2)
        except RuntimeError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.resource("skill://{name}/SKILL.md")
    def skill_content(name: str) -> str:
        """某个skill的SKILL.md完整内容。

        URI参数：name - skill名称（如 pr-ai-review-loop）
        """
        try:
            data = get_skill_content(name)
            return data["content"]
        except RuntimeError as e:
            return f"Error: {e}"

    @mcp.resource("skill://{name}/CHANGELOG.md")
    def skill_changelog(name: str) -> str:
        """某个skill的CHANGELOG.md内容。

        URI参数：name - skill名称
        """
        try:
            data = _get_skill_changelog(name)
            if data.get("raw_content"):
                return data["raw_content"]
            return json.dumps(data, ensure_ascii=False, indent=2)
        except RuntimeError as e:
            return f"Error: {e}"

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
        # HTTP 模式：加认证中间件 + 健康检查端点
        import asyncio
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route, Mount
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request

        # API Key 认证 + 限流中间件
        class APIKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                # 健康检查端点既不认证也不限流
                if request.url.path == "/health":
                    return await call_next(request)

                # ---- 认证 ----
                identity = "anonymous"
                if API_KEY:
                    auth = request.headers.get("authorization", "")
                    if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
                        return JSONResponse(
                            {"error": "unauthorized", "detail": "Invalid or missing API key"},
                            status_code=401,
                        )
                    identity = auth[7:]  # 通过认证后，按 API Key 作为限流身份
                else:
                    # 未配置 API_KEY（单租户/内网模式）：用可选的租户头标识，否则匿名
                    identity = request.headers.get("x-tenant-id", "anonymous")

                # ---- 限流（按身份固定窗口；Redis 不可用时自动降级内存计数）----
                limit = check_rate_limit(identity)
                if not limit["allowed"]:
                    return JSONResponse(
                        {
                            "error": "rate_limit_exceeded",
                            "detail": f"超过限流阈值：每 {RATE_WINDOW}s 最多 {RATE_LIMIT} 次",
                            "count": limit["count"],
                            "limit": limit["limit"],
                            "backend": limit["backend"],
                        },
                        status_code=429,
                        headers={"Retry-After": str(limit["retry_after"])},
                    )

                return await call_next(request)

        # 健康检查端点
        async def health_endpoint(request: Request):
            return JSONResponse({
                "status": "ok",
                "service": "skills-hub-mcp",
                "auth_enabled": bool(API_KEY),
                "repo": REPO,
                "branch": BRANCH,
                "redis_configured": bool(REDIS_URL),
                "rate_limit": RATE_LIMIT,
                "rate_window": RATE_WINDOW,
            })

        # 获取 MCP 的 ASGI 应用
        mcp_app = mcp.http_app(transport="streamable-http")

        # 组合 Starlette 应用（注意：必须传入 mcp_app.lifespan）
        app = Starlette(
            routes=[
                Route("/health", health_endpoint),
                Mount("/", app=mcp_app),
            ],
            lifespan=mcp_app.lifespan,
        )
        app.add_middleware(APIKeyMiddleware)

        # 启动服务
        import uvicorn
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
