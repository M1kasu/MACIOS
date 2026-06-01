"""统一交互入口路由（``/api/interactions``）。

**本路由是产品主入口和评测主入口。**
``/chat`` 和 ``/api/pilot/tasks`` 保留为底层调试接口，面向
"我知道我要做什么"的开发者直接调用。

请求接受一组简洁字段，内部构造 :class:`InboundRequest` 并交给
:class:`UnifiedTurnRuntime` 处理，实现"私聊 / 群聊 / API 模拟输入
→ AgentTurnLoop → 普通问答 / 复杂任务 / 进度查询 / 忽略"
的全链路。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_hub.contracts.identity import (
    SourceChatType,
    SourceContext,
    UserContext,
    UserRole,
)
from agent_hub.contracts.interaction import InboundRequest
from agent_hub.contracts.turn import TurnIntent

if TYPE_CHECKING:
    from agent_hub.api.pilot_runtime import PilotRuntime
    from agent_hub.runtime.agent.turn_runtime import UnifiedTurnRuntime


# ── 请求 / 响应模型 ────────────────────────────────────────────────────────────


class InteractionRequest(BaseModel):
    """扁平化的交互入口请求模型。

    供评测脚本和本地调试直接构造，不需要手动嵌套 UserContext /
    SourceContext — 路由内部会自动转换为 :class:`InboundRequest`。

    Args:
        user_id:      请求者 ID；评测时可设为任意字符串。
        role:         ``"user"`` / ``"admin"``，默认 ``"user"``。
        channel:      入站渠道，如 ``"api"`` / ``"feishu"``；默认 ``"api"``。
        chat_id:      会话 ID；进度查询时用于定位工作区。
        chat_type:    ``"direct"`` / ``"group"``；默认 ``"direct"``。
        is_at_bot:    群聊时是否 @bot；默认 ``False``。
        message_id:   消息 ID，用于幂等性校验。
        text:         消息正文。
        attachments:  附件键列表。
        message_type: 消息类型字符串；默认 ``"text"``。
        trace_id:     链路追踪 ID；未传时自动生成。
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: str = "user"
    channel: str = "api"
    chat_id: str | None = None
    chat_type: str = "direct"
    is_at_bot: bool = False
    message_id: str | None = None
    text: str = ""
    attachments: list[str] = Field(default_factory=list)
    message_type: str = "text"
    trace_id: str | None = None


class InteractionResponse(BaseModel):
    """统一交互响应，扁平结构方便客户端消费。"""

    model_config = ConfigDict(extra="forbid")

    intent: str
    trace_id: str
    reply_text: str | None = None
    task_id: str | None = None
    workspace_id: str | None = None
    plan_id: str | None = None
    events_url: str | None = None
    decision_reason: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    deduplicated: bool = False


# ── 路由工厂 ──────────────────────────────────────────────────────────────────


def build_interactions_router(
    runtime: PilotRuntime,
    turn_runtime: UnifiedTurnRuntime,
) -> APIRouter:
    """构造并返回 ``/api/interactions`` 路由器。

    被 :func:`agent_hub.api.routes.lifespan` 在 Pilot 启用时调用，
    动态注入 ``runtime`` 和 ``turn_runtime``。
    """
    router = APIRouter(
        prefix="/api/interactions",
        tags=["interactions"],
    )

    @router.post("", response_model=InteractionResponse, summary="统一交互入口")
    async def create_interaction(req: InteractionRequest) -> InteractionResponse:
        """统一交互入口：自动路由到普通问答 / 复杂任务 / 进度查询 / 忽略。

        这是 **产品主入口**和**评测主入口**。调用方只需传递扁平的请求字段，
        服务自动决定意图并调用对应下游。

        底层调试接口（了解内部机制时使用）：
        - ``POST /chat``            — 直连 AgentPipeline；
        - ``POST /api/pilot/tasks`` — 直连 TaskOrchestrator。
        """
        # 构造规范化入站请求
        chat_type_enum = (
            SourceChatType(req.chat_type)
            if req.chat_type in SourceChatType._value2member_map_  # noqa: SLF001
            else SourceChatType.UNKNOWN
        )
        inbound = InboundRequest(
            trace_id=req.trace_id or str(uuid.uuid4()),
            user_context=UserContext(
                user_id=req.user_id,
                role=(
                    UserRole(req.role)
                    if req.role in UserRole._value2member_map_  # noqa: SLF001
                    else UserRole.USER
                ),
            ),
            source_context=SourceContext(
                channel=req.channel,
                chat_id=req.chat_id,
                chat_type=chat_type_enum,
                message_id=req.message_id,
                is_at_bot=req.is_at_bot,
            ),
            text=req.text,
            attachments=req.attachments,
            message_type=req.message_type,
        )

        result = await turn_runtime.handle(inbound)

        intent = getattr(result.intent, "value", result.intent)
        if intent == TurnIntent.IGNORE.value:
            if result.status == "blocked":
                intent = TurnIntent.BLOCKED.value
            elif result.status == "error":
                intent = TurnIntent.ERROR.value
            elif result.task_id:
                intent = TurnIntent.START_TASK.value
            elif result.reply_text:
                intent = TurnIntent.ORDINARY_QA.value

        # 填充 events_url（需要 public_url helper）
        events_url: str | None = result.events_url
        if result.task_id and not events_url:
            try:
                events_url = runtime.settings.public_url(
                    f"/api/pilot/tasks/{result.task_id}/events"
                )
            except Exception:  # noqa: BLE001 - public_url 在测试中可能未实现
                events_url = f"/api/pilot/tasks/{result.task_id}/events"

        return InteractionResponse(
            intent=intent,
            trace_id=result.trace_id,
            reply_text=result.reply_text,
            task_id=result.task_id,
            workspace_id=result.workspace_id,
            plan_id=result.plan_id,
            events_url=events_url,
            decision_reason=None,
            matched_keywords=[],
            deduplicated=result.deduplicated,
        )

    return router


__all__ = ["InteractionRequest", "InteractionResponse", "build_interactions_router"]
