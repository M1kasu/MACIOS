"""SSE 流式输出模块。

将 Pipeline 的分步执行结果转换为 Server-Sent Events 格式，
通过 sse-starlette 推送给客户端。

事件格式：
    data: {"type": "token"|"status"|"done"|"error", "content": "..."}\n\n
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, TypeAlias

import structlog

if TYPE_CHECKING:
    from agent_hub.contracts.interaction import InboundRequest
    from agent_hub.runtime.agent.turn_runtime import UnifiedTurnRuntime

logger = structlog.get_logger(__name__)

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _sse_event(event_type: str, content: JSONValue, **extra: JSONValue) -> str:
    """构造 SSE data 行。"""
    payload = {"type": event_type, "content": content, **extra}
    return json.dumps(payload, ensure_ascii=False)


async def sse_generator(
    turn_runtime: UnifiedTurnRuntime,
    request: InboundRequest,
) -> AsyncGenerator[str, None]:
    """UnifiedTurnRuntime 流式执行的 SSE 事件生成器。

    Args:
        turn_runtime: 已初始化的 UnifiedTurnRuntime。
        request:      规范化入站请求。

    Yields:
        SSE data 字符串（不含 ``data: `` 前缀，由 sse-starlette 框架添加）。
    """
    yield _sse_event("accepted", "accepted", trace_id=request.trace_id)
    yield _sse_event("status", "processing", trace_id=request.trace_id)

    try:
        async for chunk in turn_runtime.stream(request):
            yield _sse_event(
                chunk.get("type", "token"),
                chunk.get("content", ""),
                **{k: v for k, v in chunk.items() if k not in ("type", "content")},
            )

        yield _sse_event("done", "", trace_id=request.trace_id)

    except Exception as exc:
        logger.error("sse_generator_error", error=str(exc))
        yield _sse_event("error", str(exc))
        yield _sse_event("done", "", error=True)
