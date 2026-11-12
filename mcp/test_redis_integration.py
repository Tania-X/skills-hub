#!/usr/bin/env python3
"""集成测试：连接本地真实 Redis，验证分布式缓存与限流计数。

前置条件：本地 Redis 运行在 127.0.0.1:6379（本项目 D 盘物理机安装，非 Docker）。
未配置 / 连不上时自动 skip，不影响纯单元测试运行。

运行方式：
    cd mcp/
    python -m pytest test_redis_integration.py -v
"""
import json
import os
import sys
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# 必须在导入 / reload 模块前设置 Redis 连接串
os.environ["SKILLS_HUB_REDIS_URL"] = "redis://127.0.0.1:6379/0"

import mcp_server  # noqa: E402
importlib.reload(mcp_server)  # 确保模块读到刚设置的 REDIS_URL
import redis as redis_lib  # noqa: E402


def _redis_alive() -> bool:
    try:
        r = redis_lib.Redis.from_url(
            os.environ["SKILLS_HUB_REDIS_URL"], decode_responses=True,
            protocol=2, socket_connect_timeout=2, socket_timeout=2,
        )
        return bool(r.ping())
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _redis_alive(), reason="本地 Redis 不可用，跳过 Redis 集成测试")


@pytest.fixture(autouse=True)
def clean_redis_keys():
    """每个用例前后清理本项目占用的 key 前缀，避免计数 / 缓存串扰。"""
    client = redis_lib.Redis.from_url(
        os.environ["SKILLS_HUB_REDIS_URL"], decode_responses=True,
        protocol=2, socket_connect_timeout=2, socket_timeout=2,
    )
    prefixes = ("skills:", "skill:content:", "skill:changelog:", "rate:")
    def _flush():
        for prefix in prefixes:
            for k in client.scan_iter(match=f"{prefix}*"):
                client.delete(k)
    _flush()
    yield
    _flush()


def test_redis_client_connected():
    """模块惰性客户端能连上真实 Redis 并探测为可用。"""
    client = mcp_server._get_redis()
    assert client is not None
    assert mcp_server._redis_state == "ok"
    assert client.ping() is True


def test_cache_roundtrip_and_ttl():
    """写入索引缓存后能从 Redis 读回，且带上了 TTL。"""
    skills = [{"name": "skill-a", "version": "1.0.0", "source": "github"}]
    mcp_server._redis_set(mcp_server.KEY_INDEX, json.dumps(skills, ensure_ascii=False), 300)

    raw = mcp_server._redis_get(mcp_server.KEY_INDEX)
    assert raw is not None
    assert json.loads(raw) == skills

    client = mcp_server._get_redis()
    ttl = client.ttl(mcp_server.KEY_INDEX)
    assert 0 < ttl <= 300


def test_index_served_from_redis_without_remote_fetch():
    """索引已在 Redis 时，get_skills_index 直接命中，不再读本地 / GitHub。"""
    skills = [{"name": "skill-a", "version": "1.0.0", "source": "redis"}]
    mcp_server._redis_set(mcp_server.KEY_INDEX, json.dumps(skills, ensure_ascii=False), 300)

    with patch("mcp_server._local_skills") as mock_local, \
         patch("mcp_server._remote_skills") as mock_remote:
        result = mcp_server.get_skills_index()
    assert result == skills
    mock_local.assert_not_called()
    mock_remote.assert_not_called()


def test_content_cache_roundtrip():
    """单条 skill 内容写入 Redis 后可完整读回（含中文 / 元信息）。"""
    data = {"name": "skill-a", "content": "# 正文\n中文内容", "version": "2.0.0", "source": "github"}
    key = mcp_server._content_key("skill-a")
    mcp_server._redis_set(key, json.dumps(data, ensure_ascii=False), 300)

    raw = mcp_server._redis_get(key)
    assert raw is not None
    assert json.loads(raw) == data


def test_rate_limit_real_redis_counter():
    """真实 Redis INCR 计数：窗口内放行，超阈值返回 429 语义（allowed=False）。"""
    identity = "integration-test-key"
    with patch.object(mcp_server, "RATE_LIMIT", 3), \
         patch.object(mcp_server, "RATE_WINDOW", 60):
        results = [mcp_server.check_rate_limit(identity) for _ in range(4)]

    for i, r in enumerate(results[:3]):
        assert r["allowed"] is True
        assert r["backend"] == "redis"
        assert r["count"] == i + 1

    assert results[3]["allowed"] is False
    assert results[3]["backend"] == "redis"
    assert results[3]["count"] == 4
    assert results[3]["limit"] == 3
    assert results[3]["retry_after"] == 60


def test_force_refresh_clears_redis_cache():
    """force=True 清掉旧索引 / 内容缓存，并用新拉取结果重建索引。"""
    mcp_server._redis_set(mcp_server.KEY_INDEX, json.dumps([{"name": "a"}]), 300)
    mcp_server._redis_set(mcp_server._content_key("skill-a"),
                           json.dumps({"name": "skill-a"}), 300)

    client = mcp_server._get_redis()
    assert client.exists(mcp_server.KEY_INDEX) == 1

    with patch("mcp_server._local_skills", return_value=[{"name": "b"}]):
        mcp_server.get_skills_index(force=True)

    # 旧的内容缓存被删除；索引被新拉取结果重建（不再是旧值 a）
    assert client.exists(mcp_server._content_key("skill-a")) == 0
    assert json.loads(client.get(mcp_server.KEY_INDEX)) == [{"name": "b"}]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
