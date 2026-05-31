"""FastAPI HTTP 路由。

提供统一的 REST API 入口，将 HTTP 请求转发到 :class:`AgentPipeline`。

启动方式::

    uvicorn agent_hub.api.routes:app --reload --port 8080
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from agent_hub.api.pilot_routes import build_pilot_router
from agent_hub.api.pilot_runtime import PilotRuntime, build_pilot_runtime
from agent_hub.api.rag_routes import build_rag_router
from agent_hub.config.settings import Settings, get_settings
from agent_hub.core.enums import UserRole
from agent_hub.core.models import SourceContext, TaskInput, UserContext
from agent_hub.core.pipeline import AgentPipeline
from agent_hub.core.trace_store import InMemoryTraceStore, get_trace_store, set_trace_store
from agent_hub.core.tracer import init_tracer

logger = structlog.get_logger(__name__)

# ── 全局状态 ──────────────────────────────────────────

_pipeline: AgentPipeline | None = None
_settings: Settings | None = None
_pilot_runtime: PilotRuntime | None = None


def _get_pipeline() -> AgentPipeline:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline 未初始化")
    return _pipeline


def get_pilot_runtime() -> PilotRuntime:
    if _pilot_runtime is None:
        raise HTTPException(status_code=503, detail="Pilot runtime 未初始化")
    return _pilot_runtime


def _resolve_dashboard_dir(static_dir: str) -> Path | None:
    """解析 Dashboard 静态目录。

    支持绝对路径、相对当前工作目录路径，以及源码项目根目录下的路径。
    返回 None 表示显式关闭静态 Dashboard 挂载。
    """
    configured = static_dir.strip()
    if not configured:
        return None

    path = Path(configured).expanduser()
    if path.is_absolute():
        return path

    candidates = [
        Path.cwd() / path,
        Path(__file__).resolve().parents[3] / path,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


# ── Lifespan ─────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化 Pipeline / Pilot，关闭时清理资源。"""
    global _pipeline, _settings, _pilot_runtime  # noqa: PLW0603
    _settings = get_settings()
    init_tracer("agent-hub-api")
    # 注册进程内 TraceStore（供 /trace/{id} 查询）
    set_trace_store(InMemoryTraceStore())
    _pipeline = AgentPipeline(_settings)
    if not getattr(app.state, "rag_router_mounted", False):
        app.include_router(build_rag_router(lambda: _get_pipeline().rag_pipeline))
        app.state.rag_router_mounted = True

    if _settings.pilot_enabled:
        _pilot_runtime = build_pilot_runtime(_settings, pipeline=_pipeline)
        _pipeline.attach_pilot_runtime(_pilot_runtime)
        app.include_router(build_pilot_router(_pilot_runtime))
        from agent_hub.api.interactions_routes import build_interactions_router
        app.include_router(build_interactions_router(_pilot_runtime))
        if (
            _settings.feishu_enabled
            and _pilot_runtime.feishu_webhook_service is not None
            and _pilot_runtime.feishu_long_conn is not None
        ):
            # 长连接模式：主动向飞书建立 WebSocket，无需公网 webhook
            await _pilot_runtime.feishu_long_conn.start()
            logger.info(
                "feishu_long_conn_started",
                app_id=_settings.feishu_app_id,
            )
        # 静态 Dashboard：默认同源挂载 /dashboard，部署时可通过
        # DASHBOARD_STATIC_DIR 指向构建产物目录。
        from fastapi.staticfiles import StaticFiles

        web_dir = _resolve_dashboard_dir(_settings.dashboard_static_dir)
        if web_dir is not None and web_dir.is_dir():
            app.mount(
                "/dashboard",
                StaticFiles(directory=str(web_dir), html=True),
                name="pilot-dashboard",
            )
            logger.info(
                "pilot_dashboard_mounted",
                path=str(web_dir),
                url=_settings.dashboard_url,
            )
        elif web_dir is not None:
            logger.warning("pilot_dashboard_missing", path=str(web_dir))
        logger.info("pilot_runtime_started")

    logger.info("api_started")
    yield
    if _pilot_runtime is not None:
        await _pilot_runtime.aclose()
    if _pipeline is not None:
        await _pipeline.rag_pipeline.close()
    _pipeline = None
    _pilot_runtime = None
    logger.info("api_stopped")


# ── FastAPI App ──────────────────────────────────────

app = FastAPI(
    title="Agent-Hub API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 从配置读取
_cors_settings = get_settings()
_origins = [o.strip() for o in _cors_settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── 请求 / 响应模型 ─────────────────────────────────


class ChatRequest(BaseModel):
    """对话请求体。"""
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="用户消息")
    user_id: str = Field(..., description="用户ID")
    role: str = Field(default="user", description="角色：admin / user")
    source_context: SourceContext = Field(..., description="消息来源上下文")
    trace_id: str | None = Field(default=None, description="链路追踪ID")


class ChatResponse(BaseModel):
    """对话响应体。"""

    trace_id: str
    response: str
    status: str
    total_duration_ms: int


# ── 路由 ─────────────────────────────────────────────


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """统一对话入口。"""
    pipeline = _get_pipeline()

    user_ctx = UserContext(
        user_id=req.user_id,
        role=UserRole(req.role),
    )
    source_context = req.source_context.model_copy(
        update={"sender_id": req.source_context.sender_id or req.user_id}
    )

    task_input = TaskInput(
        trace_id=req.trace_id or str(uuid.uuid4()),
        user_context=user_ctx,
        source_context=source_context,
        raw_message=req.message,
        attachments=[],
    )

    output = await pipeline.run(task_input)

    return ChatResponse(
        trace_id=output.trace_id,
        response=output.response,
        status=output.status,
        total_duration_ms=output.total_duration_ms,
    )


@app.get("/health")
async def health() -> dict[str, object]:
    """健康检查。"""
    settings = _settings or get_settings()
    return {
        "status": "ok",
        "pipeline": _pipeline is not None,
        "pilot": _pilot_runtime is not None,
        "public_base_url": settings.public_base_url,
        "dashboard_url": settings.dashboard_url,
    }


@app.get("/tools")
async def list_tools(role: str = "user") -> dict[str, list[dict[str, str]]]:
    """列出当前用户可用的工具。"""
    pipeline = _get_pipeline()
    tools = pipeline._registry.list_tools_for_user(role)
    return {"tools": [{"name": t.name, "description": t.description} for t in tools]}


@app.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, object]:
    """查询链路追踪记录。

    从进程内 ``InMemoryTraceStore`` 读取该 ``trace_id`` 下的所有 Span，
    按 ``start_ms`` 升序返回。未启用 / 未命中时返回空列表。
    """
    store = get_trace_store()
    if store is None:
        return {"trace_id": trace_id, "status": "disabled", "spans": []}
    spans = store.get_trace(trace_id)
    if spans is None:
        return {"trace_id": trace_id, "status": "not_found", "spans": []}
    return {"trace_id": trace_id, "status": "ok", "spans": spans}


# ── SSE 流式端点 ─────────────────────────────────────


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    """SSE 流式对话入口。

    返回 Server-Sent Events 流，逐 token 推送 LLM 生成结果。
    """
    from agent_hub.api.streaming import sse_generator

    pipeline = _get_pipeline()

    user_ctx = UserContext(
        user_id=req.user_id,
        role=UserRole(req.role),
    )
    source_context = req.source_context.model_copy(
        update={"sender_id": req.source_context.sender_id or req.user_id}
    )

    task_input = TaskInput(
        trace_id=req.trace_id or str(uuid.uuid4()),
        user_context=user_ctx,
        source_context=source_context,
        raw_message=req.message,
        attachments=[],
    )

    return EventSourceResponse(sse_generator(pipeline, task_input))
