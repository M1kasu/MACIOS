"""Pipeline 兜底逻辑单元测试。

覆盖：
- sub_tasks 为空 + TOOL_EXECUTION → 兜底生成子任务 → ReAct 触发
- sub_tasks 为空 + TASK_GENERATION → 兜底 → llm_agent 执行
- GROUP_CHAT → 不触发兜底
- Router prompt 包含"必须至少生成一个子任务"
"""

from __future__ import annotations

import pytest

from agent_hub.core.enums import ExecutionMode
from agent_hub.core.models import (
    AgentResult,
    RoutingDecision,
    SourceChatType,
    SourceContext,
    SubTask,
    TaskInput,
    UserContext,
)
from agent_hub.core.pipeline import AgentPipeline
from agent_hub.core.router import _SYSTEM_PROMPT

# ── 直接测试 _ensure_default_subtask ──────────────────


class TestPipelineFallback:
    """测试 Pipeline 兜底逻辑。"""

    @pytest.fixture()
    def pipeline(self, tmp_path):
        """构造一个最小化 Pipeline（不依赖真实 LLM）。"""
        from unittest.mock import patch

        from agent_hub.config.settings import Settings

        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="http://localhost:1234",
            obsidian_vault_path=str(tmp_path / "vault"),
            guard_enabled=False,
            cache_enabled=False,
            vector_memory_enabled=False,
            rate_limiter_enabled=False,
        )
        with (
            patch("agent_hub.agents.llm_agent.Anthropic"),
            patch("agent_hub.agents.llm_agent.OpenAI"),
            patch("agent_hub.core.pipeline.RAGPipeline"),
        ):
            return AgentPipeline(settings)

    def test_fallback_tool_execution(self, pipeline: AgentPipeline) -> None:
        """ACT + 空 plan → 兜底生成含 tool_agent 的子任务。"""
        routing = RoutingDecision(
            mode=ExecutionMode.ACT,
            confidence=0.9,
            reasoning="用户要求计算",
            plan=[],
        )
        result = pipeline._ensure_default_subtask(routing, "帮我算一下 2+3")

        assert len(result.plan) == 1
        st = result.plan[0]
        assert st.subtask_id == "subtask_fallback_1"
        assert st.description == "帮我算一下 2+3"
        assert "llm_agent" in st.required_agents
        assert "tool_agent" in st.required_agents
        assert st.priority == 1
        assert st.depends_on == []

    def test_fallback_task_generation(self, pipeline: AgentPipeline) -> None:
        """PLAN + 空 plan → 兜底 → llm_agent 子任务。"""
        routing = RoutingDecision(
            mode=ExecutionMode.PLAN,
            confidence=0.85,
            reasoning="用户要写代码",
            plan=[],
        )
        result = pipeline._ensure_default_subtask(routing, "写一个快速排序")

        assert len(result.plan) == 1
        st = result.plan[0]
        assert st.required_agents == ["llm_agent"]
        assert st.description == "写一个快速排序"

    def test_fallback_retrieval(self, pipeline: AgentPipeline) -> None:
        """QA + 空 plan → 兜底生成 retrieval_agent 子任务。"""
        routing = RoutingDecision(
            mode=ExecutionMode.QA,
            confidence=0.8,
            reasoning="用户查询知识",
            plan=[],
        )
        result = pipeline._ensure_default_subtask(routing, "RAG是什么")

        assert len(result.plan) == 1
        assert result.plan[0].required_agents == ["retrieval_agent"]

    def test_no_fallback_group_chat(self, pipeline: AgentPipeline) -> None:
        """IGNORE → _ensure_default_subtask 不生成子任务。"""
        routing = RoutingDecision(
            mode=ExecutionMode.IGNORE,
            confidence=0.95,
            reasoning="普通群聊",
            plan=[],
        )
        result = pipeline._ensure_default_subtask(routing, "哈哈哈")

        assert len(result.plan) == 0

    def test_no_fallback_when_subtasks_exist(self, pipeline: AgentPipeline) -> None:
        """已有 sub_tasks 时，run() 中的条件不会触发兜底。"""
        existing = SubTask(
            subtask_id="subtask_1",
            description="已有任务",
            required_agents=["llm_agent"],
        )
        routing = RoutingDecision(
            mode=ExecutionMode.PLAN,
            confidence=0.9,
            reasoning="测试",
            plan=[existing],
        )
        # 模拟 run() 中的条件判断
        should_fallback = not routing.plan and routing.mode != ExecutionMode.IGNORE
        assert should_fallback is False

    def test_vector_memory_enabled_wires_runtime_components(self, tmp_path) -> None:
        from unittest.mock import MagicMock, patch

        from agent_hub.config.settings import Settings

        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="http://localhost:1234",
            obsidian_vault_path=str(tmp_path / "vault"),
            guard_enabled=False,
            cache_enabled=False,
            vector_memory_enabled=True,
            rate_limiter_enabled=False,
            pg_dsn="postgresql://agent:agent@localhost:5432/agent_hub",
            embedding_dimension=4,
        )
        vector_store = MagicMock(name="vector_store")
        embedder = MagicMock(name="embedder")
        vector_memory = MagicMock(name="vector_memory")
        conflict_detector = MagicMock(name="conflict_detector")
        memory_operator = MagicMock(name="memory_operator")

        with (
            patch("agent_hub.agents.llm_agent.Anthropic"),
            patch("agent_hub.agents.llm_agent.OpenAI"),
            patch("agent_hub.core.pipeline.RAGPipeline"),
            patch(
                "agent_hub.rag.vector_store.VectorStore",
                return_value=vector_store,
            ) as vector_store_cls,
            patch("agent_hub.rag.embedder.Embedder", return_value=embedder) as embedder_cls,
            patch(
                "agent_hub.memory.vector_memory.VectorMemory",
                return_value=vector_memory,
            ) as vector_memory_cls,
            patch(
                "agent_hub.memory.conflict_detector.ConflictDetector",
                return_value=conflict_detector,
            ) as detector_cls,
            patch(
                "agent_hub.memory.memory_ops.MemoryOperator",
                return_value=memory_operator,
            ) as operator_cls,
        ):
            pipeline = AgentPipeline(settings)

        embedder_cls.assert_called_once()
        vector_store_cls.assert_called_once()
        vector_memory_cls.assert_called_once_with(
            vector_store=vector_store,
            embedder=embedder,
        )
        detector_cls.assert_called_once_with(
            vector_memory=vector_memory,
            embedder=embedder,
            threshold=settings.memory_conflict_threshold,
        )
        operator_cls.assert_called_once_with(
            persistent=pipeline._memory.persistent,
            vector_memory=vector_memory,
        )
        assert pipeline._memory._vector_memory is vector_memory
        assert pipeline._memory._conflict_detector is conflict_detector
        assert pipeline._memory._memory_operator is memory_operator

    @pytest.mark.asyncio
    async def test_feishu_addressed_ignore_is_promoted_to_llm(
        self,
        pipeline: AgentPipeline,
    ) -> None:
        """飞书私聊普通问答被 Router 判 ignore 时，仍应由 LLM 回复。"""
        from unittest.mock import AsyncMock, patch

        pipeline._agents["llm_agent"].run = AsyncMock(return_value=AgentResult(
            agent_name="llm_agent",
            success=True,
            output="我很好",
            duration_ms=0,
            trace_id="trace-feishu-qa",
        ))
        task_input = TaskInput(
            trace_id="trace-feishu-qa",
            user_context=UserContext(
                user_id="ou_test",
                role="user",
            ),
            source_context=SourceContext(
                channel="feishu",
                chat_id="oc_chat",
                chat_type=SourceChatType.DIRECT,
                sender_id="ou_test",
            ),
            raw_message="你好，这是一条测试内容，你需要回复我“我很好”",
        )

        with patch.object(
            pipeline._router,
            "route",
            new_callable=AsyncMock,
            return_value=RoutingDecision(
                mode=ExecutionMode.IGNORE,
                confidence=1.0,
                reasoning="闲聊",
                plan=[],
            ),
        ):
            output = await pipeline.run_router_plan(task_input)

        assert output.status == "success"
        assert output.response == "我很好"
        pipeline._agents["llm_agent"].run.assert_awaited_once()


class TestRouterPromptEnsuresSubtask:
    """验证 Router prompt 包含强制子任务生成的规则。"""

    def test_router_prompt_ensures_subtask(self) -> None:
        assert "必须至少生成一个子任务" in _SYSTEM_PROMPT

    def test_router_prompt_group_chat_exception(self) -> None:
        assert "ignore" in _SYSTEM_PROMPT
        assert "空列表" in _SYSTEM_PROMPT
