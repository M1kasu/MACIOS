# Agent-Hub

> 面向飞书办公场景的 Agent 任务运行时：把 IM 中的模糊任务请求转成可审批、可追踪、可恢复的结构化执行流。仓库同时包含两层能力：
>
> 1. 通用 Agent 执行内核：结构化路由、DAG 编排、ReAct 推理、RAG、记忆、安全与流式响应。
> 2. Agent-Pilot 业务运行时：任务规划、审批、产物、事件流、Dashboard，以及可选的飞书接入与真实 PPT 链路。

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?logo=fastapi)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 项目概览

Agent-Hub 可以按两个层次理解：

1. **通用 Agent 执行内核**
   核心入口是 `UnifiedTurnRuntime + AgentPipeline.run_stream() + AgentTurnLoop + SourceBindingResolver + PromptGuard + Memory`，负责"接收入站请求、确定性绑定、按需调用工具、读取 Skill/MCP/Plugin 能力定义、检索知识、写入记忆、流式返回"。`DecisionRouter` 仍作为显式工具用于复杂 DAG 计划，不再是自然语言主入口的第一跳。
2. **Agent-Pilot 业务运行时**
   Pilot 在通用引擎之上补齐任务化与协作化能力：`Workspace / Task / Plan / PlanStep / Approval / Artifact / ExecutionEvent`，并提供 Dashboard、SSE、审批恢复、飞书入口与 PPT 产物链路。飞书入站消息会先规范化为 `InboundRequest`，再进入同一个 `UnifiedTurnRuntime`，由模型在回合中按需调用 `answer_directly`、`query_task_status` 或 `start_pilot_task`。

如果你只想验证 Agent 编排内核，可以从 `/chat` 与 `/chat/stream` 开始。
如果你想看完整的"任务规划 → 审批 → 执行 → 产物 → 多端同步"闭环，请直接使用 `/api/pilot/*` 与 `/dashboard/`。

## 当前已实现范围

| 范围 | 状态 | 说明 |
| ------ | ------ | ------ |
| Agent-Hub 核心引擎 | 代码已实现 | 路由、DAG 编排、ReAct、RAG、记忆、安全、SSE |
| Pilot 任务闭环 | 代码已实现 | Workspace / Task / Plan / PlanStep / Approval / Artifact / EventStore / EventBus / Dashboard |
| 飞书连接器 | 代码已实现，需凭据接入 | 支持 webhook / 长连接、任务发起、进度消息、审批卡片回调 |
| 真实 PPT 产物链 | 代码已实现，需飞书凭据 | 支持 Brief → SlideSpec → PPTX → 飞书 Drive 分享 |
| Docker 本地演示 | 可直接运行 | 提供 app + postgres + redis 的保底演示栈，默认关闭飞书与真实分享链路 |
| 评测与脚本 | 已提供 | 提供 benchmark、离线校验、RAG 评估、演示 Runbook |

> **诚实说明**：上表"代码已实现"表示模块代码存在、单元测试通过；但不代表全链路端到端压测验证完成。下表列出的是**确实可运行、可复现**的验证路径。

## 已验证能力

| 能力 | 说明 |
| ------ | ------ |
| 结构化路由 | `DecisionRouter` 使用 OpenAI 兼容 function calling 输出 `RoutingDecision` 与子任务 DAG；支持 6 种执行模式：ignore / qa / plan / act / delegate / repair；低置信度自动降级 |
| 能力层拆分 | `Tool` 只表示 MCP/适配器暴露的可执行原语 schema；`Skill` 是 `SKILL.md` 指令包；`MCP` 是外部工具服务配置；`Plugin` 是 `.claude-plugin/plugin.json` 打包 commands / agents / skills / MCP 的分发单元 |
| 确定性源绑定 | `SourceBindingResolver` 按固定层级（message/thread > chat > user > channel/account > channel default > main）做"最具体匹配"路由，生成稳定 session_key 实现多租户会话隔离 |
| 确定性风险策略 | `RiskPolicy` 基于用户角色、能力标签与 Guard 结果计算 `ToolProfile`（read_only / baseline_artifact / tool_assisted_safe / admin_ops），不信任 LLM 输出的权限建议 |
| DAG 并行执行 | 通用 `AgentPipeline` 按依赖分层，并用 `asyncio.gather` 并行执行同层子任务；Pilot `ExecutionEngine` 也做 DAG 分层，但业务步骤在层内顺序推进，以保证审批、产物和恢复状态一致 |
| DAG 计划校验 | `SubTaskPlanValidator` 校验子任务数量上限、ID 唯一性、依赖可达性、环检测与 profile 兼容性 |
| ReAct 工具推理 | `LLMAgent` 支持 Thought → Action → Observation 循环，并记录 `react_trace`；工具调用受 `ToolProfile` 约束 |
| 混合检索 RAG | 稠密检索、BM25 稀疏检索与 RRF 融合排序 |
| LangGraph 反思检索 | `ReflectionAgent` 实现 retrieve → evaluate → rewrite → generate 容错工作流 |
| Prompt 注入防御 | 规则引擎 + LLM 二次检测的双层防护；Guard 结果参与 `RiskPolicy` 的审批与风险等级决策 |
| 三层记忆 | 会话记忆、Obsidian Markdown 持久记忆、可选向量记忆注入点 |
| 事件化 Pilot | 任务、步骤、审批、产物状态都写入 `ExecutionEvent`，支持 SSE 回放与实时订阅 |
| 审批与恢复 | 支持计划审批、步骤审批、失败恢复与 blocked task resume；高风险操作（写入、分享）自动触发审批 |
| 多端同步 | Dashboard 通过 SSE 订阅同一条事件流；飞书可选推送进度与审批卡片 |
| 统一回合入口 | HTTP、飞书和评测入口统一进入 `UnifiedTurnRuntime`；普通问答、进度查询和长任务启动都由 AgentTurnLoop 的工具调用结果推导 |

## 当前实现边界

这份 README 尽量只描述代码里已经存在的能力。当前边界如下：

### 架构边界

- 通用自然语言主编排是 `UnifiedTurnRuntime → AgentPipeline.run_stream() → AgentTurnLoop`，不是用 LangGraph 驱动全系统。复杂 DAG 执行需要由 AgentTurnLoop 显式调用 `run_decision_router_plan`，该工具内部再走 `DecisionRouter → RiskPolicy → SubTaskPlanValidator → Agent 执行 → Memory 写入`。
- Router 只给出执行建议（mode、capabilities、plan），所有权限相关字段（tool_profile、risk_level、requires_approval、route_source、session_key）均由 `SourceBindingResolver` 和 `RiskPolicy` 确定性计算，不信任 LLM 输出。
- `capabilities/` 负责读取和规范化 `SKILL.md`、`.mcp.json`、`.claude-plugin/plugin.json`；不会在本地启动 MCP server，也不会把 Skill 当成可执行函数注册。
- Pilot 业务执行引擎优先保证审批状态一致性：它按 DAG 层推进，但同层 step 当前是顺序执行；DAG 并行压测只对应通用 AgentPipeline 的调度效果，不代表飞书审批全链路端到端耗时。
- LangGraph 目前只用于 `reflection_agent` 的检索纠错子流程。
- 入口层不再维护关键词/规则式意图服务；是否回答、查进度或启动 Pilot 任务由 AgentTurnLoop 在同一回合中通过工具调用决定。

### 连接器边界

- 飞书已通过 WebSocket 长连接模式接入，无需公网地址。
- Docker 默认是**本地保底演示模式**：`FEISHU_ENABLED=false`、`PILOT_USE_REAL_CHAIN=false`，保证没有飞书凭据时也能稳定跑通 Dashboard + Pilot。
- 真实 Drive 分享链路依赖飞书应用凭据、folder token 和可访问的 Drive URL 模板；文件默认按本次请求人的 open_id 私发/分享，`FEISHU_ADMIN_OPEN_ID` 只作为兜底。

### 依赖与降级

- `/chat` 入口依赖可用的 LLM；如果没有 `LLM_API_KEY`，Pilot 的 fake/demo 链路依然能跑，但通用问答能力会降级。
- `source_context` 是 `/chat` 和 `/chat/stream` 的**必填字段**，至少需要传 `channel`。不传会直接 422。

## 架构概览

```mermaid
graph TD
    U["User / Feishu / Dashboard"] --> API["FastAPI App"]

    API --> CHAT["/chat & /chat/stream"]
    API --> PILOT["/api/pilot/*"]
    API --> FEISHU["/api/feishu/webhook"]
    API --> DASH["/dashboard/"]

    CHAT --> TURN["UnifiedTurnRuntime"]
    FEISHU --> TURN
    TURN --> PIPE["AgentPipeline.run_stream"]
    PIPE --> BINDING["SourceBindingResolver"]
    PIPE --> LOOP["AgentTurnLoop"]
    LOOP --> ANSWER["answer_directly"]
    LOOP --> STATUS["query_task_status"]
    LOOP --> START["start_pilot_task"]
    LOOP --> ROUTER_TOOL["run_decision_router_plan"]
    ROUTER_TOOL --> ROUTER["DecisionRouter (6 modes)"]
    ROUTER --> RISK["RiskPolicy + ToolProfile"]
    RISK --> VALIDATOR["SubTaskPlanValidator"]
    VALIDATOR --> LLM["LLMAgent + ReAct"]
    PIPE --> RET[RetrievalAgent]
    PIPE --> TOOL[ToolAgent]
    PIPE --> REFLECT[ReflectionAgent]
    PIPE --> MEM[MemoryManager]
    PIPE --> GUARD["PromptGuard"]

    PILOT --> RUNTIME[PilotRuntime]
    RUNTIME --> ORCH[TaskOrchestrator]
    START --> ORCH
    STATUS --> RUNTIME
    ORCH --> PLAN[PlanningService]
    ORCH --> APPROVAL[ApprovalService]
    ORCH --> EXEC[ExecutionEngine]
    EXEC --> SKILLS[SkillRegistry]
    EXEC --> ART[ArtifactStore]
    RUNTIME --> STORE["SQLite/InMemory EventStore"]
    RUNTIME --> BUS[EventBus]
    BUS --> SSE["Pilot SSE"]
    SSE --> DASH
```

## 仓库结构

```text
src/agent_hub/
├── agents/         # LLM / Retrieval / Tool / Reflection Agent
├── api/            # FastAPI 路由、Pilot Runtime、SSE、Dashboard 挂载
├── capabilities/   # Claude/OpenClaw 风格 Skill、MCP、Plugin 加载器
├── config/         # Settings 与配置管理
├── connectors/     # 飞书 WebSocket 长连接连接器
├── core/           # Pipeline、Router、Models、Binding、Risk、PlanValidator、Tracer 等通用内核
├── eval/           # 评测器与报告工具
├── memory/         # Session / Persistent / Vector Memory
├── pilot/          # Pilot 领域模型、事件、服务、技能、查询
├── rag/            # Chunker、Embedder、Ranker、Vector Store
└── security/       # Prompt Guard 与安全防护

scripts/            # benchmark、offline verify、演示脚本
tests/              # API、Pipeline、Feishu、Pilot、RAG、安全等测试
web/                # Dashboard 静态页
demo_runbook.md     # 比赛/演示黄金路径说明
```

## 运行模式

| 模式 | 是否需要 LLM Key | 是否需要飞书凭据 | 典型入口 | 适用场景 |
| ------ | ------------------ | ------------------ | ---------- | ---------- |
| 通用 Agent API | 需要 | 不需要 | `/chat`、`/chat/stream` | 验证路由、ReAct、RAG、记忆、安全 |
| 本地 Pilot 保底演示 | 不需要 | 不需要 | `/api/pilot/*`、`/dashboard/` | 纯本地演示任务规划、审批、产物、SSE |
| Docker Compose 保底演示 | 不需要 | 不需要 | `docker compose up -d --build` 后访问 `/dashboard/` | 快速起一个可演示的容器环境 |
| 飞书真实链路 | 建议需要 | 需要 | 飞书消息、审批卡片、Dashboard | 演示 IM 入口、Drive 分享、三端同步 |

## 快速开始

### 1. 准备环境

- Python `3.11+`，推荐 `3.12`
- Docker / Docker Compose（用于本地依赖或完整容器演示）
- 可选：OpenAI 兼容 LLM Key
- 可选：飞书开放平台应用凭据

### 2. 复制环境变量模板

```bash
cp .env.example .env
```

Windows PowerShell 可以用：

```powershell
Copy-Item .env.example .env
```

`.env.example` 已经调整为**保底演示默认值**：不开飞书、不走真实分享链路，直接复制后就能先跑 Pilot/Dashboard。

### 3. 最小可运行配置

如果你只想先看 Dashboard + Pilot 任务闭环，下面这组变量就够了：

```env
PUBLIC_BASE_URL=http://127.0.0.1:8080
CORS_ORIGINS=http://127.0.0.1:8080,http://localhost:8080

PILOT_ENABLED=true
PILOT_STORE_PATH=./data/pilot/pilot.sqlite3
PILOT_ARTIFACT_DIR=./data/pilot/artifacts
PILOT_DEMO_MODE=true
PILOT_AUTO_APPROVE_WRITES=false
PILOT_USE_REAL_GATEWAY=false
PILOT_USE_REAL_CHAIN=false

FEISHU_ENABLED=false
FEISHU_USE_LONG_CONN=false

OBSIDIAN_VAULT_PATH=./data/obsidian
```

如果你要启用通用 `/chat` 能力，再补上：

```env
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4-flash
GUARD_LLM_TIMEOUT_SECONDS=3
GUARD_CACHE_TTL_SECONDS=300
GUARD_CACHE_MAX_ENTRIES=1024
```

如果你要启用真实飞书链路，再补上：

```env
PILOT_USE_REAL_CHAIN=true
PILOT_USE_REAL_GATEWAY=true

FEISHU_ENABLED=true
FEISHU_USE_LONG_CONN=true
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret
FEISHU_BOT_OPEN_ID=ou_xxx
FEISHU_DEFAULT_FOLDER_TOKEN=folder_xxx
FEISHU_DRIVE_URL_TEMPLATE=https://your-tenant.feishu.cn/file/{file_token}
# 可选兜底；正常会按本次消息发送人的 open_id 私发/分享
FEISHU_ADMIN_OPEN_ID=

PUBLIC_BASE_URL=https://your-public-host
CORS_ORIGINS=https://your-public-host
```

## 本地源码运行

### 1. 安装依赖

```bash
pip install -e .
pip install -e ".[dev]"
```

### 2. 可选地启动本地依赖

如果你要用 PostgreSQL / pgvector / Redis，可以直接复用本仓库的 compose 依赖服务：

```bash
docker compose up -d postgres redis
```

对应的默认连接串是：

```env
PG_DSN=postgresql://agent:agent@localhost:5432/agent_hub
REDIS_URL=redis://localhost:6379/0
```

### 3. 启动 API

```bash
python -m uvicorn agent_hub.api.routes:app --host 0.0.0.0 --port 8080 --reload
```

启动后可访问：

- `http://127.0.0.1:8080/health`
- `http://127.0.0.1:8080/dashboard/`

### 4. 先跑一个 Pilot 任务

这是最推荐的本地验证方式，因为它不依赖 LLM Key，也能完整展示审批、步骤、产物和事件流：

```bash
curl -X POST http://127.0.0.1:8080/api/pilot/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source_channel": "api",
    "raw_text": "请帮我做一份关于 Agent-Hub 的路演 PPT",
    "requester_id": "demo-user",
    "title": "Agent-Hub Demo Deck",
    "plan_profile": "deck_full",
    "auto_approve": false
  }'
```

提交成功后：

1. 打开 `/dashboard/` 观察任务列表、步骤状态和事件流。
2. 在 Dashboard 里对 `requested` 审批点"同意"。
3. 查看生成的 Brief、SlideSpec、PPTX 和 fake/share 产物。

### 5. 可选地测试通用聊天入口

> **前提**：需要配置 `LLM_API_KEY`，否则 Router 和生成能力会降级。

`source_context` 是必填字段，至少需要传 `channel`。同步对话示例：

```bash
curl -X POST http://127.0.0.1:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我写一个快速排序",
    "user_id": "u001",
    "role": "user",
    "source_context": {
      "channel": "api",
      "sender_id": "u001"
    }
  }'
```

SSE 流式输出示例：

```bash
curl -N -X POST http://127.0.0.1:8080/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "给我一个 Python 装饰器示例",
    "user_id": "u001",
    "source_context": {
      "channel": "api",
      "sender_id": "u001"
    }
  }'
```

## Docker / Compose 使用说明

### 默认目标

仓库里的 `docker-compose.yml` 现在默认是**本地保底演示模式**，它会：

- 启动 `app + postgres + redis`
- 把 Dashboard 同源挂到 `/dashboard/`
- 把 Pilot 数据和 Artifact 持久化到 Docker volume
- 默认关闭 `FEISHU_ENABLED` 与 `PILOT_USE_REAL_CHAIN`

这样做的目的，是让你**没有飞书凭据、没有公网回调地址时也能直接演示**，避免容器启动后落到"规划走真实链路、分享技能却没注册"的半可用状态。

### 服务说明

| 服务 | 作用 | 默认端口 |
| ------ | ------ | ---------- |
| `app` | FastAPI API + Dashboard + Pilot Runtime | `8080` |
| `postgres` | pgvector / PostgreSQL 依赖 | `5432` |
| `redis` | 缓存与后续基础设施依赖 | `6379` |

### 启动完整容器栈

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f app
```

健康检查：

```bash
curl http://127.0.0.1:8080/health
```

访问 Dashboard：

```text
http://127.0.0.1:8080/dashboard/
```

### 容器模式下提交演示任务

默认 compose 不需要飞书，也不需要 LLM Key。启动后直接调用：

```bash
curl -X POST http://127.0.0.1:8080/api/pilot/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source_channel": "api",
    "raw_text": "请生成一份 Agent-Hub 项目介绍 PPT",
    "requester_id": "docker-demo",
    "title": "Docker Demo",
    "plan_profile": "deck_full",
    "auto_approve": false
  }'
```

### 数据持久化

compose 使用以下 volume：

- `pg_data`：PostgreSQL 数据
- `obsidian_data`：Obsidian 持久记忆
- `pilot_data`：Pilot SQLite + Artifacts

容器内对应路径：

- `/app/data/obsidian`
- `/app/data/pilot/pilot.sqlite3`
- `/app/data/pilot/artifacts`

### 从 Docker 保底模式切到真实飞书链路

要切到真实链路，请在 `.env` 或 shell 环境中显式覆盖：

```env
PILOT_USE_REAL_CHAIN=true
PILOT_USE_REAL_GATEWAY=true

FEISHU_ENABLED=true
FEISHU_USE_LONG_CONN=true
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret
FEISHU_BOT_OPEN_ID=ou_xxx
FEISHU_DEFAULT_FOLDER_TOKEN=folder_xxx
FEISHU_DRIVE_URL_TEMPLATE=https://your-tenant.feishu.cn/file/{file_token}
# 可选兜底；正常会按本次消息发送人的 open_id 私发/分享
FEISHU_ADMIN_OPEN_ID=

PUBLIC_BASE_URL=https://your-public-host
CORS_ORIGINS=https://your-public-host
```

然后重建应用容器：

```bash
docker compose up -d --build app
```

注意：

- `PG_DSN` 在容器内要指向 `postgres` service，而不是 `localhost`。
- 如果改用公网 webhook 模式，请把 `FEISHU_USE_LONG_CONN=false`，并确保外部能访问 `/api/feishu/webhook`。
- 真实 Drive 分享链路对飞书应用权限、folder token、Drive URL 模板和请求人 open_id 获取都有要求；`FEISHU_ADMIN_OPEN_ID` 只作为无法识别请求人时的兜底。

## API 概览

### 通用 Agent API

| 路由 | 说明 |
| ------ | ------ |
| `POST /chat` | 同步对话入口 |
| `POST /chat/stream` | SSE 流式对话 |
| `GET /health` | 健康检查 |
| `GET /tools?role=user` | 查看当前角色可见的工具 schema；默认不再内置本地 demo 工具，真实工具应由 MCP 服务发现 |
| `GET /trace/{trace_id}` | 查询内存 Trace |

### Pilot API

| 路由 | 说明 |
| ------ | ------ |
| `POST /api/pilot/tasks` | 提交任务 |
| `GET /api/pilot/tasks` | 列任务摘要 |
| `GET /api/pilot/tasks/{task_id}` | 查任务详情 |
| `POST /api/pilot/approvals/{approval_id}/decision` | 审批通过 / 拒绝 |
| `POST /api/pilot/tasks/{task_id}/resume` | 恢复 blocked 任务 |
| `POST /api/pilot/tasks/{task_id}/steps/{step_id}/retry` | 从步骤重试 |
| `GET /api/pilot/tasks/{task_id}/events` | SSE 事件流 |
| `GET /api/pilot/artifacts/{artifact_id}` | Artifact 元数据 |
| `GET /api/pilot/artifacts/{artifact_id}/content` | Artifact 内容预览 |

### 可选飞书入口

| 路由 | 说明 |
| ------ | ------ |
| `POST /api/feishu/webhook` | 飞书 webhook 事件入口（仅 webhook 模式） |

### Dashboard

| 路由 | 说明 |
| ------ | ------ |
| `GET /dashboard/` | Pilot 任务驾驶舱 |

## 关键实现亮点

### 1. 结构化路由，而不是字符串 prompt 分支

`DecisionRouter` 使用 OpenAI 兼容 function calling，把请求输出为结构化的 `RoutingDecision` 和子任务计划，支持 6 种执行模式（ignore / qa / plan / act / delegate / repair），再按置信度规则做降级处理（< 0.4 强制 ignore，< 0.7 清空 plan）。

### 2. 确定性风险策略，不信任 LLM 权限建议

`RiskPolicy` 基于确定性事实（用户角色、能力标签、Guard 结果、Binding 约束）计算最终的 `ToolProfile`（read_only → baseline_artifact → tool_assisted_safe → admin_ops）和风险等级（read / write / share / admin / blocked），Router 输出的权限相关字段会被显式清除后由 Policy 层重新写入。高风险操作（写入、分享）自动触发审批要求。

### 3. 确定性源绑定，多租户会话隔离

`SourceBindingResolver` 按固定层级（message/thread > chat > user > channel/account > channel default > main）做"最具体匹配"路由，将来源事实解析为 `agent_id` + 稳定 `session_key`，在 LLM 驱动的执行建议之前完成绑定。Binding 还可携带 `tool_profile` 约束，与 `RiskPolicy` 取最小权限集合。

### 4. DAG 计划校验

`SubTaskPlanValidator` 在 Router 输出子任务后执行校验：子任务数量上限（默认 8）、ID 唯一性、依赖可达性、环检测（拓扑排序）以及 ToolProfile 兼容性（read_only 下不允许 tool_agent）。

### 5. ReAct 推理和工具权限控制是统一的

`LLMAgent` 在需要工具时会进入 ReAct 循环；工具调用受 `ToolProfile` 约束，`RiskPolicy.tool_allowed()` 按工具的 `risk_level` / `side_effect` / `tool_profiles` 与当前 profile 做权限检查。当前工具层不再注册本地 demo 可执行函数，MCP tool 只在本地承载 schema 和来源信息，实际执行应交给 MCP 客户端连接外部服务。

### 6. 统一回合入口

HTTP、飞书和评测模拟器都先归一化为 `InboundRequest`，再进入 `UnifiedTurnRuntime`。入口层不做规则式意图分类；AgentTurnLoop 在同一回合中选择直接回答、查询任务状态、启动 Pilot 长任务，或显式调用 `run_decision_router_plan` 进入旧 DAG 调试路径。

### 7. Pilot 任务闭环是事件化的

`Task / Plan / PlanStep / Approval / Artifact` 的状态变化全部通过状态机推进，并写入 `ExecutionEvent`，因此 Dashboard、飞书消息和恢复逻辑都建立在同一条事实流上。

### 8. 审批不是旁路 UI，而是执行链路的一部分

计划审批和步骤审批都在 `ApprovalService + ExecutionEngine` 内联处理；写入 / 分享类高风险 step 会进入 `WAITING_APPROVAL`，批准后才能继续推进。

### 9. 多端实时同步依赖回放 + 实时订阅

Pilot SSE 会先从 EventStore 回放 backfill，再订阅 EventBus 实时事件，保证 Dashboard 刷新或手机端重连后也不会丢关键状态。

### 10. 飞书长连接与卡片回调共用同一套下游逻辑

长连接模式会把 SDK 事件归一化成 webhook 风格 payload，再复用同一套 `FeishuWebhookService`，因此 webhook 与长连接不是两套分叉实现。

## 测试与脚本

常用测试命令：

```bash
pytest tests/ -q --ignore=tests/test_manual.py
pytest tests/test_pilot_services.py tests/test_pilot_api.py tests/test_feishu_webhook.py -q
pytest tests/test_feishu_longconn.py tests/test_real_chain_skills.py -q
pytest tests/test_guard.py -q
```

常用脚本：

```bash
python scripts/offline_verify.py
python scripts/benchmark_dag.py --scenarios 50 --rounds 1
python scripts/benchmark.py
python scripts/evaluate.py
```

## 企业知识库 RAG

RAG 使用 PostgreSQL/pgvector 作为权威知识库存储，Redis 作为查询结果与 BM25 稀疏索引热缓存。Docker Compose 已包含 `postgres` 与 `redis` 服务：

```bash
docker compose up -d postgres redis
```

关键配置：

```env
PG_DSN=postgresql://agent:agent@localhost:5432/agent_hub
REDIS_URL=redis://localhost:6379/0

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIMENSION=1024
EMBEDDING_DEVICE=cpu

RAG_REDIS_ENABLED=true
RAG_QUERY_CACHE_ENABLED=true
RAG_SPARSE_CACHE_ENABLED=true
```

兼容 OpenAI embeddings API 的远程 embedding 服务可切换为：

```env
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=3072
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=your_embedding_key
```

知识库接口：

```bash
curl -X POST http://127.0.0.1:8080/api/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","namespace":"handbook","document_id":"leave-policy","doc_type":"markdown","content":"# 年假政策\n员工每年可享受..."}'

curl -X POST http://127.0.0.1:8080/api/rag/retrieve \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","namespace":"handbook","query":"年假怎么申请？","top_k":5}'
```

如果你在准备演示，建议同时阅读：

- `demo_runbook.md`：比赛/答辩的黄金路径与兜底方案

## 常见问题

### 1. Dashboard 可以打开，但一直没有任务

这是正常的。Dashboard 目前主要负责"看状态、做审批、看产物"，不是任务创建页。请先调用 `/api/pilot/tasks`，或从飞书入口发起任务。

### 2. `docker compose up` 后，为什么默认不直接连飞书？

因为没有飞书凭据时，真实 PPT 分享链路只会跑到一半。compose 现在默认走本地保底演示模式，优先保证可跑通、可展示、可恢复。

### 3. 为什么我开了 `/chat`，但回答很弱或者直接降级？

`/chat` 依赖可用的 LLM。如果没有配置 `LLM_API_KEY`，Router 和生成能力都会降级。Pilot 的 fake/demo 任务链路不依赖这个，所以仍然能运行。

### 4. 为什么开了 `PILOT_USE_REAL_CHAIN=true` 还是失败？

真实链路不仅要求这个开关，还要求：

- `FEISHU_ENABLED=true`
- 飞书应用凭据完整
- Drive folder token 可用
- 能从飞书入站消息拿到请求人的 open_id，或配置了 `FEISHU_ADMIN_OPEN_ID` 兜底
- `PUBLIC_BASE_URL` 与回调/分享地址配置正确

缺一个条件，最容易失败的就是 `real.drive.upload_share`。

## 安全与权限

- **Prompt 注入防御**：规则检测 + LLM 语义检测双层组合，`PromptGuard` 输出的 `risk_level` 参与 `RiskPolicy` 的审批与风险等级决策。
- **确定性风险策略**：`RiskPolicy` 基于用户角色、能力标签、Guard 结果和 Binding 约束计算最终的 `ToolProfile`（read_only / baseline_artifact / tool_assisted_safe / admin_ops），不信任 LLM 输出的权限建议；Router 输出的权限字段会被显式清除后由 Policy 层重新写入。
- **工具权限过滤**：`RiskPolicy.tool_allowed()` 按工具的 `risk_level`、`side_effect`、`tool_profiles` 与当前 profile 做权限检查，管理员工具对普通用户自动降级为 read_only。
- **高风险自动审批**：风险等级为 admin / share 时自动触发审批要求；write 操作在非私聊场景也会触发审批。
- **确定性源绑定**：`SourceBindingResolver` 将来源事实解析为 `agent_id` + 稳定 `session_key`，在 LLM 执行之前完成绑定。会话隔离优先使用 `thread_id`、`chat_id`，再退到 `sender_id`。Binding 可携带 `tool_profile` 约束，与 `RiskPolicy` 取最小权限集合。
- **DAG 计划校验**：`SubTaskPlanValidator` 在执行前校验子任务数量、依赖可达性、环检测和 profile 兼容性。

## 许可

MIT
