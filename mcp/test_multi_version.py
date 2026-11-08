#!/usr/bin/env python3
"""单元测试：多版本共存功能。

运行方式：
    cd mcp/
    python -m pytest test_multi_version.py -v
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


class TestListInstalledVersions:
    """测试列出本地已安装版本"""

    def test_empty_install_dir(self, tmp_path):
        from mcp_server import _list_installed_versions
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            data = _list_installed_versions("test-skill")
            assert data["count"] == 0
            assert data["versions"] == []

    def test_multiple_versions_installed(self, tmp_path):
        from mcp_server import _list_installed_versions
        # 准备两个版本的目录
        skill_dir = tmp_path / "pr-ai-review-loop@3.0.0"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("content v3.0.0", encoding="utf-8")

        skill_dir2 = tmp_path / "pr-ai-review-loop@3.1.0-beta.1"
        skill_dir2.mkdir()
        (skill_dir2 / "SKILL.md").write_text("content v3.1.0-beta.1", encoding="utf-8")

        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            data = _list_installed_versions("pr-ai-review-loop")
            assert data["count"] == 2
            versions = [v["version"] for v in data["versions"]]
            assert "3.0.0" in versions
            assert "3.1.0-beta.1" in versions

    def test_no_matching_skill(self, tmp_path):
        from mcp_server import _list_installed_versions
        # 有其他skill的目录，但没有我们要找的
        other = tmp_path / "other-skill@1.0.0"
        other.mkdir()

        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            data = _list_installed_versions("test-skill")
            assert data["count"] == 0


class TestUseVersion:
    """测试切换默认版本"""

    def test_version_not_installed(self, tmp_path):
        from mcp_server import _use_version
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            with pytest.raises(RuntimeError, match="未安装"):
                _use_version("test-skill", "9.9.9")

    def test_version_installed_but_no_symlink_support(self, tmp_path):
        from mcp_server import _use_version
        # 准备已安装的版本
        skill_dir = tmp_path / "test-skill@1.0.0"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("content", encoding="utf-8")

        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            try:
                result = _use_version("test-skill", "1.0.0")
                assert result["switched_to"] == "1.0.0"
            except RuntimeError as e:
                # Windows 不支持软链接是正常的
                assert "软链接" in str(e) or "symlink" in str(e).lower()


class TestDowngradeSkill:
    """测试降级功能"""

    def test_no_versions_to_downgrade(self, tmp_path):
        from mcp_server import _list_installed_versions
        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            data = _list_installed_versions("test-skill")
            versions = [v["version"] for v in data.get("versions", [])]
            assert len(versions) < 2  # 没有可回退的版本

    def test_auto_downgrade_to_previous(self, tmp_path):
        from mcp_server import _list_installed_versions
        # 准备两个版本
        for v in ["1.0.0", "2.0.0"]:
            d = tmp_path / f"test-skill@{v}"
            d.mkdir()
            (d / "SKILL.md").write_text(f"content {v}", encoding="utf-8")

        with patch("mcp_server.INSTALL_DIR", str(tmp_path)):
            data = _list_installed_versions("test-skill")
            versions = [v["version"] for v in data["versions"]]
            # 倒数第二个就是上一个版本
            previous = versions[-2] if len(versions) >= 2 else ""
            assert previous == "1.0.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
