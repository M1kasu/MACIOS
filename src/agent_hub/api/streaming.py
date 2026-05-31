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
    from agent_hub.core.models import TaskInput
    from agent_hub.core.pipeline import AgentPipeline

logger = structlog.get_logger(__name__)

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _sse_event(event_type: str, content: JSONValue, **extra: JSONValue) -> str:
    """构造 SSE data 行。"""
    payload = {"type": event_type, "content": content, **extra}
    return json.dumps(payload, ensure_ascii=False)


async def sse_generator(
    pipeline: AgentPipeline,
    task_input: TaskInput,
) -> AsyncGenerator[str, None]:
    """Pipeline 流式执行的 SSE 事件生成器。

    如果 pipeline 支持 ``run_stream()``，则逐步推送。
    否则降级为调用标准 ``run()`` 后一次性返回。

    Args:
        pipeline: AgentPipeline 实例。
        task_input: 用户请求。

    Yields:
        SSE data 字符串（不含 ``data: `` 前缀，由 sse-starlette 框架添加）。
    """
    yield _sse_event("accepted", "accepted", trace_id=task_input.trace_id)
    yield _sse_event("status", "processing", trace_id=task_input.trace_id)

    try:
        if hasattr(pipeline, "run_stream"):
            async for chunk in pipeline.run_stream(task_input):
                yield _sse_event(
                    chunk.get("type", "token"),
                    chunk.get("content", ""),
                    **{k: v for k, v in chunk.items() if k not in ("type", "content")},
                )
        else:
            # 降级：非流式调用
            output = await pipeline.run(task_input)
            yield _sse_event("token", output.response)

        yield _sse_event("done", "", trace_id=task_input.trace_id)

    except Exception as exc:
        logger.error("sse_generator_error", error=str(exc))
        yield _sse_event("error", str(exc))
        yield _sse_event("done", "", error=True)
