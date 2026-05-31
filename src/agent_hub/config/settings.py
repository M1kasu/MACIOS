"""应用配置管理。

通过 ``pydantic-settings`` 从 ``.env`` 文件和环境变量中读取配置。
优先级：环境变量 > .env 文件 > 默认值。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（pyproject.toml 所在位置）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置。

    所有字段均可通过同名环境变量覆盖（不区分大小写）。

    Attributes:
        neo4j_uri: Neo4j 数据库连接 URI。
        neo4j_user: Neo4j 用户名。
        neo4j_password: Neo4j 密码。
        vm_shared_dir: 虚拟机共享目录路径。
        host_data_dir: 宿主机数据目录路径。
        allowed_file_extensions: 允许上传的文件扩展名。
        log_level: 日志级别。
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM（智谱 / OpenAI 兼容） ─────────────────────
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_model: str = "glm-4-flash"

    # ── Neo4j ─────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── RAG ────────────────────────────────────────────
    rag_api_base: str = "http://localhost:8000"

    # ── pgvector + Embedding ─────────────────────────
    pg_dsn: str = "postgresql://localhost:5432/agent_hub"
    pg_pool_min_size: int = 1
    pg_pool_max_size: int = 10
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dimension: int = 1024
    embedding_device: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_batch_size: int = 32
    embedding_normalize: bool = True
    embedding_timeout_seconds: float = 30.0
    chunk_size: int = 512
    chunk_overlap: int = 64
    rag_top_k: int = 5
    rrf_k: int = 60
    rag_redis_enabled: bool = True
    rag_query_cache_enabled: bool = True
    rag_query_cache_ttl: int = 300
    rag_sparse_cache_enabled: bool = True
    rag_sparse_cache_ttl: int = 86_400
    rag_sparse_bootstrap_limit: int = 20_000

    # ── Obsidian 记忆持久化 ────────────────────────────
    obsidian_vault_path: str = "./data/obsidian"

    # ── 记忆管理（Mem0 式） ───────────────────────────
    memory_conflict_threshold: float = 0.85

    # ── CORS（逗号分隔） ──────────────────────────────
    cors_origins: str = "http://localhost:3000"

    # ── HTTP 部署出口 ─────────────────────────────────
    # 为空时 API 响应继续返回相对路径；配置后用于飞书卡片、群消息、
    # 演示链接等需要外部访问的 URL。
    public_base_url: str = ""
    # Dashboard 静态目录。相对路径会按当前工作目录和项目根目录兜底解析。
    dashboard_static_dir: str = "web"

    # ── ReAct 推理循环 ────────────────────────────────
    react_max_rounds: int = 5

    # ── Prompt 注入防御 ───────────────────────────────
    guard_enabled: bool = True
    guard_llm_enabled: bool = True
    guard_llm_timeout_seconds: float = 3.0
    guard_cache_ttl_seconds: float = 300.0
    guard_cache_max_entries: int = 1024

    # ── Redis 缓存 ───────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 300
    semantic_cache_threshold: float = 0.95
    # 是否在主 Pipeline 中启用三级缓存（需要 Redis 在线）。
    cache_enabled: bool = False

    # ── LLM 并发控制 ─────────────────────────────────
    llm_max_concurrent: int = 5
    llm_call_timeout: int = 30
    # 是否构造全局 RateLimiter 实例（暂仅注入到 Pipeline，未强制 wrap LLM 调用）。
    rate_limiter_enabled: bool = False
    # 是否在 Pipeline 启动时自动注入 VectorMemory + ConflictDetector。
    vector_memory_enabled: bool = False

    # ── Pilot M2 ─────────────────────────────────────
    pilot_enabled: bool = True
    # 空字符串表示使用 InMemoryEventStore；否则作为 SQLite 文件路径。
    pilot_store_path: str = ""
    # demo 模式：启动时自动注册 fake skills，方便 Web Dashboard 离线试跑。
    pilot_demo_mode: bool = True
    # 为 ExecutionEngine 提供默认 auto-approve 策略；M2 默认关闭以暴露真实状态流。
    pilot_auto_approve_writes: bool = False
    # SSE 端点单次回放的最大事件数。
    pilot_event_backfill_limit: int = 500
    # admin-only recovery 路由的简单 header gate；为空表示禁用。
    pilot_admin_token: str = ""
    # M3 Artifact 内容落盘根目录；空字符串表示用内存兜底（仅推荐测试使用）。
    pilot_artifact_dir: str = "data/pilot/artifacts"
    # 启用真实 ModelGateway（OpenAI 兼容）；为 False 时仍走 FakeModelGateway。
    pilot_use_real_gateway: bool = False
    # 启用真实产物链（SlideSpec / PPTX / Drive）；False 时仍走 fake skills。
    pilot_use_real_chain: bool = False
    # 长任务活动心跳间隔；用于 task.progress 事件与 Dashboard 实时活动感知。
    pilot_progress_heartbeat_interval_seconds: float = 15.0
    # 飞书端心跳消息最小发送间隔；避免长任务进度刷屏。
    feishu_progress_min_interval_seconds: float = 30.0
    feishu_progress_max_messages_per_task: int = 20

    # ── M4 飞书 IM ───────────────────────────────────
    # 启用真实飞书入口（webhook + skills）；为 False 时只用 fake skills。
    feishu_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    # 自建应用 / 应用商店应用；目前只校验存在，不区分鉴权差异。
    feishu_app_type: str = "self_built"
    # 开放平台 API base，可指向飞书国际版 / lark.com。
    feishu_api_base_url: str = "https://open.feishu.cn"
    feishu_request_timeout_ms: int = 12_000
    # webhook event_id LRU 去重 TTL（秒）。
    feishu_webhook_dedup_ttl_seconds: int = 600
    feishu_webhook_dedup_max_entries: int = 4_096
    # Drive 默认上传目录 token；留空表示根目录。
    feishu_default_folder_token: str = ""
    # 兜底 open_id：正常飞书任务会优先分享给本次请求人的 open_id；
    # 仅在无法从入站消息取得请求人 open_id 时才使用该值。
    feishu_admin_open_id: str = ""
    # Drive 文件可访问 URL 模板，{file_token} 占位符将被替换。
    # 例如租户域 https://xxx.feishu.cn/file/{file_token} 或通用 https://www.feishu.cn/file/{file_token}。
    feishu_drive_url_template: str = "https://www.feishu.cn/file/{file_token}"
    # 机器人 open_id，用于 mention 过滤；留空表示不强制要求 @bot。
    feishu_bot_open_id: str = ""
    feishu_ignore_self_messages: bool = True
    # 触发任务的关键字（逗号分隔）；非空时只在文本包含任一关键字时建任务。
    feishu_trigger_keywords: str = ""
    # 是否需要 mention 机器人才触发（仅群聊生效）。
    feishu_require_mention_in_group: bool = True

    # ── 文件路径 & 安全 ──────────────────────────────
    vm_shared_dir: str = "/mnt/shared"
    host_data_dir: str = "D:/Agent-Hub/data"
    allowed_file_extensions: str = ".txt,.pdf,.md,.docx,.csv,.json"

    # ── 日志 ──────────────────────────────────────────
    log_level: str = "INFO"

    @property
    def allowed_extensions_set(self) -> set[str]:
        """将逗号分隔的扩展名字符串解析为集合。"""
        return {ext.strip() for ext in self.allowed_file_extensions.split(",") if ext.strip()}

    def public_url(self, path: str) -> str:
        """把站内路径转换为可对外展示的 URL。

        ``PUBLIC_BASE_URL`` 未配置时保留相对路径，方便本地测试与同源
        Dashboard；配置后返回绝对 URL，供飞书消息、卡片和演示链接使用。
        """
        normalized_path = path if path.startswith("/") else f"/{path}"
        base_url = self.public_base_url.strip().rstrip("/")
        if not base_url:
            return normalized_path
        return f"{base_url}{normalized_path}"

    @property
    def dashboard_url(self) -> str:
        """Dashboard 的对外访问地址。"""
        return self.public_url("/dashboard/")

    @property
    def feishu_trigger_keyword_set(self) -> set[str]:
        """逗号分隔关键字 → 去空白集合。空集合表示不按关键字过滤。"""
        return {
            kw.strip()
            for kw in self.feishu_trigger_keywords.split(",")
            if kw.strip()
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例。

    使用 ``lru_cache`` 确保整个进程生命周期内只解析一次配置。
    """
    return Settings()
