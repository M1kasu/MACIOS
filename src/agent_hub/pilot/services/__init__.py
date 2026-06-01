"""Pilot 服务编排层（M1）。

服务层负责把 M0 的领域、状态机、事件底座与 M1 的 SkillRegistry 串成
端到端的业务流程；不直接接入飞书 / FastAPI / 真实 LLM。
"""

from agent_hub.pilot.services.approval import ApprovalService
from agent_hub.pilot.services.artifacts import ArtifactStore
from agent_hub.pilot.services.commands import CommandError, PilotCommandService
from agent_hub.pilot.services.dto import (
    PlanBlueprint,
    PlanProfile,
    PlanStepDraft,
    RunResult,
    ServiceActor,
    StepExecution,
    TaskHandle,
    TaskRequest,
)
from agent_hub.pilot.services.event_publisher import PilotEventPublisher
from agent_hub.pilot.services.execution import ExecutionEngine, StepInputResolver
from agent_hub.pilot.services.model_gateway import (
    FakeModelGateway,
    ModelGateway,
    OpenAIModelGateway,
    PlanContext,
    SkillMode,
    TemplatePlanGateway,
    derive_plan_profile,
)
from agent_hub.pilot.services.orchestrator import TaskOrchestrator
from agent_hub.pilot.services.planning import (
    REQUIRED_KINDS,
    REQUIRED_KINDS_BY_PROFILE,
    BriefRevisionContext,
    PlanningService,
    PlanTemplateError,
)
from agent_hub.pilot.services.progress import TaskProgressReporter
from agent_hub.pilot.services.queries import (
    PilotQueryService,
    TaskDetail,
    TaskSummary,
    WorkspaceSummary,
)
from agent_hub.pilot.services.repository import PilotRepository

__all__ = [
    "ApprovalService",
    "ArtifactStore",
    "BriefRevisionContext",
    "CommandError",
    "ExecutionEngine",
    "FakeModelGateway",
    "ModelGateway",
    "OpenAIModelGateway",
    "PilotCommandService",
    "PilotEventPublisher",
    "PilotQueryService",
    "PilotRepository",
    "PlanBlueprint",
    "PlanContext",
    "PlanProfile",
    "PlanStepDraft",
    "PlanTemplateError",
    "PlanningService",
    "REQUIRED_KINDS",
    "REQUIRED_KINDS_BY_PROFILE",
    "RunResult",
    "ServiceActor",
    "SkillMode",
    "StepExecution",
    "StepInputResolver",
    "TaskDetail",
    "TaskHandle",
    "TaskOrchestrator",
    "TaskProgressReporter",
    "TaskRequest",
    "TaskSummary",
    "TemplatePlanGateway",
    "WorkspaceSummary",
    "derive_plan_profile",
]
