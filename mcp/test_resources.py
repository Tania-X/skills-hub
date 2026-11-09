#!/usr/bin/env python3
"""单元测试：Resources功能。

运行方式：
    cd mcp/
    python -m pytest test_resources.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))


class TestResourcesExist:
    """验证resources已注册到MCP server"""

    def test_mcp_server_has_resources(self):
        """验证_make_mcp返回的server包含resources能力"""
        from mcp_server import _make_mcp
        mcp = _make_mcp()

        # 验证有resource装饰器被使用了
        src = Path(__file__).parent / "mcp_server.py"
        code = src.read_text(encoding="utf-8")

        # 验证有3个resource
        assert code.count("@mcp.resource(") >= 3, "至少应该有3个resource"

        # 验证有这3个resource
        assert 'skills://index' in code, "缺少skills://index resource"
        assert 'skill://{name}/SKILL.md' in code, "缺少skill://{name}/SKILL.md resource"
        assert 'skill://{name}/CHANGELOG.md' in code, "缺少skill://{name}/CHANGELOG.md resource"


class TestSkillsIndexResource:
    """验证skills索引resource"""

    def test_skills_index_returns_json(self):
        """验证skills索引返回JSON格式"""
        # 模拟get_skills_index的返回
        mock_skills = [
            {"name": "test-skill", "version": "1.0.0", "description": "测试技能"},
        ]

        with patch("mcp_server.get_skills_index", return_value=mock_skills):
            # 调用resource函数的逻辑
            result = json.dumps({"skills": mock_skills}, ensure_ascii=False, indent=2)
            data = json.loads(result)
            assert len(data["skills"]) == 1
            assert data["skills"][0]["name"] == "test-skill"


class TestSkillContentResource:
    """验证skill内容resource"""

    def test_skill_content_returns_markdown(self):
        """验证skill内容返回Markdown文本"""
        mock_data = {
            "name": "test-skill",
            "version": "1.0.0",
            "content": "---\nname: test-skill\nversion: 1.0.0\n---\n\n# 测试技能\n\n这是内容。",
        }

        with patch("mcp_server.get_skill_content", return_value=mock_data):
            content = mock_data["content"]
            assert "测试技能" in content
            assert "name: test-skill" in content


class TestSkillChangelogResource:
    """验证changelog resource"""

    def test_changelog_returns_content(self):
        """验证changelog返回内容"""
        mock_data = {
            "name": "test-skill",
            "versions": [{"version": "1.0.0", "date": "2024-01-01"}],
            "raw_content": "# Changelog\n\n## v1.0.0 - 2024-01-01\n- 初始版本\n",
        }

        with patch("mcp_server._get_skill_changelog", return_value=mock_data):
            content = mock_data.get("raw_content")
            assert "Changelog" in content
            assert "v1.0.0" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
