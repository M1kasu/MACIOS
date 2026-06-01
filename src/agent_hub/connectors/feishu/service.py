"""把规范化的飞书消息接到 ``UnifiedTurnRuntime`` 上。

仅通过 WebSocket 长连接模式接收事件，处理流程：

1. 将消息规范化为 :class:`InboundRequest`；
2. 交由 :class:`UnifiedTurnRuntime` 流式执行（AgentTurnLoop 决策）；
3. 检测到 ``start_pilot_task`` 工具启动时立即发送 ACK；
   普通问答则在流结束后回复文本。
4. 审批卡片回调（``card.action.trigger``）直接交给
   :class:`PilotCommandService` 处理，不经过 AgentTurnLoop。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from agent_hub.connectors.feishu.client import FeishuClientProtocol
from agent_hub.connectors.feishu.models import (
    FeishuCardCallback,
    FeishuChatType,
    FeishuInboundMessage,
    FeishuWebhookOutcome,
)
from agent_hub.connectors.feishu.webhook import (
    FeishuWebhookProcessor,
    FeishuWebhookResult,
)
from agent_hub.contracts.turn import TurnIntent
from agent_hub.pilot.domain.enums import TaskStatus
from agent_hub.pilot.services.dto import TaskHandle
from agent_hub.pilot.skills.feishu_card import build_decision_card

if TYPE_CHECKING:
    from agent_hub.contracts.interaction import InboundRequest
    from agent_hub.pilot.services.commands import PilotCommandService
    from agent_hub.pilot.services.repository import PilotRepository
    from agent_hub.runtime.agent.turn_runtime import UnifiedTurnRuntime

logger = structlog.get_logger(__name__)

SOURCE_CHANNEL = "feishu"
GROUP_PRIVATE_ACK_TEXT = "收到，文件做好后我私发给您"


@dataclass(frozen=True, slots=True)
class FeishuAckResult:
    outcome: FeishuWebhookOutcome
    handle: TaskHandle | None = None
    reason: str | None = None
    ack_message_id: str | None = None
    approval_decision: dict[str, object] | None = None
    intent: TurnIntent | None = None
    reply_message_id: str | None = None
    # 在 ``card.action.trigger`` 回调中需要同步返回给飞书客户端的
    # “决议后终态卡片”；为空时客户端会保留原卡片。
    card_to_replace: dict[str, object] | None = None


class FeishuWebhookService:
    """飞书长连接入站处理服务。

    Args:
        processor:    事件解析器（去重 + 规范化 + 过滤）。
        client:       飞书出站客户端；``None`` 时不回复（测试 / dry-run）。
        commands:     审批决策服务；``None`` 时卡片回调静默处理。
        repository:   可选仓储，仅用于审批卡片更新查询。
        turn_runtime: 统一对话运行时；``None`` 时 ACCEPTED 消息将被忽略。
        ack_template: ACK 文案模板，``{title}`` 替换为消息截断标题。
        send_ack:     是否发送 ACK；关闭后不回复（仅创建 task）。
    """

    def __init__(
        self,
        *,
        processor: FeishuWebhookProcessor,
        client: FeishuClientProtocol | None = None,
        commands: PilotCommandService | None = None,
        repository: PilotRepository | None = None,
        turn_runtime: UnifiedTurnRuntime | None = None,
        ack_template: str = "收到任务，开始执行，正在规划：{title}",
        send_ack: bool = True,
    ) -> None:
        self._processor = processor
        self._client = client
        self._commands = commands
        self._repo = repository
        self._turn_runtime = turn_runtime
        self._ack_template = ack_template
        self._send_ack = send_ack

    async def handle_event_dict(self, payload: dict) -> FeishuAckResult:
        """长连接模式入口：跳过验签/解密，直接处理已解包事件 dict。"""
        result = await self._processor.handle_event_dict(payload)
        return await self._process_result(result)

    async def _process_result(self, result: FeishuWebhookResult) -> FeishuAckResult:
        """将 FeishuWebhookResult 路由到下游业务逻辑。"""
        if result.outcome is FeishuWebhookOutcome.CARD_CALLBACK:
            return await self._handle_card_callback(result.card_callback)
        if result.outcome is not FeishuWebhookOutcome.ACCEPTED:
            return FeishuAckResult(outcome=result.outcome, reason=result.reason)

        message = result.message
        if message is None:  # pragma: no cover - 防御
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.IGNORED,
                reason="processor returned no message",
            )

        if self._turn_runtime is None:
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.IGNORED,
                reason="turn_runtime not configured",
            )

        inbound = self._to_inbound_request(message)
        ack_id: str | None = None
        reply_parts: list[str] = []
        task_id: str | None = None
        workspace_id: str | None = None
        plan_id: str | None = None
        task_status_str: str | None = None
        deduplicated: bool = False
        turn_intent = TurnIntent.IGNORE

        try:
            async for chunk in self._turn_runtime.stream(inbound):
                chunk_type = chunk.get("type", "")
                content = chunk.get("content", "")

                if (
                    chunk_type == "tool_started"
                    and chunk.get("tool_name") == "start_pilot_task"
                    and ack_id is None
                ):
                    # 检测到任务启动 → 提前发送 ACK，不等流结束
                    ack_id = await self._maybe_ack(message)
                elif chunk_type in ("token", "final") and content:
                    reply_parts.append(str(content))
                    if turn_intent is TurnIntent.IGNORE:
                        turn_intent = TurnIntent.ORDINARY_QA
                elif chunk_type == "blocked":
                    if content:
                        reply_parts.append(str(content))
                    turn_intent = TurnIntent.BLOCKED
                    break
                elif chunk_type == "error":
                    turn_intent = TurnIntent.ERROR
                    logger.warning("feishu.service.turn_chunk_error", error=str(content))
                elif chunk_type == "tool_finished":
                    if chunk.get("tool_name") == "query_task_status":
                        turn_intent = TurnIntent.PROGRESS_QUERY
                    tool_result = chunk.get("result")
                    if (
                        isinstance(tool_result, dict)
                        and tool_result.get("status") == "started"
                        and tool_result.get("task_id")
                    ):
                        task_id = tool_result.get("task_id")
                        workspace_id = tool_result.get("workspace_id")
                        plan_id = tool_result.get("plan_id")
                        task_status_str = tool_result.get("task_status")
                        deduplicated = bool(tool_result.get("deduplicated", False))
                        turn_intent = TurnIntent.START_TASK
        except Exception as exc:  # noqa: BLE001
            logger.warning("feishu.service.turn_failed", error=str(exc))
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.IGNORED,
                reason=f"turn_error: {exc}",
            )

        if task_id:
            try:
                status_enum = (
                    TaskStatus(task_status_str) if task_status_str else TaskStatus.CREATED
                )
            except ValueError:
                status_enum = TaskStatus.CREATED
            task_handle = TaskHandle(
                workspace_id=workspace_id or "",
                task_id=task_id,
                plan_id=plan_id,
                status=status_enum,
                trace_id=inbound.trace_id,
                deduplicated=deduplicated,
            )
            if ack_id is None:
                ack_id = await self._maybe_ack(message, task_handle)
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.ACCEPTED,
                handle=task_handle,
                ack_message_id=ack_id,
                intent=TurnIntent.START_TASK,
            )

        reply_text = "".join(reply_parts) or None
        if reply_text:
            reply_id = await self._send_text_reply(message, reply_text)
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.ACCEPTED,
                intent=(
                    turn_intent
                    if turn_intent is not TurnIntent.IGNORE
                    else TurnIntent.ORDINARY_QA
                ),
                reply_message_id=reply_id,
            )

        return FeishuAckResult(
            outcome=FeishuWebhookOutcome.IGNORED,
            reason="no_response",
        )

    # ── 内部 ───────────────────────────────────────

    async def _handle_card_callback(
        self,
        callback: FeishuCardCallback | None,
    ) -> FeishuAckResult:
        """M5 审批卡片回调 → PilotCommandService.decide_approval。

        骨架实现：没有注入 ``commands`` 时静默 ignore，保证后向兼容。
        后续可加入"更新卡片状态"、"跳转产物链接"等逻辑。
        """
        if callback is None:  # pragma: no cover - 防御
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.IGNORED,
                reason="empty card callback",
            )
        if self._commands is None:
            logger.info(
                "feishu.card.ignored_no_commands",
                approval_id=callback.action_value.approval_id,
            )
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.CARD_CALLBACK,
                reason="commands service not wired",
            )

        decision = callback.action_value.decision.lower()
        if decision not in ("approve", "reject"):
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.IGNORED,
                reason=f"unsupported decision: {decision}",
            )
        try:
            outcome = await self._commands.decide_approval(
                callback.action_value.approval_id,
                decision=decision,  # type: ignore[arg-type]
                actor_id=callback.operator_open_id or "feishu",
                comment=callback.action_value.comment or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "feishu.card.decision_failed",
                approval_id=callback.action_value.approval_id,
                error=str(exc),
            )
            return FeishuAckResult(
                outcome=FeishuWebhookOutcome.REJECTED,
                reason=str(exc),
            )
        logger.info(
            "feishu.card.decision_applied",
            approval_id=callback.action_value.approval_id,
            decision=decision,
            actor_id=callback.operator_open_id,
        )
        decision_card = await self._update_approval_card(
            approval_id=callback.action_value.approval_id,
            decision=decision,
            actor_id=callback.operator_open_id or "feishu",
            comment=callback.action_value.comment or "",
        )
        return FeishuAckResult(
            outcome=FeishuWebhookOutcome.CARD_CALLBACK,
            approval_decision=outcome,
            card_to_replace=decision_card,
        )

    async def _update_approval_card(
        self,
        *,
        approval_id: str,
        decision: str,
        actor_id: str,
        comment: str,
    ) -> dict[str, Any] | None:
        """决议后用最终态卡片覆盖原来的审批卡片，并返回该卡片。

        返回值会被 `card.action.trigger` 回调同步塑进响应 payload，
        避免飞书客户端因“响应中未携带 card”而回退原卡片。
        """
        if self._client is None or self._repo is None:
            return None
        try:
            approval = await self._repo.get_approval(approval_id)
            if approval is None or not approval.channel_message_id:
                return None
            card = build_decision_card(
                title=approval.reason or "审批请求",
                summary=approval.preview or f"审批 {approval_id}",
                decision=decision,
                actor_id=actor_id,
                comment=comment,
            )
            await self._client.update_card(
                message_id=approval.channel_message_id,
                card=card,
            )
            logger.info(
                "feishu.card.updated_final_state",
                approval_id=approval_id,
                decision=decision,
                message_id=approval.channel_message_id,
            )
            return card
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "feishu.card.update_failed",
                approval_id=approval_id,
                error=str(exc),
            )
            return None

    def _to_inbound_request(self, message: FeishuInboundMessage) -> InboundRequest:
        """将飞书入站消息规范化为通用 :class:`InboundRequest`。"""
        from agent_hub.contracts.identity import (
            SourceChatType,
            SourceContext,
            UserContext,
            UserRole,
        )
        from agent_hub.contracts.interaction import InboundRequest

        chat_type = {
            FeishuChatType.P2P: SourceChatType.DIRECT,
            FeishuChatType.GROUP: SourceChatType.GROUP,
        }.get(message.chat_type, SourceChatType.UNKNOWN)
        return InboundRequest(
            user_context=UserContext(
                user_id=message.sender_id or "feishu-user",
                role=UserRole.USER,
            ),
            source_context=SourceContext(
                channel=SOURCE_CHANNEL,
                account_id=message.app_id,
                chat_id=message.chat_id,
                chat_type=chat_type,
                message_id=message.message_id,
                sender_id=message.sender_id,
                sender_id_type=message.sender_id_type,
                is_at_bot=message.bot_mentioned,
                raw={
                    "tenant_key": message.tenant_key,
                    "event_id": message.event_id,
                    "feishu_chat_type": message.chat_type.value,
                    "feishu_message_type": message.message_type.value,
                    **_private_delivery_metadata(message),
                },
            ),
            text=message.text or "",
            attachments=[a.file_key for a in message.attachments],
            message_type=message.message_type.value,
        )

    async def _maybe_ack(
        self,
        message: FeishuInboundMessage,
        handle: TaskHandle | None = None,
    ) -> str | None:
        if not self._send_ack or self._client is None:
            return None
        if handle is not None and handle.deduplicated:
            return None
        title = _derive_title(message)
        if message.chat_type is FeishuChatType.GROUP:
            text = GROUP_PRIVATE_ACK_TEXT
        else:
            text = self._ack_template.format(title=title)
        try:
            sent = await self._client.send_message(
                receive_id=message.chat_id,
                receive_id_type="chat_id",
                msg_type="text",
                content=json.dumps({"text": text}, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001 - 防御性吞掉，避免 ACK 失败影响主流程
            logger.warning(
                "feishu.webhook.ack_failed",
                chat_id=message.chat_id,
                task_id=handle.task_id if handle is not None else None,
                error=str(exc),
            )
            return None
        return sent.message_id

    async def _send_text_reply(
        self,
        message: FeishuInboundMessage,
        text: str | None,
    ) -> str | None:
        """普通问答 / 进度查询的回复发送，失败仅打日志不影响主流程。"""
        if not text or self._client is None:
            return None
        try:
            sent = await self._client.send_message(
                receive_id=message.chat_id,
                receive_id_type="chat_id",
                msg_type="text",
                content=json.dumps({"text": text}, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "feishu.turn.reply_failed",
                chat_id=message.chat_id,
                error=str(exc),
            )
            return None
        return sent.message_id


def _derive_title(message: FeishuInboundMessage) -> str:
    text = (message.text or "").strip()
    if text:
        first_line = text.splitlines()[0]
        return first_line[:32] or "飞书任务"
    if message.chat_type is FeishuChatType.P2P:
        return "飞书私聊任务"
    return "飞书群聊任务"


def _idempotency_key(message: FeishuInboundMessage) -> str:
    tenant = message.tenant_key or "unknown"
    base = message.event_id or message.message_id
    return f"feishu:{tenant}:{base}"


def _private_delivery_metadata(message: FeishuInboundMessage) -> dict[str, str]:
    sender_id = (message.sender_id or "").strip()
    sender_id_type = (message.sender_id_type or "open_id").strip() or "open_id"
    metadata = {
        "feishu_source_chat_id": message.chat_id,
        "feishu_source_chat_type": message.chat_type.value,
        "feishu_sender_id": sender_id,
        "feishu_sender_id_type": sender_id_type,
        "feishu_delivery_mode": "private",
    }
    if sender_id:
        metadata["feishu_private_receive_id"] = sender_id
        metadata["feishu_private_receive_id_type"] = sender_id_type
        if sender_id_type == "open_id":
            metadata["feishu_requester_open_id"] = sender_id
    return metadata


__all__ = [
    "FeishuAckResult",
    "FeishuWebhookService",
    "GROUP_PRIVATE_ACK_TEXT",
    "SOURCE_CHANNEL",
]


# 防 unused import 警告（FeishuWebhookResult 在 docstring 引用）。
_ = FeishuWebhookResult
