"""Agent-Hub 跨层契约包。

这里是所有「界面契约」的统一入口：
- 跨层传递的身份与来源上下文（identity）
- 执行模式、任务 DTO、路由决策（execution）
- 工具规范与能力引用（capability）
- 权限档案与守卫检测结果（policy）
- 产物轻量引用（artifact）
- 领域事件 envelope（events）
- 公共错误类型（errors）

**规则**：
- contracts 只依赖 pydantic + stdlib，不依赖任何 agent_hub 内部实现模块；
- contracts 不放 Pilot 业务实体（Workspace/Task/Plan/Approval/Artifact 领域模型）；
- contracts 不放 Memory/RAG/Feishu 内部实体；
- 其他模块应从 agent_hub.contracts 导入跨层 DTO，不直接 import core.models。
"""

from __future__ import annotations

# ── artifact ──────────────────────────────────────────────────────────────────
from agent_hub.contracts.artifact import (
    Artifact,
    ArtifactRef,
)

# ── capability ────────────────────────────────────────────────────────────────
from agent_hub.contracts.capability import (
    InstructionSkillRef,
    ToolCall,
    ToolResult,
    ToolSpec,
)

# ── errors ────────────────────────────────────────────────────────────────────
from agent_hub.contracts.errors import (
    AgentHubError,
    ContractViolationError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
)

# ── events ────────────────────────────────────────────────────────────────────
from agent_hub.contracts.events import (
    DomainEvent,
)

# ── execution ─────────────────────────────────────────────────────────────────
from agent_hub.contracts.execution import (
    AgentResult,
    ExecutionMode,
    MemoryEntry,
    NodeType,
    ReActStep,
    ReActTrace,
    RoutingDecision,
    SubTask,
    TaskInput,
    TaskOutput,
)

# ── identity ──────────────────────────────────────────────────────────────────
from agent_hub.contracts.identity import (
    ChannelType,
    SourceChatType,
    SourceContext,
    UserContext,
    UserRole,
)

# ── interaction ──────────────────────────────────────────────────────────────
from agent_hub.contracts.interaction import (
    InboundRequest,
)

# ── policy ────────────────────────────────────────────────────────────────────
from agent_hub.contracts.policy import (
    GuardResult,
    PermissionProfile,
    PolicyDecision,
    RiskLevel,
)

# ── turn ─────────────────────────────────────────────────────────────────────
from agent_hub.contracts.turn import (
    TurnEvent,
    TurnIntent,
    TurnResult,
    TurnStatus,
)

__all__ = [
    # identity
    "ChannelType",
    "SourceChatType",
    "SourceContext",
    "UserContext",
    "UserRole",
    # execution
    "AgentResult",
    "ExecutionMode",
    "MemoryEntry",
    "NodeType",
    "ReActStep",
    "ReActTrace",
    "RoutingDecision",
    "SubTask",
    "TaskInput",
    "TaskOutput",
    # capability
    "InstructionSkillRef",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    # interaction
    "InboundRequest",
    # turn
    "TurnEvent",
    "TurnIntent",
    "TurnResult",
    "TurnStatus",
    # policy
    "GuardResult",
    "PermissionProfile",
    "PolicyDecision",
    "RiskLevel",
    # artifact
    "Artifact",
    "ArtifactRef",
    # events
    "DomainEvent",
    # errors
    "AgentHubError",
    "ContractViolationError",
    "ExternalServiceError",
    "NotFoundError",
    "PermissionDeniedError",
]
