"""UnifiedTurnRuntime：唯一的自然语言对话入口运行时。

所有渠道（HTTP、飞书、评测模拟器）的自然语言输入统一经过此类，执行顺序：

  Guard → SourceBinding → AgentTurnLoop → 结果收集

:class:`UnifiedTurnRuntime` 不承担任何意图分类逻辑；意图由 AgentTurnLoop
内部的模型按需决定调用哪个工具：

- ``answer_directly``          — 直接回答
- ``query_task_status``        — 查询 Pilot 任务状态
- ``start_pilot_task``         — 启动 Pilot 长任务
- ``run_decision_router_plan`` — 复杂规划执行
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import structlog

from agent_hub.contracts.execution import TaskInput
from agent_hub.contracts.interaction import InboundRequest
from agent_hub.contracts.turn import TurnEvent, TurnResult

if TYPE_CHECKING:
    from agent_hub.core.pipeline import AgentPipeline

logger = structlog.get_logger(__name__)


def _to_task_input(request: InboundRequest) -> TaskInput:
    """将通道无关的入站请求转换为 Pipeline 内部执行格式。"""
    return TaskInput(
        trace_id=request.trace_id,
        user_context=request.user_context,
        source_context=request.source_context,
        raw_message=request.text or "",
        attachments=list(request.attachments),
    )


class UnifiedTurnRuntime:
    """唯一的自然语言对话入口运行时。

    Args:
        pipeline: ``AgentPipeline`` 实例，提供执行后端（Guard、Binding、
                  AgentTurnLoop、工具集、memory）。``run_stream()`` 是
                  进入 AgentTurnLoop 的唯一路径。
    """

    def __init__(self, pipeline: AgentPipeline) -> None:
        self._pipeline = pipeline

    async def stream(self, request: InboundRequest) -> AsyncGenerator[TurnEvent, None]:
        """流式执行一个回合，直接 yield AgentTurnLoop chunks。

        Args:
            request: 规范化入站请求。

        Yields:
            ``TurnEvent`` dicts（``type`` / ``content`` / …）。
        """
        task_input = _to_task_input(request)
        async for chunk in self._pipeline.run_stream(task_input):
            yield chunk

    async def handle(self, request: InboundRequest) -> TurnResult:
        """同步执行一个回合，收集所有 chunks 并返回统一结果。

        Chunks 消费规则：

        - ``token`` / ``final``    → 追加到 ``reply_text``
        - ``tool_finished``        → 检查 ``result["status"] == "started"``
                                     且 ``result["task_id"]`` 非空时提取
                                     任务元数据
        - ``error``                → 设置 ``status="error"``

        Args:
            request: 规范化入站请求。

        Returns:
            :class:`TurnResult` 供下游 HTTP / 飞书 adapter 消费。
        """
        start = time.monotonic()
        reply_parts: list[str] = []
        task_id: str | None = None
        workspace_id: str | None = None
        plan_id: str | None = None
        task_status: str | None = None
        deduplicated: bool = False
        events_url: str | None = None
        status = "success"
        error: str | None = None

        try:
            async for chunk in self.stream(request):
                chunk_type = chunk.get("type", "")
                content = chunk.get("content", "")

                if chunk_type in ("token", "final") and content:
                    reply_parts.append(str(content))
                elif chunk_type == "tool_finished":
                    result = chunk.get("result")
                    if (
                        isinstance(result, dict)
                        and result.get("status") == "started"
                        and result.get("task_id")
                    ):
                        task_id = result.get("task_id")
                        workspace_id = result.get("workspace_id")
                        plan_id = result.get("plan_id")
                        task_status = result.get("task_status")
                        deduplicated = bool(result.get("deduplicated", False))
                        events_url = result.get("events_url")
                elif chunk_type == "error":
                    status = "error"
                    error = str(content) if content else "unknown error"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "turn_runtime.handle_failed",
                trace_id=request.trace_id,
                error=str(exc),
            )
            status = "error"
            error = str(exc)

        reply_text = "".join(reply_parts) or None

        # Guard 拦截时 pipeline 产出 type="error" content 含 "blocked"；
        # 或直接抛出，此处统一映射。
        if status != "error" and error is None and reply_text is None and task_id is None:
            # stream 为空或 pipeline 拒绝服务；视为 blocked
            pass  # 保持 status="success"，调用方自行判断

        return TurnResult(
            trace_id=request.trace_id,
            reply_text=reply_text,
            task_id=task_id,
            workspace_id=workspace_id,
            plan_id=plan_id,
            task_status=task_status,
            deduplicated=deduplicated,
            events_url=events_url,
            status=status,
            error=error,
            total_duration_ms=int((time.monotonic() - start) * 1000),
        )


__all__ = ["UnifiedTurnRuntime"]
