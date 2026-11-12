#!/usr/bin/env python3
"""单元测试：Redis 缓存层 + API Key 限流层（mock Redis，不依赖真实 Redis 实例）。

覆盖：
- 缓存：Redis 命中 / 未命中回写 / 异常降级内存 / force 清缓存
- 限流：Redis 计数放行 / 超限拒绝 / Redis 故障降级内存 / 身份独立计数 / 窗口重置

运行方式：
    cd mcp/
    python -m pytest test_cache_rate_limit.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import mcp_server


@pytest.fixture(autouse=True)
def reset_module_state():
    """每个用例前后重置全局缓存、限流计数与 Redis 连接状态，避免用例串扰。"""
    mcp_server._cache["skills"] = None
    mcp_server._cache["fetched_at"] = 0.0
    mcp_server._cache["contents"].clear()
    mcp_server._cache["contents_fetched_at"].clear()
    mcp_server._cache["changelogs"].clear()
    mcp_server._cache["changelogs_fetched_at"].clear()
    mcp_server._rate_memory.clear()
    mcp_server._redis_client = None
    mcp_server._redis_state = "pending"
    yield
    mcp_server._redis_client = None
    mcp_server._redis_state = "pending"
    mcp_server._rate_memory.clear()


def _mock_redis_client(get_value: str | None = None, incr_values=None) -> MagicMock:
    """构造一个模拟 Redis 客户端；get 返回 get_value，incr 按 incr_values 序列自增返回。"""
    client = MagicMock()
    client.get.return_value = get_value
    client.delete.return_value = 1
    client.scan_iter.return_value = []
    if incr_values is not None:
        client.incr.side_effect = iter(incr_values)
    else:
        client.incr.side_effect = iter([1])
    return client


# ----------------------------------------------------------------
# 缓存：索引
# ----------------------------------------------------------------

class TestIndexCache:

    def test_no_redis_returns_none(self):
        """未配置 REDIS_URL 时 _get_redis 返回 None，走内存。"""
        with patch.object(mcp_server, "REDIS_URL", ""):
            assert mcp_server._get_redis() is None

    def test_redis_hit_skips_remote_fetch(self):
        """Redis 命中索引时直接返回，不再读本地副本 / GitHub。"""
        skills = [{"name": "skill-a", "version": "1.0.0", "source": "redis"}]
        client = _mock_redis_client(get_value=json.dumps(skills, ensure_ascii=False))
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch("mcp_server._local_skills") as mock_local, \
             patch("mcp_server._remote_skills") as mock_remote:
            result = mcp_server.get_skills_index()
            assert result == skills
            mock_local.assert_not_called()
            mock_remote.assert_not_called()

    def test_redis_miss_local_then_write_back(self):
        """Redis 未命中时读本地副本，并把结果回写 Redis。"""
        client = _mock_redis_client(get_value=None)
        local = [{"name": "skill-a", "version": "1.0.0", "source": "local"}]
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch("mcp_server._local_skills", return_value=local):
            result = mcp_server.get_skills_index()
            assert result == local
            client.set.assert_called_once()
            # 回写的是索引 key，带 TTL
            key, value = client.set.call_args[0][0], client.set.call_args[0][1]
            assert key == mcp_server.KEY_INDEX
            assert json.loads(value) == local

    def test_redis_error_degrades_to_memory(self):
        """Redis 读抛异常时静默降级，不影响取数。"""
        client = MagicMock()
        client.get.side_effect = Exception("connection refused")
        client.set.side_effect = Exception("connection refused")
        local = [{"name": "skill-a", "source": "local"}]
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch("mcp_server._local_skills", return_value=local):
            result = mcp_server.get_skills_index()
            assert result == local

    def test_force_clears_redis_and_memory(self):
        """force=True 同时清 Redis 索引/内容/changelog 键和内存桶。"""
        client = _mock_redis_client(get_value=None)
        # 先往内存塞旧数据
        mcp_server._cache["skills"] = [{"name": "old"}]
        mcp_server._cache["fetched_at"] = mcp_server.time.time()
        mcp_server._cache["contents"]["old"] = {"name": "old"}
        mcp_server._cache["changelogs"]["old"] = {"name": "old"}
        local = [{"name": "skill-a", "source": "local"}]
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch("mcp_server._local_skills", return_value=local):
            mcp_server.get_skills_index(force=True)
            client.delete.assert_any_call(mcp_server.KEY_INDEX)
            assert mcp_server._cache["contents"] == {}
            assert mcp_server._cache["changelogs"] == {}


# ----------------------------------------------------------------
# 缓存：单条内容
# ----------------------------------------------------------------

class TestContentCache:

    def test_redis_content_hit(self, tmp_path):
        """内容在 Redis 命中时直接返回，不读本地文件。"""
        data = {"name": "skill-a", "content": "# doc", "version": "1.0.0", "source": "redis"}
        client = _mock_redis_client(get_value=json.dumps(data, ensure_ascii=False))
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch.object(mcp_server, "LOCAL_REPO", str(tmp_path)):
            result = mcp_server.get_skill_content("skill-a")
            assert result == data

    def test_redis_content_miss_writes_back(self, tmp_path):
        """Redis 未命中读本地副本后回写 Redis。"""
        skill_dir = tmp_path / "skills" / "skill-a"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: skill-a\nversion: 2.0.0\n---\n正文", encoding="utf-8"
        )
        client = _mock_redis_client(get_value=None)
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch.object(mcp_server, "LOCAL_REPO", str(tmp_path)):
            result = mcp_server.get_skill_content("skill-a")
            assert result["version"] == "2.0.0"
            client.set.assert_called_once()
            assert client.set.call_args[0][0] == mcp_server._content_key("skill-a")


# ----------------------------------------------------------------
# 缓存：changelog
# ----------------------------------------------------------------

class TestChangelogCache:

    def test_changelog_redis_hit(self):
        data = {"name": "skill-a", "content": "# c", "versions": [{"version": "1.0.0"}], "source": "redis"}
        client = _mock_redis_client(get_value=json.dumps(data, ensure_ascii=False))
        with patch.object(mcp_server, "_get_redis", return_value=client):
            result = mcp_server._get_skill_changelog("skill-a")
            assert result == data


# ----------------------------------------------------------------
# 限流
# ----------------------------------------------------------------

class TestRateLimit:

    def test_redis_counts_and_allows(self):
        client = _mock_redis_client(incr_values=[1])
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch.object(mcp_server, "RATE_LIMIT", 3), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            result = mcp_server.check_rate_limit("key-a")
            assert result["allowed"] is True
            assert result["backend"] == "redis"
            assert result["count"] == 1
            client.expire.assert_called_once()

    def test_redis_rejects_over_limit(self):
        client = _mock_redis_client(incr_values=[4])  # 超过 limit=3
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch.object(mcp_server, "RATE_LIMIT", 3), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            result = mcp_server.check_rate_limit("key-a")
            assert result["allowed"] is False
            assert result["backend"] == "redis"
            assert result["retry_after"] == 60

    def test_redis_failure_degrades_to_memory(self):
        """Redis 计数抛异常时降级内存计数。"""
        client = MagicMock()
        client.incr.side_effect = Exception("redis down")
        with patch.object(mcp_server, "_get_redis", return_value=client), \
             patch.object(mcp_server, "RATE_LIMIT", 3), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            result = mcp_server.check_rate_limit("key-a")
            assert result["allowed"] is True
            assert result["backend"] == "memory"
            assert result["count"] == 1

    def test_memory_counter_rejects_after_limit(self):
        """纯内存模式：连续调用到上限后拒绝。"""
        with patch.object(mcp_server, "_get_redis", return_value=None), \
             patch.object(mcp_server, "RATE_LIMIT", 3), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            for _ in range(3):
                r = mcp_server.check_rate_limit("anon")
                assert r["allowed"] is True
            r = mcp_server.check_rate_limit("anon")
            assert r["allowed"] is False
            assert r["backend"] == "memory"

    def test_different_identity_independent(self):
        """不同身份（API Key）计数互不影响。"""
        with patch.object(mcp_server, "_get_redis", return_value=None), \
             patch.object(mcp_server, "RATE_LIMIT", 2), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            mcp_server.check_rate_limit("key-a")
            mcp_server.check_rate_limit("key-a")
            r_b = mcp_server.check_rate_limit("key-b")  # key-b 独立计数
            assert r_b["count"] == 1
            assert r_b["allowed"] is True

    def test_window_reset_after_rollover(self):
        """窗口滚动到下一个区间后计数重置。"""
        with patch.object(mcp_server, "_get_redis", return_value=None), \
             patch.object(mcp_server, "RATE_LIMIT", 2), \
             patch.object(mcp_server, "RATE_WINDOW", 60):
            t0 = 1_000_000.0
            with patch("mcp_server.time.time", return_value=t0):
                mcp_server.check_rate_limit("key-a")
                mcp_server.check_rate_limit("key-a")
            # 跨到下一个窗口
            with patch("mcp_server.time.time", return_value=t0 + 60):
                r = mcp_server.check_rate_limit("key-a")
                assert r["count"] == 1
                assert r["allowed"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
