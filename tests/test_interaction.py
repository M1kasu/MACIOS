"""``/api/interactions`` 统一入口测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def interactions_app() -> Iterator[FastAPI]:
    """构造仅含 /api/interactions 路由的最小 FastAPI 应用。"""
    from agent_hub.api.interactions_routes import build_interactions_router
    from agent_hub.api.pilot_runtime import build_pilot_runtime
    from agent_hub.config.settings import Settings
    from agent_hub.contracts.turn import TurnIntent, TurnResult, TurnStatus

    settings = Settings(
        api_keys=["test-key"],
        pilot_enabled=True,
        pilot_store_path="",
        pilot_demo_mode=True,
        pilot_auto_approve_writes=False,
        pilot_admin_token="admin-secret",
        public_base_url="",
        feishu_enabled=False,
        pilot_use_real_gateway=False,
        pilot_use_real_chain=False,
    )
    runtime = build_pilot_runtime(settings)

    mock_turn_runtime = MagicMock()

    async def _mock_handle(inbound: object) -> TurnResult:
        text = getattr(inbound, "text", "") or ""
        trace_id = getattr(inbound, "trace_id", "trace-mock")
        src = getattr(inbound, "source_context", None)

        from agent_hub.contracts.identity import SourceChatType

        if src and getattr(src, "chat_type", None) is SourceChatType.GROUP and not src.is_at_bot:
            return TurnResult(trace_id=trace_id)
        if not text:
            return TurnResult(trace_id=trace_id)
        if "blocked" in text:
            return TurnResult(
                trace_id=trace_id,
                reply_text="请求已被拦截",
                intent=TurnIntent.BLOCKED,
                status=TurnStatus.BLOCKED,
            )
        if "进度" in text:
            return TurnResult(
                trace_id=trace_id,
                reply_text="任务正在运行",
                intent=TurnIntent.PROGRESS_QUERY,
            )
        if any(kw in text for kw in ("PPT", "ppt", "汇报", "任务")):
            return TurnResult(
                trace_id=trace_id,
                task_id="t1",
                workspace_id="ws1",
                intent=TurnIntent.START_TASK,
            )
        return TurnResult(
            trace_id=trace_id,
            reply_text=f"关于「{text}」的回答",
            intent=TurnIntent.ORDINARY_QA,
        )

    mock_turn_runtime.handle = AsyncMock(side_effect=_mock_handle)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await runtime.aclose()

    fa = FastAPI(lifespan=lifespan)
    fa.include_router(build_interactions_router(runtime, mock_turn_runtime))
    yield fa


@pytest.fixture()
def ic_client(interactions_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(interactions_app) as c:
        yield c


def _post(client: TestClient, **overrides: object) -> dict:
    body: dict = {
        "user_id": "tester",
        "text": "RAG 是什么？",
    }
    body.update(overrides)
    resp = client.post("/api/interactions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_interactions_ordinary_qa_returns_reply(ic_client: TestClient) -> None:
    data = _post(ic_client, text="RAG 是什么？")
    assert data["intent"] == "ordinary_qa"
    assert "trace_id" in data


def test_interactions_ignore_empty_text(ic_client: TestClient) -> None:
    data = _post(ic_client, text="")
    assert data["intent"] == "ignore"


def test_interactions_start_task_returns_intent(ic_client: TestClient) -> None:
    data = _post(ic_client, text="帮我做一份季度汇报 PPT")
    assert data["intent"] == "start_task"


def test_interactions_progress_query_returns_intent(ic_client: TestClient) -> None:
    data = _post(ic_client, text="看一下进度")
    assert data["intent"] == "progress_query"
    assert data["reply_text"] == "任务正在运行"


def test_interactions_blocked_is_first_class_intent(ic_client: TestClient) -> None:
    data = _post(ic_client, text="blocked")
    assert data["intent"] == "blocked"
    assert data["reply_text"] == "请求已被拦截"


def test_interactions_trace_id_passthrough(ic_client: TestClient) -> None:
    data = _post(ic_client, text="你好", trace_id="my-trace-abc")
    assert data["trace_id"] == "my-trace-abc"


def test_interactions_group_without_mention_ignored(ic_client: TestClient) -> None:
    data = _post(
        ic_client,
        text="你好大家",
        chat_type="group",
        is_at_bot=False,
    )
    assert data["intent"] == "ignore"


def test_interactions_unknown_role_defaults_to_user(ic_client: TestClient) -> None:
    resp = ic_client.post(
        "/api/interactions",
        json={"user_id": "u1", "role": "unknown_role", "text": "你好"},
    )
    assert resp.status_code == 200
