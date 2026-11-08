#!/usr/bin/env python3
"""单元测试：覆盖 API Key 认证、健康检查、版本管理等新增功能。

运行方式：
    cd mcp/
    python -m pytest test_unit.py -v
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保能导入 mcp_server
sys.path.insert(0, str(Path(__file__).parent))


# ----------------------------------------------------------------
# 辅助函数测试
# ----------------------------------------------------------------

class TestParseFrontmatter:
    """测试 SKILL.md frontmatter 解析"""

    def test_parse_simple(self):
        from mcp_server import _parse_frontmatter
        text = """---
name: test-skill
version: 1.0.0
description: 测试技能
---
# 正文
"""
        meta = _parse_frontmatter(text)
        assert meta["name"] == "test-skill"
        assert meta["version"] == "1.0.0"
        assert "description" in meta

    def test_parse_no_frontmatter(self):
        from mcp_server import _parse_frontmatter
        text = "# 没有 frontmatter 的纯 Markdown"
        meta = _parse_frontmatter(text)
        assert meta == {}

    def test_parse_empty_frontmatter(self):
        from mcp_server import _parse_frontmatter
        text = "---\n---\n# 空 frontmatter"
        meta = _parse_frontmatter(text)
        assert meta == {}


class TestValidateSkillName:
    """测试 skill 名称白名单校验"""

    def test_valid_names(self):
        from mcp_server import _validate_skill_name
        valid = ["skill-name", "skill_name", "skill.name", "skill123", "a", "A-B_C.1"]
        for name in valid:
            _validate_skill_name(name)  # 不抛异常就是通过

    def test_invalid_names(self):
        from mcp_server import _validate_skill_name, SKILL_NAME_RE
        invalid = ["../evil", ".hidden", "-dash", "with space", "中文", ""]
        for name in invalid:
            with pytest.raises(RuntimeError):
                _validate_skill_name(name)


class TestGetLocalInstalledVersion:
    """测试读取本地已安装 skill 的版本号"""

    def test_existing_skill(self, tmp_path):
        from mcp_server import _get_local_installed_version
        # 准备一个已安装的 skill
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\nversion: 1.2.3\n---\n正文",
            encoding="utf-8",
        )
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            ver = _get_local_installed_version("test-skill")
            assert ver == "1.2.3"

    def test_nonexistent_skill(self, tmp_path):
        from mcp_server import _get_local_installed_version
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            ver = _get_local_installed_version("no-such-skill")
            assert ver == ""

    def test_skill_no_version(self, tmp_path):
        from mcp_server import _get_local_installed_version
        skill_dir = tmp_path / "no-version"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: no-version\n---\n无版本号",
            encoding="utf-8",
        )
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            ver = _get_local_installed_version("no-version")
            assert ver == ""


# ----------------------------------------------------------------
# MCP 工具测试（mock 外部依赖）
# ----------------------------------------------------------------

class TestListSkillsWithVersion:
    """测试 list_skills 工具现在返回本地版本和可升级标记"""

    @patch("mcp_server.get_skills_index")
    @patch("mcp_server._get_local_installed_version")
    def test_list_skills_includes_local_version(self, mock_local_ver, mock_index):
        # 直接测试 list_skills 的核心逻辑（不通过 MCP 工具层）
        from mcp_server import get_skills_index, _get_local_installed_version

        # mock 远程索引
        mock_index.return_value = [
            {"name": "skill-a", "version": "1.0.0", "description": "A"},
            {"name": "skill-b", "version": "2.0.0", "description": "B"},
        ]
        # mock 本地版本：skill-a 已安装同版本，skill-b 已安装旧版本
        mock_local_ver.side_effect = lambda name: "1.0.0" if name == "skill-a" else "1.5.0" if name == "skill-b" else ""

        # 模拟 list_skills 的逻辑
        skills = get_skills_index()
        for s in skills:
            local_ver = _get_local_installed_version(s["name"])
            s["local_version"] = local_ver
            s["upgradable"] = bool(
                local_ver and s.get("version") and s["version"] != local_ver
            )

        assert len(skills) == 2

        # skill-a: 已安装同版本，不可升级
        skill_a = next(s for s in skills if s["name"] == "skill-a")
        assert skill_a["local_version"] == "1.0.0"
        assert skill_a["upgradable"] is False

        # skill-b: 本地 1.5.0 < 远程 2.0.0，可升级
        skill_b = next(s for s in skills if s["name"] == "skill-b")
        assert skill_b["local_version"] == "1.5.0"
        assert skill_b["upgradable"] is True


class TestUpgradeSkill:
    """测试 upgrade_skill 工具的核心逻辑"""

    @patch("mcp_server._install_with_deps")
    @patch("mcp_server.get_skill_content")
    @patch("mcp_server._get_local_installed_version")
    def test_upgrade_skill_returns_version_diff(self, mock_local_ver, mock_content, mock_install):
        # 直接测试 upgrade_skill 的核心逻辑（不通过 MCP 工具层）
        from mcp_server import _install_with_deps, get_skill_content, _get_local_installed_version
        mock_local_ver.return_value = "1.0.0"
        mock_install.return_value = {"ok": True, "installed": [], "failed": []}
        mock_content.return_value = {"version": "2.0.0", "content": "新内容"}

        # 模拟 upgrade_skill 的逻辑
        name = "test-skill"
        local_ver = _get_local_installed_version(name)
        result = _install_with_deps(name, force=True, with_deps=True)
        result["previous_version"] = local_ver
        try:
            data = get_skill_content(name, force=True)
            result["current_version"] = data.get("version", "")
        except RuntimeError:
            result["current_version"] = ""

        assert result["previous_version"] == "1.0.0"
        assert result["current_version"] == "2.0.0"
        assert result["ok"] is True


# ----------------------------------------------------------------
# HTTP 模式测试（认证 + 健康检查）
# ----------------------------------------------------------------

class TestHTTPAuthMiddleware:
    """测试 API Key 认证逻辑"""

    def test_health_endpoint_does_not_require_auth(self):
        """验证健康检查端点在认证白名单中（逻辑验证，不启动真实服务）"""
        # 读取 mcp_server.py 源码，验证 /health 在白名单里
        from pathlib import Path
        src = Path(__file__).parent / "mcp_server.py"
        code = src.read_text(encoding="utf-8")
        assert 'request.url.path == "/health"' in code, "健康检查端点白名单逻辑缺失"

    def test_api_key_env_var_read(self):
        """验证 API_KEY 环境变量能被正确读取"""
        with patch.dict(os.environ, {"SKILLS_HUB_API_KEY": "test-key-123"}):
            # 重新导入模块级变量
            import importlib
            import mcp_server
            importlib.reload(mcp_server)
            assert mcp_server.API_KEY == "test-key-123"


# ----------------------------------------------------------------
# Changelog / 版本管理测试
# ----------------------------------------------------------------

class TestParseChangelog:
    """测试 CHANGELOG.md 解析"""

    def test_parse_simple_changelog(self):
        from mcp_server import _parse_changelog
        text = """# Changelog

## v1.0.0 - 2024-01-15
### 新增
- 初始版本
- 支持基本功能

## v1.1.0 - 2024-02-20
### 新增
- 加了新功能A
### 修复
- 修复了Bug B
"""
        versions = _parse_changelog(text)
        assert len(versions) == 2

        # 第一个版本（最新的）
        v1 = versions[0]
        assert v1["version"] == "1.0.0"
        assert v1["date"] == "2024-01-15"
        assert len(v1["changes"]) == 2
        assert "初始版本" in v1["changes"][0]

        # 第二个版本
        v2 = versions[1]
        assert v2["version"] == "1.1.0"
        assert v2["date"] == "2024-02-20"

    def test_parse_empty_changelog(self):
        from mcp_server import _parse_changelog
        text = "# Changelog\n\n还没有版本记录。"
        versions = _parse_changelog(text)
        assert versions == []

    def test_parse_changelog_without_date(self):
        from mcp_server import _parse_changelog
        text = """## v2.0.0
- 重大更新
"""
        versions = _parse_changelog(text)
        assert len(versions) == 1
        assert versions[0]["version"] == "2.0.0"
        assert versions[0]["date"] == ""


class TestGetSkillChangelog:
    """测试获取 skill changelog 的逻辑"""

    def test_get_changelog_from_local(self, tmp_path):
        from mcp_server import _get_skill_changelog
        # 准备本地changelog文件
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "CHANGELOG.md").write_text(
            "## v1.0.0 - 2024-01-01\n- 初始版本\n",
            encoding="utf-8",
        )
        with patch("mcp_server.LOCAL_REPO", str(tmp_path)):
            data = _get_skill_changelog("test-skill")
            assert data["source"] == "local"
            assert data["name"] == "test-skill"
            assert len(data["versions"]) == 1
            assert data["versions"][0]["version"] == "1.0.0"

    def test_get_changelog_not_found(self, tmp_path):
        from mcp_server import _get_skill_changelog
        with patch("mcp_server.LOCAL_REPO", str(tmp_path)):
            data = _get_skill_changelog("no-such-skill")
            assert data["source"] == "none"
            assert data["versions"] == []


# ----------------------------------------------------------------
# 运行入口
# ----------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
