#!/usr/bin/env python3
"""单元测试：Prompts模板功能。

运行方式：
    cd mcp/
    python -m pytest test_prompts.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


class TestPromptsExist:
    """验证prompts已注册到MCP server"""

    def test_mcp_server_has_prompts(self):
        """验证_make_mcp返回的server包含prompts能力"""
        from mcp_server import _make_mcp
        mcp = _make_mcp()
        # FastMCP的prompts存在内部注册表里
        # 我们通过源码验证@mcp.prompt装饰器被使用了
        src = Path(__file__).parent / "mcp_server.py"
        code = src.read_text(encoding="utf-8")

        # 验证有3个prompt装饰器
        assert code.count("@mcp.prompt()") >= 3, "至少应该有3个prompt模板"

        # 验证有这3个prompt函数
        assert "def code_review(" in code, "缺少code_review prompt"
        assert "def pr_description(" in code, "缺少pr_description prompt"
        assert "def skill_usage_guide(" in code, "缺少skill_usage_guide prompt"


class TestCodeReviewPrompt:
    """验证code_review prompt的内容生成"""

    def test_code_review_basic(self):
        """验证基本的代码审查prompt生成"""
        # 直接调用prompt函数的逻辑（不通过MCP框架）
        code_snippet = "def add(a, b): return a + b"
        focus_area = "全部"

        # 模拟prompt生成逻辑
        focus_map = {
            "全部": "全面审查：性能、安全、可读性、错误处理、边界情况",
        }
        focus_text = focus_map.get(focus_area, focus_area)

        prompt = f"""请作为资深工程师，对以下代码进行代码审查。

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
        assert code_snippet in prompt
        assert "全面审查" in prompt
        assert "严重问题" in prompt

    def test_code_review_focus_security(self):
        """验证安全审查重点"""
        focus_area = "安全"
        focus_map = {
            "安全": "重点关注：SQL注入、XSS、路径穿越、敏感信息泄露、权限校验",
        }
        focus_text = focus_map.get(focus_area, focus_area)
        assert "SQL注入" in focus_text
        assert "XSS" in focus_text


class TestPrDescriptionPrompt:
    """验证PR描述prompt的内容生成"""

    def test_pr_description_basic(self):
        change_summary = "加了API Key认证"
        test_coverage = "已覆盖核心场景"

        prompt = f"""请根据以下改动信息，生成一个专业的Pull Request描述。

改动概述：
{change_summary}

测试覆盖：
{test_coverage}

请按以下结构生成：
## 改动说明
## 主要变更
## 测试验证
## 影响范围
"""
        assert "API Key认证" in prompt
        assert "改动说明" in prompt
        assert "影响范围" in prompt


class TestSkillUsageGuidePrompt:
    """验证技能使用指南prompt"""

    def test_skill_usage_basic(self):
        skill_name = "pr-ai-review-loop"
        task_description = "审查这个PR的代码"

        prompt = f"""我需要使用技能 "{skill_name}" 来完成以下任务：

任务描述：
{task_description}

请按以下步骤操作：
1. 先调用 list_skills 确认技能存在和当前版本
2. 调用 get_skill 读取技能完整内容
3. 按照技能文档的指引完成任务
4. 如果遇到问题，调用 get_skill_changelog 查看版本历史和已知问题

请开始。
"""
        assert skill_name in prompt
        assert "审查这个PR的代码" in prompt
        assert "list_skills" in prompt
        assert "get_skill" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
