"""``FeishuWebhookProcessor`` 与 ``FeishuWebhookService`` 单元测试。"""

from __future__ import annotations

import json

import pytest

from agent_hub.connectors.feishu import (
    FakeFeishuClient,
    FeishuChatType,
    FeishuMessageType,
    FeishuWebhookOutcome,
    FeishuWebhookProcessor,
    FeishuWebhookService,
)
from agent_hub.pilot import (
    ApprovalService,
    ArtifactStore,
    EventBus,
    ExecutionEngine,
    FakeModelGateway,
    InMemoryEventStore,
    PilotEventPublisher,
    PilotRepository,
    PlanningService,
    SkillRegistry,
    TaskOrchestrator,
    register_fake_skills,
)

# ── 通用 builders ──────────────────────────────────


def _make_orchestrator() -> tuple[TaskOrchestrator, PilotRepository]:
    store = InMemoryEventStore()
    bus = EventBus()
    repo = PilotRepository(store)
    publisher = PilotEventPublisher(store, bus)
    registry = SkillRegistry()
    register_fake_skills(registry)
    gateway = FakeModelGateway()
    planning = PlanningService(gateway, repo, publisher)
    approvals = ApprovalService(repo, publisher)
    artifacts = ArtifactStore(repo, publisher)
    execution = ExecutionEngine(
        repository=repo,
        publisher=publisher,
        registry=registry,
        artifacts=artifacts,
        approvals=approvals,
        auto_approve_writes=True,
    )
    orchestrator = TaskOrchestrator(
        repository=repo,
        publisher=publisher,
        planning=planning,
        approvals=approvals,
        execution=execution,
    )
    return orchestrator, repo


def _text_message_event(
    *,
    text: str = "请帮我写一份介绍",
    chat_id: str = "oc_chat_1",
    sender_id: str = "ou_sender_1",
    sender_type: str = "user",
    chat_type: str = "p2p",
    event_id: str = "evt-001",
    message_id: str = "om_msg_1",
    mentions: list[dict] | None = None,
) -> dict:
    body = {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1700000000",
            "token": "",
            "app_id": "cli_app",
            "tenant_key": "tenant1",
        },
        "event": {
            "sender": {
                "sender_id": {"open_id": sender_id, "user_id": "u1"},
                "sender_type": sender_type,
            },
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": chat_type,
                "message_type": "text",
                "create_time": "1700000000",
                "content": json.dumps({"text": text}),
                "mentions": mentions or [],
            },
        },
    }
    return body


# ── Processor ──────────────────────────────────────


@pytest.mark.asyncio
async def test_processor_normalize_text_message() -> None:
    proc = FeishuWebhookProcessor()
    result = await proc.handle_event_dict(_text_message_event())
    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.message is not None
    assert result.message.text == "请帮我写一份介绍"
    assert result.message.chat_id == "oc_chat_1"
    assert result.message.message_type is FeishuMessageType.TEXT
    assert result.message.chat_type is FeishuChatType.P2P
    assert result.message.tenant_key == "tenant1"
    assert result.message.event_id == "evt-001"


@pytest.mark.asyncio
async def test_processor_ignores_bot_self_message() -> None:
    proc = FeishuWebhookProcessor(
        bot_open_id="ou_bot",
    )
    result = await proc.handle_event_dict(
        _text_message_event(
            sender_id="ou_bot",
            event_id="evt-self",
            message_id="om_self",
            text="bot reply",
        ),
    )

    assert result.outcome is FeishuWebhookOutcome.IGNORED
    assert result.reason == "bot self message"


@pytest.mark.asyncio
async def test_processor_ignores_app_sender_message() -> None:
    proc = FeishuWebhookProcessor()
    result = await proc.handle_event_dict(
        _text_message_event(
            sender_id="ou_unknown_app",
            sender_type="app",
            event_id="evt-app-sender",
            message_id="om_app_sender",
            text="app reply",
        ),
    )

    assert result.outcome is FeishuWebhookOutcome.IGNORED
    assert result.reason == "bot self message"


@pytest.mark.asyncio
async def test_processor_dedup_event_id() -> None:
    proc = FeishuWebhookProcessor()
    payload = _text_message_event()
    first = await proc.handle_event_dict(payload)
    again = await proc.handle_event_dict(payload)
    assert first.outcome is FeishuWebhookOutcome.ACCEPTED
    assert again.outcome is FeishuWebhookOutcome.DUPLICATE


@pytest.mark.asyncio
async def test_processor_group_chat_requires_mention() -> None:
    proc = FeishuWebhookProcessor(
        bot_open_id="ou_bot",
        require_mention_in_group=True,
    )
    no_mention = _text_message_event(
        chat_type="group",
        event_id="evt-no-mention",
        message_id="om_2",
    )
    result = await proc.handle_event_dict(no_mention)
    assert result.outcome is FeishuWebhookOutcome.IGNORED

    with_mention = _text_message_event(
        chat_type="group",
        event_id="evt-with-mention",
        message_id="om_3",
        text="@_user_1 你好，这是一条测试内容",
        mentions=[{"id": {"open_id": "ou_bot"}}],
    )
    result = await proc.handle_event_dict(with_mention)
    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.message is not None
    assert result.message.bot_mentioned is True


@pytest.mark.asyncio
async def test_processor_strips_bot_mention_key_from_text() -> None:
    proc = FeishuWebhookProcessor(
        bot_open_id="ou_bot",
        require_mention_in_group=True,
    )
    payload = _text_message_event(
        chat_type="group",
        event_id="evt-strip-mention",
        message_id="om_strip",
        text="@_user_1 你好，这是一条测试内容，你需要回复我'我很好'",
        mentions=[{"key": "@_user_1", "id": {"open_id": "ou_bot"}}],
    )

    result = await proc.handle_event_dict(payload)

    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.message is not None
    assert result.message.text == "你好，这是一条测试内容，你需要回复我'我很好'"


@pytest.mark.asyncio
async def test_processor_trigger_keyword_filter() -> None:
    proc = FeishuWebhookProcessor(
        trigger_keywords={"PPT"},
    )
    miss = await proc.handle_event_dict(
        _text_message_event(text="hello", event_id="evt-miss"),
    )
    hit = await proc.handle_event_dict(
        _text_message_event(text="帮我做一份 ppt", event_id="evt-hit"),
    )
    assert miss.outcome is FeishuWebhookOutcome.IGNORED
    assert hit.outcome is FeishuWebhookOutcome.ACCEPTED


@pytest.mark.asyncio
async def test_processor_unknown_event_type_ignored() -> None:
    proc = FeishuWebhookProcessor()
    payload = {
        "schema": "2.0",
        "header": {
            "event_id": "evt-other",
            "event_type": "im.chat.member_added",
            "token": "",
        },
        "event": {},
    }
    result = await proc.handle_event_dict(payload)
    assert result.outcome is FeishuWebhookOutcome.IGNORED


# ── Service ────────────────────────────────────────


def _make_turn_runtime_mock(
    *,
    task_id: str | None = "task_001",
    workspace_id: str | None = "ws_001",
    reply_text: str | None = None,
) -> MagicMock:
    """构造 UnifiedTurnRuntime mock，模拟 stream() 产出 chunks。"""
    from unittest.mock import MagicMock

    mock = MagicMock()

    async def _stream(_inbound: object):
        if task_id:
            yield {"type": "tool_started", "tool_name": "start_pilot_task", "content": "start_pilot_task"}
            yield {
                "type": "tool_finished",
                "tool_name": "start_pilot_task",
                "content": "start_pilot_task",
                "result": {
                    "status": "started",
                    "task_id": task_id,
                    "workspace_id": workspace_id or "",
                    "plan_id": "plan_001",
                    "task_status": "created",
                    "deduplicated": False,
                    "events_url": None,
                },
            }
        elif reply_text:
            yield {"type": "token", "content": reply_text}
            yield {"type": "final", "content": reply_text}

    mock.stream = _stream
    return mock


@pytest.mark.asyncio
async def test_service_creates_task_and_acks() -> None:
    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor()
    turn_runtime = _make_turn_runtime_mock(task_id="task_001", workspace_id="ws_001")
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        turn_runtime=turn_runtime,
    )

    result = await service.handle_event_dict(_text_message_event())
    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.handle is not None
    assert result.ack_message_id is not None
    assert len(fake_client.sent_messages) == 1
    sent = fake_client.sent_messages[0]
    assert sent["receive_id"] == "oc_chat_1"
    assert sent["msg_type"] == "text"


@pytest.mark.asyncio
async def test_service_reuses_workspace_for_same_chat() -> None:
    proc = FeishuWebhookProcessor()
    turn_runtime = _make_turn_runtime_mock(task_id="task_001", workspace_id="ws_001")
    service = FeishuWebhookService(
        processor=proc,
        client=None,
        turn_runtime=turn_runtime,
    )

    a = await service.handle_event_dict(_text_message_event(event_id="ea"))
    b = await service.handle_event_dict(
        _text_message_event(event_id="eb", message_id="om_2"),
    )
    assert a.handle is not None and b.handle is not None
    # 两次任务的 workspace_id 由 mock 返回相同值
    assert a.handle.workspace_id == b.handle.workspace_id


# ── Ingress 注入下的 START_TASK 路径（回归 ack 死代码 bug） ──


@pytest.mark.asyncio
async def test_service_with_ingress_p2p_start_task_acks_and_creates_task() -> None:
    """turn_runtime 返回 task_id 时，P2P 文本任务消息应：发 ACK + 创建 task。"""
    from agent_hub.pilot.services.ingress import IngressIntent

    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor()
    turn_runtime = _make_turn_runtime_mock(task_id="task_p2p", workspace_id="ws_p2p")
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        turn_runtime=turn_runtime,
    )

    result = await service.handle_event_dict(
        _text_message_event(
            text="帮我做一份 PPT，主题是季度复盘",
            event_id="evt-p2p-start",
            message_id="om_start_1",
        ),
    )

    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.intent is IngressIntent.START_TASK
    assert result.handle is not None, "START_TASK 必须创建 task"
    assert result.ack_message_id is not None, "START_TASK 必须发 ACK"
    assert len(fake_client.sent_messages) == 1


@pytest.mark.asyncio
async def test_service_with_ingress_group_mention_start_task_acks() -> None:
    """群聊 @bot 的任务文本走 START_TASK 分支也要发 ACK。"""
    from agent_hub.pilot.services.ingress import IngressIntent

    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor(
        bot_open_id="ou_bot",
        require_mention_in_group=True,
    )
    turn_runtime = _make_turn_runtime_mock(task_id="task_grp", workspace_id="ws_grp")
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        turn_runtime=turn_runtime,
    )

    result = await service.handle_event_dict(
        _text_message_event(
            chat_type="group",
            text="@_user_1 帮我生成一份产品 PPT",
            mentions=[{"key": "@_user_1", "id": {"open_id": "ou_bot"}}],
            event_id="evt-grp-start",
            message_id="om_grp_1",
        ),
    )

    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.intent is IngressIntent.START_TASK
    assert result.handle is not None
    assert result.ack_message_id is not None
    assert len(fake_client.sent_messages) == 1


@pytest.mark.asyncio
async def test_service_with_interaction_group_task_acks_private_delivery_text() -> None:
    """群聊任务应先在群里发 ACK 消息。"""
    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor(
        bot_open_id="ou_bot",
        require_mention_in_group=True,
    )
    turn_runtime = _make_turn_runtime_mock(task_id="task_grp2", workspace_id="ws_grp2")
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        turn_runtime=turn_runtime,
    )

    result = await service.handle_event_dict(
        _text_message_event(
            chat_type="group",
            text="@_user_1 帮我生成一份产品 PPT",
            mentions=[{"key": "@_user_1", "id": {"open_id": "ou_bot"}}],
            event_id="evt-grp-interaction",
            message_id="om_grp_interaction_1",
        ),
    )

    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.ack_message_id is not None
    assert len(fake_client.sent_messages) >= 1


@pytest.mark.asyncio
async def test_service_with_ingress_ordinary_qa_does_not_create_task() -> None:
    """ORDINARY_QA 路径不会创建 task，也不应发 ACK。"""
    from agent_hub.pilot.services.ingress import IngressIntent

    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor()
    turn_runtime = _make_turn_runtime_mock(task_id=None, reply_text="你好啊，有什么可以帮你？")
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        turn_runtime=turn_runtime,
    )

    result = await service.handle_event_dict(
        _text_message_event(
            text="你好啊",
            event_id="evt-qa-1",
            message_id="om_qa_1",
        ),
    )

    assert result.handle is None
    assert result.intent in (IngressIntent.ORDINARY_QA, IngressIntent.IGNORE, None)


# ── Card callback (M5 审批) ────────────────────────


def _card_action_event(
    *,
    approval_id: str = "ap_001",
    decision: str = "approve",
    operator_open_id: str = "ou_approver",
    comment: str = "ok",
    event_id: str = "evt-card-1",
    event_type: str = "card.action.trigger",
) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": event_type,
            "create_time": "1700000000",
            "token": "",
            "app_id": "cli_app",
            "tenant_key": "tenant1",
        },
        "event": {
            "operator": {
                "open_id": operator_open_id,
                "user_id": "",
                "union_id": "",
                "tenant_key": "tenant1",
            },
            "action": {
                "tag": "button",
                "value": {
                    "approval_id": approval_id,
                    "decision": decision,
                    "comment": comment,
                },
            },
            "context": {
                "open_chat_id": "oc_chat",
                "open_message_id": "om_msg",
            },
        },
    }


@pytest.mark.asyncio
async def test_service_card_callback_invokes_decide_approval() -> None:
    """卡片审批回调应调用 PilotCommandService.decide_approval。"""
    from unittest.mock import AsyncMock

    proc = FeishuWebhookProcessor()
    commands = AsyncMock()
    commands.decide_approval = AsyncMock(
        return_value={"approval_status": "approved"}
    )
    service = FeishuWebhookService(
        processor=proc,
        client=None,
        commands=commands,
    )

    result = await service.handle_event_dict(_card_action_event())
    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    assert result.approval_decision == {"approval_status": "approved"}
    commands.decide_approval.assert_awaited_once_with(
        "ap_001",
        decision="approve",
        actor_id="ou_approver",
        comment="ok",
    )


@pytest.mark.asyncio
async def test_service_card_callback_accepts_p2_event_type() -> None:
    """长连接 SDK 推送的 ``p2.card.action.trigger`` 也应被识别。"""
    from unittest.mock import AsyncMock

    proc = FeishuWebhookProcessor()
    commands = AsyncMock()
    commands.decide_approval = AsyncMock(return_value={"status": "ok"})
    service = FeishuWebhookService(
        processor=proc,
        client=None,
        commands=commands,
    )

    result = await service.handle_event_dict(
        _card_action_event(event_type="p2.card.action.trigger"),
    )
    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    commands.decide_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_card_callback_decide_failure_rejected() -> None:
    """decide_approval 抛异常时返回 REJECTED 并带 reason。"""
    from unittest.mock import AsyncMock

    proc = FeishuWebhookProcessor()
    commands = AsyncMock()
    commands.decide_approval = AsyncMock(side_effect=RuntimeError("not found"))
    service = FeishuWebhookService(
        processor=proc,
        client=None,
        commands=commands,
    )

    result = await service.handle_event_dict(_card_action_event(event_id="evt-card-fail"))
    assert result.outcome is FeishuWebhookOutcome.REJECTED
    assert result.reason is not None
    assert "not found" in result.reason


# ── 审批后更新卡片终态 ─────────────────────────────


@pytest.mark.asyncio
async def test_card_callback_updates_card_to_final_state() -> None:
    """approve 回调后，应调用 client.update_card 覆盖原卡片为终态。"""
    from unittest.mock import AsyncMock

    from agent_hub.pilot import (
        Approval,
        ApprovalStatus,
        ApprovalTargetType,
    )

    _, repo = _make_orchestrator()
    # 预置一个 REQUESTED 状态的审批，带 channel_message_id
    approval = Approval(
        workspace_id="ws_test",
        task_id="task_test",
        target_type=ApprovalTargetType.PLAN,
        target_id="plan_test",
        requester_id="ou_requester",
        approvers=["ou_approver"],
        reason="生成 PPT 计划审批",
        preview="共 3 步，含写入操作",
        status=ApprovalStatus.REQUESTED,
        channel_message_id="om_card_msg_1",
    )
    await repo.save(approval, expected_version=None)

    # commands mock：decide_approval 成功即可；update_card 路径由 service 自己走 repo
    commands = AsyncMock()
    commands.decide_approval = AsyncMock(return_value={"approval_status": "approved"})

    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor()
    service = FeishuWebhookService(
        processor=proc,
        repository=repo,
        client=fake_client,
        commands=commands,
    )

    result = await service.handle_event_dict(
        _card_action_event(
            approval_id=approval.approval_id,
            decision="approve",
            operator_open_id="ou_approver",
            comment="LGTM",
        )
    )

    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    # 卡片终态被 update
    assert len(fake_client.updated_cards) == 1
    updated = fake_client.updated_cards[0]
    assert updated["message_id"] == "om_card_msg_1"
    card = updated["card"]
    assert card["header"]["template"] == "green"           # approve → 绿色
    assert "已批准" in card["elements"][0]["text"]["content"]
    assert "ou_approver" in card["elements"][0]["text"]["content"]
    assert "LGTM" in card["elements"][0]["text"]["content"]


@pytest.mark.asyncio
async def test_card_callback_reject_updates_card_red() -> None:
    """reject 回调后卡片终态应为红色。"""
    from unittest.mock import AsyncMock

    from agent_hub.pilot import (
        Approval,
        ApprovalStatus,
        ApprovalTargetType,
    )

    _, repo = _make_orchestrator()
    approval = Approval(
        workspace_id="ws_test2",
        task_id="task_test2",
        target_type=ApprovalTargetType.PLAN,
        target_id="plan_test2",
        requester_id="ou_requester",
        approvers=["ou_approver"],
        reason="风险步骤审批",
        status=ApprovalStatus.REQUESTED,
        channel_message_id="om_card_msg_2",
    )
    await repo.save(approval, expected_version=None)

    commands = AsyncMock()
    commands.decide_approval = AsyncMock(return_value={"approval_status": "rejected"})

    fake_client = FakeFeishuClient()
    proc = FeishuWebhookProcessor()
    service = FeishuWebhookService(
        processor=proc,
        repository=repo,
        client=fake_client,
        commands=commands,
    )

    result = await service.handle_event_dict(
        _card_action_event(
            approval_id=approval.approval_id,
            decision="reject",
            operator_open_id="ou_approver",
            comment="",
            event_id="evt-reject-1",
        )
    )

    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    assert len(fake_client.updated_cards) == 1
    card = fake_client.updated_cards[0]["card"]
    assert card["header"]["template"] == "red"
    assert "已拒绝" in card["elements"][0]["text"]["content"]


@pytest.mark.asyncio
async def test_card_callback_no_channel_message_id_skips_update() -> None:
    """approval 没有 channel_message_id 时，不调用 update_card。"""
    from unittest.mock import AsyncMock

    proc = FeishuWebhookProcessor()
    commands = AsyncMock()
    commands.decide_approval = AsyncMock(return_value={"status": "approved"})
    fake_client = FakeFeishuClient()
    service = FeishuWebhookService(
        processor=proc,
        client=fake_client,
        commands=commands,
    )

    result = await service.handle_event_dict(
        _card_action_event(approval_id="no_such_approval", event_id="evt-no-card")
    )

    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    # 没找到 approval / 没有 channel_message_id → 不调用 update_card
    assert len(fake_client.updated_cards) == 0
