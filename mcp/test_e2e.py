#!/usr/bin/env python3
"""端到端测试：以 MCP 客户端身份连接 stdio server，调用全部工具。"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_server.py"))
    params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
        env={**os.environ},  # 继承环境变量（LOCAL_REPO / INSTALL_DIR / PROXY 等）
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"=== tools ({len(tools.tools)}) ===")
            for t in tools.tools:
                print(f"  {t.name}: {t.description.splitlines()[0]}")

            print("\n=== list_skills ===")
            r = await session.call_tool("list_skills", {})
            print(r.content[0].text)

            print("\n=== get_skill(pr-ai-review-loop) ===")
            r = await session.call_tool("get_skill", {"name": "pr-ai-review-loop"})
            data = json.loads(r.content[0].text)
            print(f"name={data['name']} version={data.get('version')} source={data.get('source')} len={len(data.get('content',''))}")

            print("\n=== install_skill (to temp dir) ===")
            r = await session.call_tool("install_skill", {"name": "pr-ai-review-loop"})
            print(r.content[0].text)

            print("\n=== install_skill with_deps (依赖解析) ===")
            import tempfile
            tmpdir = tempfile.mkdtemp(prefix="skills-hub-test-")
            params2 = StdioServerParameters(
                command=sys.executable,
                args=[server_script],
                env={**os.environ, "SKILLS_HUB_INSTALL_DIR": tmpdir},
            )
            async with stdio_client(params2) as (read2, write2):
                async with ClientSession(read2, write2) as session2:
                    await session2.initialize()
                    r = await session2.call_tool(
                        "install_skill",
                        {"name": "pr-ai-review-loop", "force": True, "with_deps": True},
                    )
                    data = json.loads(r.content[0].text)
                    print(f"ok={data.get('ok')} installed={[i['name'] for i in data.get('installed', [])]}")
                    names = {i["name"] for i in data.get("installed", [])}
                    assert "pr-ai-review-loop" in names
                    assert "ai-review-method" in names, f"依赖未安装: {names}"
                    assert "review-severity-policy" in names, f"依赖未安装: {names}"
                    # 验证文件真实存在
                    for n in names:
                        p = os.path.join(tmpdir, n, "SKILL.md")
                        assert os.path.isfile(p), f"缺少文件: {p}"
                    print("✅ 依赖解析验证通过 (loop + method + severity-policy 全装)")

            print("\n=== refresh_cache ===")
            r = await session.call_tool("refresh_cache", {})
            print(r.content[0].text[:200])

            print("\n=== get_skill(nonexistent) — 期望 error ===")
            r = await session.call_tool("get_skill", {"name": "no-such-skill"})
            print(r.content[0].text[:150])

    print("\n✅ ALL E2E TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
