"""SSE 流式输出 + 流式 Pipeline + 并发限流测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from agent_hub.api.streaming import sse_generator
from agent_hub.core.rate_limiter import RateLimiter

# ═══════════════════════════════════════════════════════
# RateLimiter 测试
# ═══════════════════════════════════════════════════════


class TestRateLimiter:
    """并发限流器测试。"""

    @pytest.mark.asyncio
    async def test_basic_call(self) -> None:
        limiter = RateLimiter(max_concurrent=5, default_timeout=10)

        async def coro() -> int:
            return 42

        result = await limiter.call(coro())
        assert result == 42
        assert limiter.total_calls == 1

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        limiter = RateLimiter(max_concurrent=5, default_timeout=0.1)

        async def slow_coro() -> str:
            await asyncio.sleep(10)
            return "done"

        with pytest.raises(asyncio.TimeoutError):
            await limiter.call(slow_coro())

        assert limiter.timeouts == 1

    @pytest.mark.asyncio
    async def test_fallback_on_timeout(self) -> None:
        limiter = RateLimiter(max_concurrent=5, default_timeout=0.1)

        async def slow_coro() -> str:
            await asyncio.sleep(10)
            return "done"

        result = await limiter.call_with_fallback(
            slow_coro(), fallback="兜底值", timeout=0.1,
        )
        assert result == "兜底值"

    @pytest.mark.asyncio
    async def test_concurrency_limit(self) -> None:
        limiter = RateLimiter(max_concurrent=2, default_timeout=5)
        concurrent_count = 0
        max_concurrent = 0

        async def tracked_coro() -> str:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return "ok"

        tasks = [limiter.call(tracked_coro()) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert all(r == "ok" for r in results)
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_no_timeout(self) -> None:
        limiter = RateLimiter(max_concurrent=5, default_timeout=0)

        async def coro() -> str:
            return "no timeout"

        result = await limiter.call(coro())
        assert result == "no timeout"


# ═══════════════════════════════════════════════════════
# SSE Generator 测试
# ═══════════════════════════════════════════════════════


class TestSSEGenerator:
    """SSE 事件生成器测试。"""

    @pytest.mark.asyncio
    async def test_non_streaming_fallback(self) -> None:
        """无流内容时，sse_generator 仍然输出 accepted / status / done。"""
        mock_turn_runtime = MagicMock()

        async def _empty_stream(_req: object) -> AsyncIterator[dict[str, str]]:
            return
            yield  # make it an async generator

        mock_turn_runtime.stream = _empty_stream

        mock_input = MagicMock()
        mock_input.trace_id = "t1"

        events = []
        async for event in sse_generator(mock_turn_runtime, mock_input):
            events.append(json.loads(event))

        assert events[0]["type"] == "accepted"
        assert any(e["type"] == "status" for e in events)
        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_streaming_mode(self) -> None:
        """turn_runtime.stream() 的 chunk 正确转发为 SSE 事件。"""
        mock_turn_runtime = MagicMock()

        async def mock_stream(_req: object) -> AsyncIterator[dict[str, str]]:
            yield {"type": "token", "content": "Hello "}
            yield {"type": "token", "content": "World"}

        mock_turn_runtime.stream = mock_stream

        mock_input = MagicMock()
        mock_input.trace_id = "t1"

        events = []
        async for event in sse_generator(mock_turn_runtime, mock_input):
            events.append(json.loads(event))

        assert events[0]["type"] == "accepted"
        tokens = [e["content"] for e in events if e["type"] == "token"]
        assert "Hello " in tokens
        assert "World" in tokens
        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        """stream() 抛异常时推送 error 事件。"""
        mock_turn_runtime = MagicMock()

        async def mock_stream(_req: object) -> AsyncIterator[dict[str, str]]:
            raise RuntimeError("LLM 炸了")
            yield {"type": "token", "content": ""}

        mock_turn_runtime.stream = mock_stream

        mock_input = MagicMock()
        mock_input.trace_id = "t1"

        events = []
        async for event in sse_generator(mock_turn_runtime, mock_input):
            events.append(json.loads(event))

        assert any(e["type"] == "error" for e in events)
        assert events[-1]["type"] == "done"


class TestUnifiedTurnRuntime:
    @pytest.mark.asyncio
    async def test_handle_maps_blocked_chunk_to_blocked_status(self) -> None:
        from agent_hub.contracts.identity import (
            SourceChatType,
            SourceContext,
            UserContext,
            UserRole,
        )
        from agent_hub.contracts.interaction import InboundRequest
        from agent_hub.contracts.turn import TurnIntent, TurnStatus
        from agent_hub.runtime.agent.turn_runtime import UnifiedTurnRuntime

        pipeline = MagicMock()

        async def _blocked_stream(_task_input: object) -> AsyncIterator[dict[str, str]]:
            yield {"type": "blocked", "content": "请求已被拦截"}

        pipeline.run_stream = _blocked_stream
        runtime = UnifiedTurnRuntime(pipeline)
        result = await runtime.handle(
            InboundRequest(
                trace_id="trace-blocked",
                user_context=UserContext(user_id="u1", role=UserRole.USER),
                source_context=SourceContext(
                    channel="api",
                    chat_type=SourceChatType.DIRECT,
                ),
                text="blocked",
            )
        )

        assert result.status is TurnStatus.BLOCKED
        assert result.intent is TurnIntent.BLOCKED
        assert result.reply_text == "请求已被拦截"
