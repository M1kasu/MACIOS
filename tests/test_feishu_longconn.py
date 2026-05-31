"""FeishuLongConnClient 单元测试。

使用 unittest.mock 替换 lark_oapi，完全离线运行。
覆盖：
- _to_webhook_dict 转换逻辑
- start() 在缺少 lark_oapi 时优雅降级
- start() 成功启动后台线程
- aclose() 停止后台线程并调用 ws_client.stop()
- _run_in_thread → 事件触发 → service.handle_event_dict() 被调用
- FeishuWebhookProcessor.handle_event_dict() 跳过验签直接解析
"""

from __future__ import annotations

import asyncio
import threading
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_hub.connectors.feishu.longconn import (
    FeishuLongConnClient,
    _to_card_action_dict,
    _to_webhook_dict,
)
from agent_hub.connectors.feishu.models import FeishuWebhookOutcome
from agent_hub.connectors.feishu.webhook import FeishuWebhookProcessor

# ── _to_webhook_dict ──────────────────────────────


def _make_lark_event(
    *,
    event_id: str = "evt-001",
    event_type: str = "im.message.receive_v1",
    tenant_key: str = "tenant-1",
    app_id: str = "app-1",
    open_id: str = "ou_sender",
    chat_id: str = "oc_chat",
    message_id: str = "om_msg",
    chat_type: str = "group",
    message_type: str = "text",
    content: str = '{"text":"hello"}',
    mentions: list | None = None,
) -> MagicMock:
    """构造一个模拟 lark-oapi im.message.receive_v1 事件对象。"""
    header = MagicMock()
    header.event_id = event_id
    header.event_type = event_type
    header.tenant_key = tenant_key
    header.app_id = app_id

    sender_id = MagicMock()
    sender_id.open_id = open_id
    sender_id.user_id = ""
    sender_id.union_id = ""

    sender = MagicMock()
    sender.sender_id = sender_id
    sender.sender_type = "user"

    message = MagicMock()
    message.message_id = message_id
    message.chat_id = chat_id
    message.chat_type = chat_type
    message.message_type = message_type
    message.content = content

    mock_mentions: list = []
    for m in (mentions or []):
        mid = MagicMock()
        mid.open_id = m.get("open_id", "")
        mm = MagicMock()
        mm.key = m.get("key", "@_user_1")
        mm.id = mid
        mm.name = m.get("name", "")
        mock_mentions.append(mm)
    message.mentions = mock_mentions

    event = MagicMock()
    event.sender = sender
    event.message = message

    data = MagicMock()
    data.header = header
    data.event = event
    return data


class TestToWebhookDict:
    def test_basic_conversion(self) -> None:
        data = _make_lark_event()
        result = _to_webhook_dict(data)
        assert result is not None
        assert result["header"]["event_id"] == "evt-001"
        assert result["header"]["event_type"] == "im.message.receive_v1"
        assert result["header"]["tenant_key"] == "tenant-1"
        assert result["header"]["token"] == ""  # 长连接不需要 token
        assert result["event"]["message"]["chat_id"] == "oc_chat"
        assert result["event"]["sender"]["sender_id"]["open_id"] == "ou_sender"

    def test_mentions_converted(self) -> None:
        data = _make_lark_event(
            mentions=[{"key": "@_user_1", "open_id": "ou_bot", "name": "Bot"}]
        )
        result = _to_webhook_dict(data)
        assert result is not None
        mentions = result["event"]["message"]["mentions"]
        assert len(mentions) == 1
        assert mentions[0]["id"]["open_id"] == "ou_bot"
        assert mentions[0]["key"] == "@_user_1"

    def test_missing_header_returns_none(self) -> None:
        data = MagicMock()
        data.header = None
        data.event = MagicMock()
        assert _to_webhook_dict(data) is None

    def test_missing_event_returns_none(self) -> None:
        data = MagicMock()
        data.header = MagicMock()
        data.event = None
        assert _to_webhook_dict(data) is None


# ── FeishuWebhookProcessor.handle_event_dict ─────────


@pytest.mark.asyncio
async def test_handle_event_dict_basic() -> None:
    processor = FeishuWebhookProcessor(
        bot_open_id="",
        require_mention_in_group=False,
    )
    data = _make_lark_event(chat_type="p2p")
    payload = _to_webhook_dict(data)
    assert payload is not None
    result = await processor.handle_event_dict(payload)
    assert result.outcome is FeishuWebhookOutcome.ACCEPTED
    assert result.message is not None
    assert result.message.text == "hello"


@pytest.mark.asyncio
async def test_handle_event_dict_dedup() -> None:
    processor = FeishuWebhookProcessor(require_mention_in_group=False)
    data = _make_lark_event(event_id="evt-dup", chat_type="p2p")
    payload = _to_webhook_dict(data)
    assert payload is not None
    r1 = await processor.handle_event_dict(payload)
    r2 = await processor.handle_event_dict(payload)
    assert r1.outcome is FeishuWebhookOutcome.ACCEPTED
    assert r2.outcome is FeishuWebhookOutcome.DUPLICATE


# ── FeishuLongConnClient ──────────────────────────


def _make_mock_lark_module() -> types.ModuleType:
    """构造一个最小化的 lark_oapi mock 模块。"""
    mod = types.ModuleType("lark_oapi")
    mod.__path__ = []  # 让 import machinery 把它视为 package
    builder = MagicMock()
    handler_builder = MagicMock()
    handler_builder.register_p2_im_message_receive_v1.return_value = handler_builder
    handler_builder.register_p2_card_action_trigger.return_value = handler_builder
    handler_builder.build.return_value = MagicMock()
    builder.return_value = handler_builder
    mod.EventDispatcherHandler = MagicMock()
    mod.EventDispatcherHandler.builder = builder

    ws_mod = types.ModuleType("lark_oapi.ws")
    ws_client_mod = types.ModuleType("lark_oapi.ws.client")
    ws_client_mod.loop = None
    ws_client_instance = MagicMock()
    ws_client_instance.start = MagicMock(side_effect=lambda: None)  # 立即返回
    ws_client_instance.stop = MagicMock()
    ws_mod.Client = MagicMock(return_value=ws_client_instance)
    ws_mod.client = ws_client_mod
    mod.ws = ws_mod

    # mock lark_oapi.event.callback.model.p2_card_action_trigger
    event_mod = types.ModuleType("lark_oapi.event")
    event_mod.__path__ = []
    cb_mod = types.ModuleType("lark_oapi.event.callback")
    cb_mod.__path__ = []
    cb_model_mod = types.ModuleType("lark_oapi.event.callback.model")
    cb_model_mod.__path__ = []
    p2_card_mod = types.ModuleType(
        "lark_oapi.event.callback.model.p2_card_action_trigger"
    )

    class _FakeCardResp:
        """与 SDK ``P2CardActionTriggerResponse`` 等价的最小 stub。"""

        def __init__(self, payload: dict) -> None:  # noqa: D401
            self.payload = payload

    p2_card_mod.P2CardActionTriggerResponse = _FakeCardResp
    mod.event = event_mod
    event_mod.callback = cb_mod
    cb_mod.model = cb_model_mod
    cb_model_mod.p2_card_action_trigger = p2_card_mod
    return mod


def _mock_lark_modules(lark_mod: types.ModuleType) -> dict[str, types.ModuleType]:
    return {
        "lark_oapi": lark_mod,
        "lark_oapi.ws": lark_mod.ws,
        "lark_oapi.ws.client": lark_mod.ws.client,
        "lark_oapi.event": lark_mod.event,
        "lark_oapi.event.callback": lark_mod.event.callback,
        "lark_oapi.event.callback.model": lark_mod.event.callback.model,
        "lark_oapi.event.callback.model.p2_card_action_trigger": (
            lark_mod.event.callback.model.p2_card_action_trigger
        ),
    }


@pytest.mark.asyncio
async def test_start_missing_lark_oapi() -> None:
    """缺少 lark_oapi 时 start() 不应抛异常，只记录错误。"""
    svc = AsyncMock()
    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )
    with patch.dict("sys.modules", {"lark_oapi": None}):
        await client.start()
    # 后台线程未创建
    assert client._thread is None


@pytest.mark.asyncio
async def test_start_and_aclose() -> None:
    """start() 创建后台线程；aclose() 停止 ws_client 并等待线程结束。"""
    svc = AsyncMock()
    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )

    lark_mod = _make_mock_lark_module()
    ws_client_instance = lark_mod.ws.Client.return_value

    # _run_in_thread 使用 stop_event 控制退出；我们立即置位让线程自然结束
    def _blocking_run(loop: asyncio.AbstractEventLoop) -> None:
        client._ws_client = ws_client_instance
        # 模拟 start() 立即返回（非长期阻塞）
        client._stop_event.wait(timeout=0.5)

    with patch.dict("sys.modules", _mock_lark_modules(lark_mod)), \
         patch.object(client, "_run_in_thread", side_effect=_blocking_run):
        await client.start()
        assert client._thread is not None
        client._ws_client = ws_client_instance
        await client.aclose()

    ws_client_instance.stop.assert_called_once()
    assert client._thread is None


@pytest.mark.asyncio
async def test_event_dispatched_to_service() -> None:
    """事件经 _run_in_thread 处理后应调用 service.handle_event_dict()。"""
    svc = AsyncMock()
    svc.handle_event_dict = AsyncMock(return_value=MagicMock())

    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )

    lark_mod = _make_mock_lark_module()
    captured_handler: list = []

    # 截获 register_p2_im_message_receive_v1 注册的回调
    original_builder = lark_mod.EventDispatcherHandler.builder

    def _capture_builder(enc_key: str, verify_token: str) -> MagicMock:
        hb = original_builder(enc_key, verify_token)
        def _register(fn):  # noqa: ANN001, ANN202
            captured_handler.append(fn)
            return hb
        hb.register_p2_im_message_receive_v1 = _register
        return hb

    lark_mod.EventDispatcherHandler.builder = _capture_builder

    loop = asyncio.get_event_loop()
    stop = threading.Event()

    def _blocking(loop_: asyncio.AbstractEventLoop) -> None:  # noqa: ANN001
        # 让 _run_in_thread 能够执行到 ws_client.start()
        client._stop_event.wait(timeout=0.5)

    with patch.dict("sys.modules", _mock_lark_modules(lark_mod)), \
         patch.object(client, "_run_in_thread", wraps=client._run_in_thread):
        # 直接在线程中执行以捕获回调
        t = threading.Thread(
            target=client._run_in_thread, args=(loop,), daemon=True
        )
        t.start()
        # 等一小会让线程注册 handler
        await asyncio.sleep(0.1)
        client._stop_event.set()
        t.join(timeout=2)

    # 用捕获到的 handler 发送一条事件
    if captured_handler:
        event_data = _make_lark_event(chat_type="p2p", event_id="evt-x")
        captured_handler[0](event_data)
        # run_coroutine_threadsafe 发送到 loop，等待
        await asyncio.sleep(0.1)
        svc.handle_event_dict.assert_called_once()


@pytest.mark.asyncio
async def test_im_event_handler_does_not_block_on_slow_service() -> None:
    """IM 事件只投递到主循环，不等待长耗时任务完成。"""
    svc = AsyncMock()

    async def _slow_handle(_: dict) -> MagicMock:
        await asyncio.sleep(0.2)
        return MagicMock()

    svc.handle_event_dict = AsyncMock(side_effect=_slow_handle)

    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )

    lark_mod = _make_mock_lark_module()
    captured_im: list = []
    original_builder = lark_mod.EventDispatcherHandler.builder

    def _capture_builder(enc_key: str, verify_token: str) -> MagicMock:
        hb = original_builder(enc_key, verify_token)

        def _reg_im(fn):  # noqa: ANN001, ANN202
            captured_im.append(fn)
            return hb

        hb.register_p2_im_message_receive_v1 = _reg_im
        hb.register_p2_card_action_trigger = lambda fn: hb
        return hb

    lark_mod.EventDispatcherHandler.builder = _capture_builder
    loop = asyncio.get_event_loop()

    with patch.dict("sys.modules", _mock_lark_modules(lark_mod)):
        t = threading.Thread(
            target=client._run_in_thread, args=(loop,), daemon=True
        )
        t.start()
        await asyncio.sleep(0.1)
        client._stop_event.set()
        t.join(timeout=2)

    assert captured_im
    event_data = _make_lark_event(chat_type="p2p", event_id="evt-slow")
    started = time.perf_counter()
    captured_im[0](event_data)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    for _ in range(30):
        await asyncio.sleep(0.02)
        if svc.handle_event_dict.await_count:
            break
    svc.handle_event_dict.assert_awaited_once()


# ── 卡片回传交互 (card.action.trigger) ─────────────


def _make_lark_card_action_event(
    *,
    event_id: str = "evt-card-1",
    event_type: str = "p2.card.action.trigger",
    tenant_key: str = "tenant-1",
    app_id: str = "app-1",
    operator_open_id: str = "ou_approver",
    approval_id: str = "ap_001",
    decision: str = "approved",
    comment: str = "ok",
    open_chat_id: str = "oc_chat",
    open_message_id: str = "om_msg",
    raw_value: dict | None = None,
) -> MagicMock:
    """构造一个模拟 lark-oapi P2CardActionTrigger 事件对象。"""
    header = MagicMock()
    header.event_id = event_id
    header.event_type = event_type
    header.tenant_key = tenant_key
    header.app_id = app_id

    operator = MagicMock()
    operator.open_id = operator_open_id
    operator.union_id = ""
    operator.user_id = ""
    operator.tenant_key = tenant_key

    action = MagicMock()
    action.tag = "button"
    action.value = raw_value if raw_value is not None else {
        "approval_id": approval_id,
        "decision": decision,
        "comment": comment,
    }

    context = MagicMock()
    context.open_chat_id = open_chat_id
    context.open_message_id = open_message_id

    event = MagicMock()
    event.operator = operator
    event.action = action
    event.context = context

    data = MagicMock()
    data.header = header
    data.event = event
    return data


class TestToCardActionDict:
    def test_basic_conversion(self) -> None:
        data = _make_lark_card_action_event()
        result = _to_card_action_dict(data)
        assert result is not None
        # SDK 类型 p2.card.action.trigger 应被规范化为开放平台命名
        assert result["header"]["event_type"] == "card.action.trigger"
        assert result["header"]["event_id"] == "evt-card-1"
        assert result["event"]["operator"]["open_id"] == "ou_approver"
        assert result["event"]["action"]["value"] == {
            "approval_id": "ap_001",
            "decision": "approved",
            "comment": "ok",
        }
        assert result["event"]["context"]["open_chat_id"] == "oc_chat"
        assert result["event"]["context"]["open_message_id"] == "om_msg"

    def test_missing_header_returns_none(self) -> None:
        data = MagicMock()
        data.header = None
        data.event = MagicMock()
        assert _to_card_action_dict(data) is None


@pytest.mark.asyncio
async def test_card_payload_routes_to_card_callback() -> None:
    """卡片 payload 经 webhook 处理器后 outcome 应为 CARD_CALLBACK。"""
    processor = FeishuWebhookProcessor(require_mention_in_group=False)
    data = _make_lark_card_action_event(event_id="evt-card-route")
    payload = _to_card_action_dict(data)
    assert payload is not None
    result = await processor.handle_event_dict(payload)
    assert result.outcome is FeishuWebhookOutcome.CARD_CALLBACK
    assert result.card_callback is not None
    assert result.card_callback.action_value.approval_id == "ap_001"
    assert result.card_callback.action_value.decision == "approved"
    assert result.card_callback.operator_open_id == "ou_approver"


@pytest.mark.asyncio
async def test_card_action_dispatched_and_returns_toast() -> None:
    """长连接卡片 handler 应调用 service.handle_event_dict 并返回 toast 响应。"""
    from agent_hub.connectors.feishu.service import FeishuAckResult

    svc = AsyncMock()
    svc.handle_event_dict = AsyncMock(
        return_value=FeishuAckResult(
            outcome=FeishuWebhookOutcome.CARD_CALLBACK,
            approval_decision={"approval_status": "approved"},
            card_to_replace={"header": {"title": {"content": "decided"}}},
        )
    )

    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )

    lark_mod = _make_mock_lark_module()
    captured_im: list = []
    captured_card: list = []

    original_builder = lark_mod.EventDispatcherHandler.builder

    def _capture_builder(enc_key: str, verify_token: str) -> MagicMock:
        hb = original_builder(enc_key, verify_token)

        def _reg_im(fn):  # noqa: ANN001, ANN202
            captured_im.append(fn)
            return hb

        def _reg_card(fn):  # noqa: ANN001, ANN202
            captured_card.append(fn)
            return hb

        hb.register_p2_im_message_receive_v1 = _reg_im
        hb.register_p2_card_action_trigger = _reg_card
        return hb

    lark_mod.EventDispatcherHandler.builder = _capture_builder

    loop = asyncio.get_event_loop()

    with patch.dict("sys.modules", _mock_lark_modules(lark_mod)):
        t = threading.Thread(
            target=client._run_in_thread, args=(loop,), daemon=True
        )
        t.start()
        await asyncio.sleep(0.1)
        client._stop_event.set()
        t.join(timeout=2)

    assert captured_card, "card.action.trigger handler 未注册"

    # 触发卡片事件，handler 内部会通过 run_coroutine_threadsafe 把任务交给 loop
    event_data = _make_lark_card_action_event(event_id="evt-card-dispatch")

    # handler 会阻塞等待 future.result()；放到独立线程执行以便我们能 yield 到事件循环
    response_holder: dict = {}

    def _invoke() -> None:
        response_holder["resp"] = captured_card[0](event_data)

    invoke_thread = threading.Thread(target=_invoke, daemon=True)
    invoke_thread.start()
    # 让事件循环运行 svc.handle_event_dict
    for _ in range(50):
        await asyncio.sleep(0.02)
        if not invoke_thread.is_alive():
            break
    invoke_thread.join(timeout=2)

    svc.handle_event_dict.assert_called_once()
    resp = response_holder.get("resp")
    assert resp is not None
    # _FakeCardResp 把 toast payload 暴露为 .payload
    payload = getattr(resp, "payload", resp)
    assert payload["toast"]["type"] == "info"
    assert payload["toast"]["content"] == "审批已提交"
    # card_to_replace 必须同步塞进响应，避免飞书客户端回退到原审批卡片
    assert payload["card"] == {
        "type": "raw",
        "data": {"header": {"title": {"content": "decided"}}},
    }


@pytest.mark.asyncio
async def test_card_action_failure_returns_error_toast() -> None:
    """service 返回非 CARD_CALLBACK 时 toast 应为 error。"""
    from agent_hub.connectors.feishu.service import FeishuAckResult

    svc = AsyncMock()
    svc.handle_event_dict = AsyncMock(
        return_value=FeishuAckResult(
            outcome=FeishuWebhookOutcome.IGNORED,
            reason="approval not found",
        )
    )

    client = FeishuLongConnClient(
        app_id="app-1", app_secret="secret", webhook_service=svc
    )

    lark_mod = _make_mock_lark_module()
    captured_card: list = []
    original_builder = lark_mod.EventDispatcherHandler.builder

    def _capture_builder(enc_key: str, verify_token: str) -> MagicMock:
        hb = original_builder(enc_key, verify_token)
        hb.register_p2_im_message_receive_v1 = lambda fn: hb
        def _reg_card(fn):  # noqa: ANN001, ANN202
            captured_card.append(fn)
            return hb
        hb.register_p2_card_action_trigger = _reg_card
        return hb

    lark_mod.EventDispatcherHandler.builder = _capture_builder
    loop = asyncio.get_event_loop()

    with patch.dict("sys.modules", _mock_lark_modules(lark_mod)):
        t = threading.Thread(
            target=client._run_in_thread, args=(loop,), daemon=True
        )
        t.start()
        await asyncio.sleep(0.1)
        client._stop_event.set()
        t.join(timeout=2)

    assert captured_card
    event_data = _make_lark_card_action_event(event_id="evt-card-fail")
    response_holder: dict = {}

    def _invoke() -> None:
        response_holder["resp"] = captured_card[0](event_data)

    invoke_thread = threading.Thread(target=_invoke, daemon=True)
    invoke_thread.start()
    for _ in range(50):
        await asyncio.sleep(0.02)
        if not invoke_thread.is_alive():
            break
    invoke_thread.join(timeout=2)

    resp = response_holder.get("resp")
    payload = getattr(resp, "payload", resp)
    assert payload["toast"]["type"] == "error"
    assert "approval not found" in payload["toast"]["content"]
