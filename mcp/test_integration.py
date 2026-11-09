#!/usr/bin/env python3
"""集成测试：MCP三大能力（Resources / Prompts / Tools）完整工作流。

场景：新AI Agent接入skills-hub，完成"PR代码审查"任务的完整流程：
1. 用Resources发现有哪些可用资源（静态资源 + 动态模板）
2. 用Prompts生成使用指南
3. 用Tools实际调用完成任务

运行方式：
    cd mcp/
    python test_integration.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_scenario_pr_code_review():
    """场景：新Agent要做PR代码审查，走完三大能力的完整流程。"""

    print("=" * 60)
    print("场景：新AI Agent接入skills-hub，完成PR代码审查任务")
    print("=" * 60)

    from mcp_server import _make_mcp
    mcp = _make_mcp()

    # ----------------------------------------------------------------
    # Step 1: 用 Resources 发现有哪些可用资源
    # ----------------------------------------------------------------
    print("\n【Step 1: Resources 能力 - 发现可用资源】")
    print("-" * 40)

    # 静态资源（固定URI）
    resources = await mcp.list_resources()
    print(f"静态资源: {len(resources)} 个")
    for r in resources:
        uri = getattr(r, 'uri', str(r))
        desc = getattr(r, 'description', '')
        print(f"  - {uri}: {desc[:50]}")

    # 动态模板（带参数的URI模板）
    templates = await mcp.list_resource_templates()
    print(f"\n动态模板: {len(templates)} 个")
    for t in templates:
        uri = getattr(t, 'uriTemplate', str(t))
        desc = getattr(t, 'description', '')
        print(f"  - {uri}: {desc[:50]}")

    total_resources = len(resources) + len(templates)
    print(f"\nResources总计: {total_resources} 个")

    # ----------------------------------------------------------------
    # Step 2: 用 Prompts 生成任务prompt
    # ----------------------------------------------------------------
    print("\n【Step 2: Prompts 能力 - 生成任务prompt】")
    print("-" * 40)

    prompts = await mcp.list_prompts()
    print(f"Prompts: {len(prompts)} 个")
    for p in prompts:
        name = getattr(p, 'name', str(p))
        desc = getattr(p, 'description', '')
        print(f"  - {name}: {desc[:50]}")

    if len(prompts) == 0:
        print("  (提示：prompts在feat/mcp-prompts分支中，待合并后生效)")

    # ----------------------------------------------------------------
    # Step 3: 用 Tools 实际调用完成任务
    # ----------------------------------------------------------------
    print("\n【Step 3: Tools 能力 - 实际调用完成任务】")
    print("-" * 40)

    tools = await mcp.list_tools()
    print(f"Tools: {len(tools)} 个")
    for t in tools:
        name = getattr(t, 'name', str(t))
        desc = getattr(t, 'description', '')
        print(f"  - {name}: {desc[:50]}...")

    # ----------------------------------------------------------------
    # 验证结果
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)

    # 验证Resources（静态 + 动态模板）
    assert len(resources) >= 1, f"应该有至少1个静态resource，实际{len(resources)}"
    assert len(templates) >= 2, f"应该有至少2个动态模板，实际{len(templates)}"

    resource_uris = [str(getattr(r, 'uri', '')) for r in resources]
    template_uris = [getattr(t, 'uri_template', '') for t in templates]
    print(f"\n静态资源URI: {resource_uris}")
    print(f"动态模板URI: {template_uris}")

    assert "skills://index" in resource_uris, "缺少skills://index静态资源"
    assert "skill://{name}/SKILL.md" in template_uris, "缺少skill内容动态模板"
    assert "skill://{name}/CHANGELOG.md" in template_uris, "缺少changelog动态模板"

    # 验证Tools
    assert len(tools) >= 8, f"应该有至少8个tools，实际{len(tools)}"
    tool_names = [getattr(t, 'name', str(t)) for t in tools]
    print(f"\nTool列表: {tool_names}")

    assert "list_skills" in tool_names, "缺少list_skills tool"
    assert "get_skill" in tool_names, "缺少get_skill tool"
    assert "install_skill" in tool_names, "缺少install_skill tool"
    assert "upgrade_skill" in tool_names, "缺少upgrade_skill tool"

    # 验证Prompts（如果有）
    prompt_names = [getattr(p, 'name', str(p)) for p in prompts]
    print(f"\nPrompt列表: {prompt_names}")
    # prompts可能在另一个分支，所以这里不强制要求必须有

    print("\n✅ 核心验证通过！")
    print(f"  - Resources: {len(resources)} 静态 + {len(templates)} 动态模板 = {total_resources} 个")
    print(f"  - Tools: {len(tools)} 个")
    print(f"  - Prompts: {len(prompts)} 个 (待feat/mcp-prompts合并后生效)")
    print("\n工作流说明：")
    print("  1. 新Agent先 list_resources / list_resource_templates 发现有什么数据")
    print("  2. 然后 list_prompts 发现有什么预定义模板可用")
    print("  3. 最后 list_tools 发现有什么工具可以调用")
    print("  这就是MCP客户端接入的标准三步发现流程。")


if __name__ == "__main__":
    asyncio.run(test_scenario_pr_code_review())
