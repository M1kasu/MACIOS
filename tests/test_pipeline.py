"""Pipeline 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_hub.config.settings import get_settings
from agent_hub.core.enums import ExecutionMode, UserRole
from agent_hub.core.models import (
    AgentResult,
    RoutingDecision,
    SourceChatType,
    SourceContext,
    SubTask,
    TaskInput,
    UserContext,
)
from agent_hub.core.pipeline import AgentPipeline, _topological_layers
from agent_hub.core.risk import RiskDecision, ToolProfile

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def settings():
    # lru_cache 返回全局共享实例；为每个 pipeline 实例强制关闭缓存，
    # 防止 L1/L2 cache 命中在测试间泄漏 status="cache_hit"。
    base = get_settings()
    return base.model_copy(update={"cache_enabled": False, "vector_memory_enabled": False})


@pytest.fixture()
def pipeline(settings):
    with (
        patch("agent_hub.agents.llm_agent.Anthropic"),
        patch("agent_hub.agents.llm_agent.OpenAI"),
        patch("agent_hub.core.pipeline.RAGPipeline"),
        patch("agent_hub.core.router.AsyncOpenAI"),
        patch("agent_hub.security.guard.AsyncOpenAI"),
    ):
        return AgentPipeline(settings)


def _make_task(
    message: str = "你好",
    role: UserRole = UserRole.USER,
    trace_id: str | None = None,
) -> TaskInput:
    ctx = UserContext(
        user_id="test-u1",
        role=role,
    )
    return TaskInput(
        trace_id=trace_id or "test-trace-001",
        user_context=ctx,
        source_context=SourceContext(
            channel="test",
            chat_id="test-sess",
            chat_type=SourceChatType.DIRECT,
            sender_id="test-u1",
        ),
        raw_message=message,
    )


# ── 拓扑排序 ────────────────────────────────────────


class TestTopologicalLayers:
    def test_empty(self) -> None:
        assert _topological_layers([]) == []

    def test_no_deps(self) -> None:
        tasks = [
            SubTask(subtask_id="a", description="A", required_agents=["llm_agent"]),
            SubTask(subtask_id="b", description="B", required_agents=["llm_agent"]),
        ]
        layers = _topological_layers(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 2

    def test_linear_chain(self) -> None:
        tasks = [
            SubTask(subtask_id="a", description="A", required_agents=["llm_agent"]),
            SubTask(
                subtask_id="b",
                description="B",
                required_agents=["llm_agent"],
                depends_on=["a"],
            ),
            SubTask(
                subtask_id="c",
                description="C",
                required_agents=["llm_agent"],
                depends_on=["b"],
            ),
        ]
        layers = _topological_layers(tasks)
        assert len(layers) == 3
        assert layers[0][0].subtask_id == "a"
        assert layers[1][0].subtask_id == "b"
        assert layers[2][0].subtask_id == "c"

    def test_diamond_dag(self) -> None:
        """A → B, A → C, B+C → D"""
        tasks = [
            SubTask(subtask_id="a", description="A", required_agents=["llm_agent"]),
            SubTask(subtask_id="b", description="B", required_agents=["llm_agent"], depends_on=["a"]),
            SubTask(subtask_id="c", description="C", required_agents=["llm_agent"], depends_on=["a"]),
            SubTask(subtask_id="d", description="D", required_agents=["llm_agent"], depends_on=["b", "c"]),
        ]
        layers = _topological_layers(tasks)
        assert len(layers) == 3
        # Layer 0: A
        assert {t.subtask_id for t in layers[0]} == {"a"}
        # Layer 1: B, C (parallel)
        assert {t.subtask_id for t in layers[1]} == {"b", "c"}
        # Layer 2: D
        assert {t.subtask_id for t in layers[2]} == {"d"}

    def test_unknown_dependency_warns(self) -> None:
        tasks = [
            SubTask(subtask_id="a", description="A", required_agents=["llm_agent"]),
            SubTask(
                subtask_id="b",
                description="B",
                required_agents=["llm_agent"],
                depends_on=["missing"],
            ),
        ]

        with patch("agent_hub.core.pipeline.logger.warning") as warning:
            layers = _topological_layers(tasks)

        warning.assert_called_once_with(
            "topological_layers.unknown_dep",
            subtask_id="b",
            unknown_dep="missing",
        )
        assert len(layers) == 1
        assert {task.subtask_id for task in layers[0]} == {"a", "b"}


# ── Pipeline 集成测试（mock LLM） ───────────────────


def _mock_routing(mode: ExecutionMode, confidence: float = 0.85, **kwargs) -> RoutingDecision:
    return RoutingDecision(
        mode=mode,
        confidence=confidence,
        reasoning="mock reasoning",
        low_confidence=confidence < 0.7,
        **kwargs,
    )


class TestPipelineGroupChatFallback:
    @pytest.mark.asyncio
    async def test_group_chat_returns_fallback(self, pipeline: AgentPipeline) -> None:
        """GROUP_CHAT 意图应返回 fallback。"""
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=_mock_routing(ExecutionMode.IGNORE, 0.9),
        ):
            result = await pipeline.run_router_plan(_make_task("哈哈"))
            assert result.status == "fallback"

    @pytest.mark.asyncio
    async def test_low_confidence_returns_fallback(self, pipeline: AgentPipeline) -> None:
        """低置信度应返回 fallback。"""
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=_mock_routing(ExecutionMode.PLAN, 0.3),
        ):
            result = await pipeline.run_router_plan(_make_task("嗯嗯"))
            assert result.status == "fallback"


class TestPipelineAdminPermission:
    @pytest.mark.asyncio
    async def test_user_denied_admin_command(self, pipeline: AgentPipeline) -> None:
        """普通用户执行管理员命令应被拒绝。"""
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=_mock_routing(ExecutionMode.DELEGATE, 0.95),
        ):
            result = await pipeline.run_router_plan(_make_task("重启服务器", role=UserRole.USER))
            assert result.status == "permission_denied"

    @pytest.mark.asyncio
    async def test_admin_allowed_admin_command(self, pipeline: AgentPipeline) -> None:
        """管理员执行需要权限的操作应被允许（进入 Agent 执行阶段）。"""
        routing = _mock_routing(
            ExecutionMode.DELEGATE,
            0.95,
            plan=[
                SubTask(
                    subtask_id="st1",
                    description="mcp__ops__deploy(target=prod)",
                    required_agents=["tool_agent"],
                ),
            ],
        )
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=routing,
        ):
            result = await pipeline.run_router_plan(_make_task("echo hello", role=UserRole.ADMIN))
            # 不应是 permission_denied
            assert result.status != "permission_denied"

    @pytest.mark.asyncio
    async def test_permission_gate_uses_risk_decision(
        self,
        pipeline: AgentPipeline,
    ) -> None:
        routing = _mock_routing(
            ExecutionMode.QA,
            0.95,
            plan=[
                SubTask(
                    subtask_id="st1",
                    description="sensitive request",
                    required_agents=["llm_agent"],
                ),
            ],
        )
        risk = RiskDecision(
            tool_profile=ToolProfile.READ_ONLY,
            risk_level="admin",
            requires_admin=True,
        )
        with (
            patch.object(
                pipeline._router,
                "route",
                new_callable=AsyncMock,
                return_value=routing,
            ),
            patch.object(pipeline._risk_policy, "assess", return_value=risk),
            patch.object(pipeline._risk_policy, "apply", return_value=routing),
        ):
            result = await pipeline.run_router_plan(_make_task("sensitive", role=UserRole.USER))

        assert result.status == "permission_denied"


class TestPipelineTraceId:
    @pytest.mark.asyncio
    async def test_trace_id_propagation(self, pipeline: AgentPipeline) -> None:
        """trace_id 应在整条链路中正确传递。"""
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=_mock_routing(ExecutionMode.IGNORE),
        ):
            task = _make_task(trace_id="my-trace-123")
            result = await pipeline.run_router_plan(task)
            assert result.trace_id == "my-trace-123"


class TestPipelineAgentExecution:
    @pytest.mark.asyncio
    async def test_subtask_dispatched_to_agent(self, pipeline: AgentPipeline) -> None:
        """子任务应被分发到正确的 Agent 并返回结果。"""
        routing = _mock_routing(
            ExecutionMode.PLAN,
            0.9,
            plan=[
                SubTask(
                    subtask_id="st1",
                    description="写一个冒泡排序",
                    required_agents=["llm_agent"],
                ),
            ],
        )
        mock_agent_result = AgentResult(
            agent_name="llm_agent",
            success=True,
            output="def bubble_sort(arr): ...",
            duration_ms=100,
            trace_id="test-trace-001",
        )
        with (
            patch.object(
                pipeline._router,
                "route",
                new_callable=AsyncMock,
                return_value=routing,
            ),
            patch.object(
                pipeline._agents["llm_agent"],
                "run",
                new_callable=AsyncMock,
                return_value=mock_agent_result,
            ),
        ):
            result = await pipeline.run_router_plan(_make_task("写冒泡排序"))
            assert result.status == "success"
            assert len(result.agent_results) == 1
            assert "bubble_sort" in result.response

    @pytest.mark.asyncio
    async def test_unknown_agent_type(self, pipeline: AgentPipeline) -> None:
        """未知 Agent 类型不应导致崩溃。"""
        routing = _mock_routing(
            ExecutionMode.PLAN,
            0.9,
            plan=[
                SubTask(
                    subtask_id="st1",
                    description="do something",
                    required_agents=["nonexistent_agent"],
                ),
            ],
        )
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=routing,
        ):
            result = await pipeline.run_router_plan(_make_task("test"))
            assert result.status == "success"
            assert result.agent_results[0].success is False
            assert "未知" in result.agent_results[0].error


class TestPipelineErrorHandling:
    @pytest.mark.asyncio
    async def test_router_exception_returns_error(self, pipeline: AgentPipeline) -> None:
        """路由器异常应被 Pipeline 捕获，返回 status=error。"""
        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM 调用失败"),
        ):
            result = await pipeline.run_router_plan(_make_task("test"))
            assert result.status == "error"
            assert "LLM 调用失败" in result.response
