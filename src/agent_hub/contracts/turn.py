"""统一回合契约：通道无关的对话回合结果。

:data:`TurnEvent`   — 流式 chunk 类型别名，与 AgentTurnLoop chunk 格式一致
                      (``dict[str, Any]``)，由 ``UnifiedTurnRuntime.stream()`` yield。

:class:`TurnResult` — ``UnifiedTurnRuntime.handle()`` 的统一返回值，覆盖所有
                      下游消费方（HTTP、飞书、评测）的需求，不包含任何 Pilot
                      领域类型以保持契约层零依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 流式事件 = AgentTurnLoop 产出的 dict chunk（type / content / …）
TurnEvent = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TurnResult:
    """``UnifiedTurnRuntime.handle()`` 的统一返回值。

    Attributes:
        trace_id:          本次回合的链路追踪 ID。
        reply_text:        模型直接回复内容；``answer_directly`` / token 流路径非空。
        task_id:           ``start_pilot_task`` 成功时的任务 ID。
        workspace_id:      ``start_pilot_task`` 成功时所属工作区 ID。
        plan_id:           ``start_pilot_task`` 时关联的 plan ID。
        task_status:       ``start_pilot_task`` 时的任务状态字符串。
        deduplicated:      ``start_pilot_task`` 幂等命中时为 ``True``。
        events_url:        任务 SSE 事件流 URL。
        status:            ``"success"`` | ``"blocked"`` | ``"error"``。
        error:             ``status == "error"`` 时的错误描述。
        total_duration_ms: 端到端耗时（毫秒）。
    """

    trace_id: str
    reply_text: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    plan_id: str | None = None
    task_status: str | None = None
    deduplicated: bool = False
    events_url: str | None = None
    status: str = "success"
    error: str | None = None
    total_duration_ms: int = 0


__all__ = ["TurnEvent", "TurnResult"]
