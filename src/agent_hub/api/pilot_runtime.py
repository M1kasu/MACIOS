"""PilotRuntime：M2 把 Pilot M0/M1 全部组件装配为单例。

- 默认使用 ``InMemoryEventStore``；指定 ``settings.pilot_store_path``
  时切到 ``SQLiteEventStore``。
- ``settings.pilot_demo_mode=True`` 时自动注册 fake skills，方便 Web
  Dashboard 离线起跑。
- 真实 ModelGateway / Skill 在后续模块替换；M2 默认 FakeModelGateway。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from agent_hub.config.settings import Settings
from agent_hub.connectors.feishu import (
    FeishuAuthProvider,
    FeishuClient,
    FeishuClientProtocol,
    FeishuLongConnClient,
    FeishuProgressNotifier,
    FeishuWebhookProcessor,
    FeishuWebhookService,
)
from agent_hub.connectors.feishu.approval_notifier import FeishuApprovalNotifier
from agent_hub.pilot.events.bus import EventBus
from agent_hub.pilot.events.store import (
    EventStore,
    InMemoryEventStore,
    SnapshotStore,
    SQLiteEventStore,
)
from agent_hub.pilot.services.approval import ApprovalService
from agent_hub.pilot.services.artifacts import ArtifactStore
from agent_hub.pilot.services.commands import PilotCommandService
from agent_hub.pilot.services.event_publisher import PilotEventPublisher
from agent_hub.pilot.services.execution import ExecutionEngine
from agent_hub.pilot.services.model_gateway import (
    ModelGateway,
    OpenAIModelGateway,
    TemplatePlanGateway,
)
from agent_hub.pilot.services.orchestrator import TaskOrchestrator
from agent_hub.pilot.services.planning import PlanningService
from agent_hub.pilot.services.progress import TaskProgressReporter
from agent_hub.pilot.services.queries import PilotQueryService
from agent_hub.pilot.services.repository import PilotRepository
from agent_hub.pilot.skills.fake import register_fake_skills
from agent_hub.pilot.skills.feishu import register_feishu_skills
from agent_hub.pilot.skills.feishu_card import register_feishu_card_skills
from agent_hub.pilot.skills.internal import (
    BriefGenerator,
    register_internal_document_skills,
)
from agent_hub.pilot.skills.real_chain import register_real_chain_skills
from agent_hub.pilot.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from agent_hub.core.pipeline import AgentPipeline
    from agent_hub.runtime.agent.turn_runtime import UnifiedTurnRuntime

logger = structlog.get_logger(__name__)


@dataclass
class PilotRuntime:
    """聚合所有 Pilot 服务的运行时容器。"""

    settings: Settings
    event_store: EventStore
    snapshot_store: SnapshotStore
    bus: EventBus
    repository: PilotRepository
    publisher: PilotEventPublisher
    registry: SkillRegistry
    gateway: ModelGateway
    planning: PlanningService
    approvals: ApprovalService
    artifacts: ArtifactStore
    execution: ExecutionEngine
    orchestrator: TaskOrchestrator
    queries: PilotQueryService
    commands: PilotCommandService
    brief_generator: BriefGenerator
    feishu_client: FeishuClientProtocol | None = None
    feishu_webhook_service: FeishuWebhookService | None = None
    feishu_long_conn: FeishuLongConnClient | None = None
    feishu_progress_notifier: FeishuProgressNotifier | None = None

    async def aclose(self) -> None:
        if self.feishu_progress_notifier is not None:
            await self.feishu_progress_notifier.aclose()
        await self.bus.close()
        if self.feishu_long_conn is not None:
            await self.feishu_long_conn.aclose()
        if self.feishu_client is not None:
            await self.feishu_client.aclose()
        # SQLite store 支持关闭；InMemory 没有资源需要释放。
        close = getattr(self.event_store, "close", None)
        if callable(close):
            close()


def build_pilot_runtime(
    settings: Settings,
    *,
    pipeline: AgentPipeline | None = None,
    turn_runtime: UnifiedTurnRuntime | None = None,
) -> PilotRuntime:
    """根据 ``Settings`` 构造一个完整可用的 PilotRuntime。

    Args:
        settings:     运行时配置。
        pipeline:     保留参数（尚局路由调试用）；新代码不需要。
        turn_runtime: 预先创建的 UnifiedTurnRuntime，注入到飞书连接器。
    """
    if settings.pilot_store_path:
        store: EventStore | SQLiteEventStore = SQLiteEventStore(
            settings.pilot_store_path,
        )
        snapshots: SnapshotStore = store  # type: ignore[assignment]
        logger.info("pilot_runtime.store", kind="sqlite",
                    path=settings.pilot_store_path)
    else:
        mem = InMemoryEventStore()
        store = mem
        snapshots = mem
        logger.info("pilot_runtime.store", kind="memory")

    bus = EventBus()
    repo = PilotRepository(snapshots)
    publisher = PilotEventPublisher(store, bus)
    progress = TaskProgressReporter(
        publisher,
        interval_seconds=settings.pilot_progress_heartbeat_interval_seconds,
    )

    registry = SkillRegistry()
    if settings.pilot_demo_mode:
        register_fake_skills(registry)
        logger.info("pilot_runtime.skills_registered", mode="demo")

    skill_mode = "real_chain" if settings.pilot_use_real_chain else "fake"
    fallback_gateway = TemplatePlanGateway(skill_mode=skill_mode)
    gateway: ModelGateway = fallback_gateway
    if settings.pilot_use_real_gateway:
        gateway = OpenAIModelGateway(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            skill_mode=skill_mode,
            fallback=fallback_gateway,
        )
        logger.info("pilot_runtime.gateway", kind="openai", skill_mode=skill_mode)
    planning = PlanningService(gateway, repo, publisher)
    approvals = ApprovalService(repo, publisher)
    artifacts = ArtifactStore(
        repo,
        publisher,
        artifact_dir=settings.pilot_artifact_dir or None,
    )
    brief_generator = register_internal_document_skills(
        registry,
        artifact_reader=artifacts.read_content_by_id,
    )
    logger.info("pilot_runtime.skills_registered", mode="internal")
    execution = ExecutionEngine(
        repository=repo,
        publisher=publisher,
        registry=registry,
        artifacts=artifacts,
        approvals=approvals,
        auto_approve_writes=settings.pilot_auto_approve_writes,
        progress_reporter=progress,
    )
    orchestrator = TaskOrchestrator(
        repository=repo,
        publisher=publisher,
        planning=planning,
        approvals=approvals,
        execution=execution,
        progress_reporter=progress,
    )
    queries = PilotQueryService(repo, store)
    commands = PilotCommandService(repo, approvals, orchestrator, publisher)

    feishu_client, feishu_webhook_service, feishu_long_conn = _maybe_build_feishu(
        settings,
        registry=registry,
        artifact_reader=artifacts.read_content_by_id,
        commands=commands,
        turn_runtime=turn_runtime,
    )
    if feishu_client is not None:
        notifier = FeishuApprovalNotifier(repo, feishu_client)
        execution.set_approval_notifier(notifier)
        orchestrator.set_approval_notifier(notifier)
        progress_notifier = FeishuProgressNotifier(
            repo,
            feishu_client,
            min_interval_seconds=settings.feishu_progress_min_interval_seconds,
            max_messages_per_task=settings.feishu_progress_max_messages_per_task,
        )
        publisher.add_handler(progress_notifier.handle_event)
    else:
        progress_notifier = None

    # 真实产物链（PPTX/Drive）：飞书可用 + 启用开关时注册
    if settings.pilot_use_real_chain:
        register_real_chain_skills(
            registry,
            feishu_client=feishu_client,
            artifact_reader=artifacts.read_content_by_id,
            default_folder_token=settings.feishu_default_folder_token,
            admin_open_id=settings.feishu_admin_open_id,
            drive_url_template=settings.feishu_drive_url_template,
            allow_overwrite=True,
        )
        logger.info(
            "pilot_runtime.skills_registered",
            mode="real_chain",
            with_feishu=feishu_client is not None,
        )

    return PilotRuntime(
        settings=settings,
        event_store=store,
        snapshot_store=snapshots,
        bus=bus,
        repository=repo,
        publisher=publisher,
        registry=registry,
        gateway=gateway,
        planning=planning,
        approvals=approvals,
        artifacts=artifacts,
        execution=execution,
        orchestrator=orchestrator,
        queries=queries,
        commands=commands,
        brief_generator=brief_generator,
        feishu_client=feishu_client,
        feishu_webhook_service=feishu_webhook_service,
        feishu_long_conn=feishu_long_conn,
        feishu_progress_notifier=progress_notifier,
    )


def _maybe_build_feishu(
    settings: Settings,
    *,
    registry: SkillRegistry,
    artifact_reader,  # noqa: ANN001 - bound method
    commands: PilotCommandService | None = None,
    turn_runtime: UnifiedTurnRuntime | None = None,
) -> tuple[FeishuClientProtocol | None, FeishuWebhookService | None, FeishuLongConnClient | None]:
    """根据配置可选地装配飞书连接器。

    仅在 ``feishu_enabled`` 且 ``app_id``/``app_secret`` 都提供时
    才创建真实客户端；其他情况返回 ``(None, None, None)``。
    """
    if not settings.feishu_enabled:
        return None, None, None
    if not (settings.feishu_app_id and settings.feishu_app_secret):
        logger.warning("feishu.runtime.missing_credentials")
        return None, None, None

    auth = FeishuAuthProvider(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        api_base_url=settings.feishu_api_base_url,
        request_timeout_ms=settings.feishu_request_timeout_ms,
    )
    client = FeishuClient(
        auth=auth,
        api_base_url=settings.feishu_api_base_url,
        request_timeout_ms=settings.feishu_request_timeout_ms,
    )
    register_feishu_skills(
        registry,
        client,
        artifact_reader=artifact_reader,
        default_folder_token=settings.feishu_default_folder_token,
    )
    # M5：审批卡片技能（独立 scope，避免与 register_feishu_skills 冲突）
    register_feishu_card_skills(registry, client, allow_overwrite=False)
    processor = FeishuWebhookProcessor(
        bot_open_id=settings.feishu_bot_open_id,
        ignore_self_messages=settings.feishu_ignore_self_messages,
        require_mention_in_group=settings.feishu_require_mention_in_group,
        trigger_keywords=settings.feishu_trigger_keyword_set,
        dedup_ttl_seconds=settings.feishu_webhook_dedup_ttl_seconds,
        dedup_max_entries=settings.feishu_webhook_dedup_max_entries,
    )
    webhook_service = FeishuWebhookService(
        processor=processor,
        client=client,
        commands=commands,
        turn_runtime=turn_runtime,
    )
    # 长连接模式：主动连接飞书 WebSocket 服务器，无需公网地址
    long_conn = FeishuLongConnClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        webhook_service=webhook_service,
    )
    logger.info("feishu.runtime.long_conn_enabled", app_id=settings.feishu_app_id)
    return client, webhook_service, long_conn


__all__ = ["PilotRuntime", "build_pilot_runtime"]
