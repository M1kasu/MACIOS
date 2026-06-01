"""服务层 DTO：API/skill 契约与领域实体之间的桥接对象。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.pilot.domain.enums import (
    ActorType,
    PlanStepKind,
    PlanStepStatus,
    RiskLevel,
    TaskStatus,
)
from agent_hub.pilot.domain.models import Artifact, Plan, PlanStep, Task


class PlanProfile(StrEnum):
    """计划形态。

    Profile 决定 :class:`PlanningService` 校验所需的 ``PlanStepKind`` 集合，
    以及 :class:`TemplatePlanGateway` 生成的默认 blueprint 模板。
    AgentTurnLoop 决定是否调用 ``start_pilot_task``；profile 只描述任务
    计划形态，不承担入口意图分类。
    """

    DECK_FULL = "deck_full"
    DOC_ONLY = "doc_only"
    SUMMARY_ONLY = "summary_only"
    REVISION = "revision"


class ServiceActor(BaseModel):
    """服务调用方身份。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str
    actor_type: ActorType = ActorType.USER


class TaskRequest(BaseModel):
    """提交任务的入口请求。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_channel: str
    raw_text: str
    requester_id: str
    title: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    workspace_id: str | None = None
    tenant_key: str | None = None
    attachments: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = False
    plan_profile: PlanProfile | None = None


class TaskHandle(BaseModel):
    """orchestrator 提交后给调用方的轻量句柄。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    task_id: str
    plan_id: str | None = None
    status: TaskStatus
    trace_id: str
    deduplicated: bool = False


class PlanStepDraft(BaseModel):
    """规划阶段未持久化的 step 草稿。

    ``ref`` 用作 draft 内部依赖标识；持久化后由 PlanningService
    映射为真实的 ``step_id`` 后再写入 ``depends_on``。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str
    title: str
    kind: PlanStepKind
    skill_name: str
    input_params: dict[str, Any] = Field(default_factory=dict)
    inputs_from: list[str] = Field(default_factory=list)
    output_artifact_ref: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.READ
    requires_approval: bool = False
    timeout_ms: int = 30_000
    max_retries: int = 0


class PlanBlueprint(BaseModel):
    """ModelGateway 输出的 plan 设计稿。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str
    assumptions: list[str] = Field(default_factory=list)
    steps: list[PlanStepDraft]
    profile: PlanProfile = PlanProfile.DECK_FULL
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepExecution(BaseModel):
    """单步执行的外部观测结果。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    final_status: PlanStepStatus
    artifact_id: str | None = None
    error: str | None = None


class RunResult(BaseModel):
    """ExecutionEngine 跑完一次 plan 的整体结果。"""

    model_config = ConfigDict(extra="forbid")

    task: Task
    plan: Plan
    steps: list[PlanStep]
    artifacts: list[Artifact]
    executions: list[StepExecution]
    final_status: TaskStatus


__all__ = [
    "PlanBlueprint",
    "PlanProfile",
    "PlanStepDraft",
    "RunResult",
    "ServiceActor",
    "StepExecution",
    "TaskHandle",
    "TaskRequest",
]
