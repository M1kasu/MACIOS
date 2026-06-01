$ErrorActionPreference = "Stop"

$vault = "E:\obsidian\cache\ApparatusJJ"
$backupRoot = Join-Path "D:\Agent-Hub\.note_backups" ("obsidian_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

function Write-Note {
    param(
        [Parameter(Mandatory=$true)][string]$RelativePath,
        [Parameter(Mandatory=$true)][string]$Content
    )
    $target = Join-Path $vault $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        throw "Missing note: $target"
    }

    $backupPath = Join-Path $backupRoot $RelativePath
    $backupDir = Split-Path -Parent $backupPath
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $target -Destination $backupPath -Force

    Set-Content -LiteralPath $target -Value $Content -Encoding UTF8
}

function Update-NoteText {
    param(
        [Parameter(Mandatory=$true)][string]$RelativePath,
        [Parameter(Mandatory=$true)][scriptblock]$Updater
    )
    $target = Join-Path $vault $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        throw "Missing note: $target"
    }

    $backupPath = Join-Path $backupRoot $RelativePath
    $backupDir = Split-Path -Parent $backupPath
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $target -Destination $backupPath -Force

    $text = Get-Content -LiteralPath $target -Raw -Encoding UTF8
    $updated = & $Updater $text
    Set-Content -LiteralPath $target -Value $updated -Encoding UTF8
}

Write-Note -RelativePath "40_Projects\办公Agent数据生产与任务编排平台\办公Agent项目-面试讲解卡.md" -Content @'
---
tags:
  - project
  - agent
  - feishu
  - interview
  - data
---

# 办公Agent项目-面试讲解卡

关联：[[项目讲解与追问脚本]]、[[简历项目校准与量化口径]]、[[AI Agent与MCP Skills]]、[[Agent架构选型与评测]]、[[RAG评测闭环与数据飞轮]]、[[Agent执行链路与任务编排]]、[[多Agent通信权限与可靠性]]

## 面试版定位

不要讲成“企业级 AgentOS”或“全自主多 Agent 协作平台”。更稳的定位是：

> 面向飞书办公场景的 Agent 任务运行时：把 IM 里的模糊任务请求转成可审批、可追踪、可恢复的结构化执行流，并把执行过程沉淀成可复盘、可评估的数据。

主线只有一条：

> 飞书消息 / API 任务进入系统 → 生成 Task / Plan / PlanStep → 高风险步骤进入审批 → 执行 Skill 并生成 Artifact → 所有状态写入 ExecutionEvent → Dashboard / 飞书端回放和同步。

## 简历版本

**办公Agent数据生产与任务编排平台** `FastAPI` `Pydantic` `pgvector` `LangGraph` `RAG`

项目描述：开发接入飞书的企业办公智能助手，支持用户在 IM 中发起查询、审批、任务拆分和进度同步；系统自动完成任务规划、知识检索、工具调用、审批回调和结果回传，并记录执行轨迹用于复盘优化。

## 本地核验结论

本地路径：`D:\Agent-Hub`

- 项目 README 已收敛为“飞书办公场景 Agent 任务运行时”，不再主讲 AgentOS。
- 飞书接入真实存在：webhook、longconn、approval card、progress notifier、Feishu skills。
- 任务编排真实存在：`core/pipeline.py` 的通用 `AgentPipeline` 支持 Kahn 拓扑分层 + `asyncio.gather`；Pilot `ExecutionEngine` 按 DAG 层推进，但同层步骤顺序执行，以保证审批、Artifact 和 resume 状态一致。
- RAG 真实存在：pgvector、BM25、RRF、chunker、embedding、query rewrite、评估模块。
- 事件化追踪真实存在：EventStore/EventBus、SQLite 持久化、ExecutionEvent。
- 当前本地 SQLite 样例库：`pilot_events=859`、`pilot_snapshots=319`、`task_id/trace_id=22`、`step_id=90`、`artifact_id=87`、`approval_id=64`。
- 新增 DAG benchmark 证据：`reports/benchmark_dag.md/json`，50 组模拟办公 DAG 中串行平均约 `356ms`，DAG 并发平均约 `138ms`，缩短约 `61%`。面试里仍按“约 45%+，取决于 DAG 并行宽度”讲，不把它说成生产 SLA。

## 60 秒讲法

> Agent-Hub 是我做的一个办公任务 Agent 运行时。它解决的不是单纯聊天，而是用户在飞书里发一个比较模糊的任务后，系统怎么把它转成可审批、可追踪、可恢复的执行流程。我把任务抽象成 Workspace、Task、Plan、PlanStep、Approval、Artifact 和 ExecutionEvent，所有状态变化都写事件流，Dashboard 和飞书看到的是同一条事实。技术上，通用 AgentPipeline 支持结构化路由、DAG 分层并发、RAG 和 ReAct；Pilot 业务链路更强调审批、产物和失败恢复。数据口径上，简历里的轨迹、50 组任务和 QA 评测都来自本地模拟、脚本压测和自建评测集，不是线上真实用户数据。

## 2 分钟讲法

> 这个项目的核心是把 Agent 放进一个可控的办公流程里。入口层支持 API 和飞书，飞书消息先经过 webhook/长连接规范化为 InboundRequest，再统一进入 UnifiedTurnRuntime；AgentTurnLoop 在同一回合里决定直接回答、查询进度还是调用 start_pilot_task。进入 Pilot 后，系统创建 Task，生成 Plan 和 PlanStep；计划和高风险步骤会进入审批，审批通过后由 ExecutionEngine 调用 Skill，生成 Brief、SlideSpec、PPTX、Drive 分享链接和 Summary 等 Artifact。
>
> 我主要做了三类事情。第一是执行过程数据化，把 task、plan、step、approval、skill、artifact 的状态统一记录成 ExecutionEvent，用 trace_id/task_id 串起来，方便 Dashboard 回放和失败定位。第二是任务编排和可靠性，通用 AgentPipeline 用 Kahn 拓扑分层和 asyncio.gather 并行执行同层子任务；Pilot 链路为了审批一致性，按 DAG 层顺序推进，并支持 blocked 后 resume、步骤重试和模板 fallback。第三是检索评估闭环，用 pgvector + BM25 + RRF 做混合检索，并保留评测脚本计算 Recall@5、Precision@5、MRR。
>
> 需要说明的是，这是个人/比赛型项目，没有企业真实数据。简历里的指标是离线样本和本地演示环境下得到的：轨迹来自 EventStore 事件，50 组任务来自办公任务模拟 DAG，80+ QA 来自自建问答集。面试里我会强调它是可复现的工程原型，而不是线上生产系统。

## 数据怎么来的

| 数据 | 面试口径 | 证据 |
|---|---|---|
| 100+ Agent 执行轨迹 | 指执行事件/轨迹点，不是 100 个真实用户任务。每个任务会产生 task.created、plan.generated、step.status_changed、approval.requested、skill.invoked、artifact.created 等事件。 | 当前 `pilot_events=859`，`task/trace=22`，事件类型可查 SQLite。 |
| 50 组办公任务 | 人工构造的办公任务 DAG，用于比较串行和通用 AgentPipeline 的 DAG 分层并发调度。 | `scripts/benchmark_dag.py`、`reports/benchmark_dag.md/json`。 |
| 80+ 自建 QA | 按制度文档、接口字段、审批流程、项目说明和常见办公问法扩写的标注集；用于比较 vector-only 和 hybrid retrieval。 | `eval/evaluator.py`、`scripts/evaluate.py`、`scripts/build_eval_dataset.py` 提供评测入口；面试时承认是自建小规模集。 |
| 45% 耗时下降 | 指通用编排内核的模拟 I/O 型子任务调度收益，不是飞书审批全链路端到端耗时。 | 本地 50 组报告约 61%，对外保守说 45%+。 |
| 95% 可追溯率 | 指模拟任务中能通过 task_id/trace_id 找到关键事件链和失败 step 的比例。 | EventStore + Snapshot + Dashboard 回放。 |

## 四条简历 bullet 的追问口径

### 轨迹数据标准化

你负责的点：

- 统一封装任务执行、工具调用、审批回调、产物生成和异常状态。
- 用 ExecutionEvent 记录 task、plan、approval、step、skill、artifact 等关键事件。
- Dashboard/SSE 可以按任务回放历史事件并订阅实时事件。

答法：

> 轨迹不是手写日志，而是执行过程中自动产生的业务事件。定位问题时可以沿着 task_id/trace_id 看任务从创建、规划、审批、执行到失败/成功的全过程，所以定位到失败步骤会比翻日志快很多。

### DAG 任务编排引擎

你负责的点：

- Function Calling 输出结构化 plan。
- Pydantic 做 Schema 校验，避免模型返回不可执行计划。
- 通用 AgentPipeline 用 Kahn 拓扑分层，同层 `asyncio.gather` 并行。
- Pilot 执行层更强调审批门控和恢复续跑，所以同层顺序推进。

答法：

> 我会区分两层：通用 AgentPipeline 证明并行调度能力，Pilot 证明办公流程可控。简历里的 45% 是通用编排内核的 benchmark，不是飞书审批全链路。

### 审批与失败恢复机制

你负责的点：

- write/share/admin 类风险步骤默认 requires_approval。
- 创建文档、上传文件、群聊回传等动作先 dry-run，再审批。
- 审批卡片回调后更新 approval 和 step 状态。
- 支持 blocked task resume，已完成步骤不会重复跑。

答法：

> 我没有让模型直接执行外部写操作。模型最多生成计划，真正执行前还要经过技能白名单、风险等级、dry-run 和审批门控。

### 混合检索与评估闭环

你负责的点：

- pgvector 做 dense retrieval。
- BM25 做 sparse retrieval。
- RRF 融合双路排名。
- LangGraph/Reflection 做检索、评估、重写、生成。
- Recall@5 用自建 QA 集评估。

答法：

> 单路向量召回对语义问题友好，但容易漏掉专有名词、字段名和流程编号；BM25 能补关键词召回，RRF 用排名融合降低单一路径偏差。

## 风险点与稳妥答法

| 风险点 | 稳妥答法 |
|---|---|
| 数据不是线上真实数据 | 明确说是本地 Demo、脚本压测、自建评测集；重点讲采集口径、指标公式和可复现脚本。 |
| Pilot 执行层不完全并行 | 区分通用 AgentPipeline 的并行调度和 Pilot 的审批执行链路。 |
| LangGraph 是否驱动全系统 | LangGraph 只用于 ReflectionAgent 的检索反思/重写子流程，主编排是自研 DAG。 |
| 飞书真实接入是否完整 | webhook/长连接/卡片回调/技能封装已实现；真实 Drive 分享依赖凭据，保留 fake fallback。 |
| Agent 味不够 | 承认这是 workflow-controlled agent：LLM 做语义理解、规划补全、检索重写和内容生成，执行层用确定性状态机兜住。 |
| 安全模块是否成熟 | 说成“入口风险防护 + 高风险动作审批”，不吹生产级安全体系。 |

## 反问时可引出的亮点

> 这个项目让我比较有感触的是，企业 Agent 的难点不在“模型能不能回答”，而在“能不能被控制和复盘”。所以我把重点放在任务状态、审批、失败恢复、事件追踪和评估闭环上。
'@

Write-Note -RelativePath "40_Projects\办公Agent数据生产与任务编排平台\Agent执行链路与任务编排.md" -Content @'
---
tags:
  - project
  - agent
  - orchestration
  - interview
  - benchmark
---

# Agent执行链路与任务编排

关联：[[办公Agent项目-面试讲解卡]]、[[AI Agent与MCP Skills]]、[[消息队列与异步任务]]、[[简历项目校准与量化口径]]

## 为什么需要任务编排

复杂办公任务不是一次模型调用能完成的。比如“根据资料生成一份路演 PPT 并上传分享”，至少包括上下文读取、知识检索、Brief 生成、SlideSpec 生成、PPTX 渲染、上传、分享和总结。任务编排的价值是让每一步都可追踪、可审批、可重试、可复盘。

## DAG 的价值

- 表达依赖关系：B 依赖 A 的结果。
- 支持并行：互不依赖的节点可以并发执行。
- 支持失败定位：知道哪个节点失败、失败前后发生了什么。
- 支持恢复：失败节点或 blocked 节点恢复，不必重跑全部任务。

## 本项目里的两层编排

面试时一定要分清两层：

| 层 | 代码位置 | 真实能力 | 面试用途 |
|---|---|---|---|
| 通用 AgentPipeline | `src/agent_hub/core/pipeline.py` | Kahn 拓扑分层；同层 `asyncio.gather` 并发；适合 I/O 型子任务 | 用来解释“DAG 并行调度降低耗时” |
| Pilot ExecutionEngine | `src/agent_hub/pilot/services/execution.py` | 按 DAG 层推进；同层顺序执行；审批门控、Artifact、blocked/resume | 用来解释“办公流程可控、可审批、可恢复” |

一句话：

> 通用 Agent 层强调并行效率，飞书 Pilot 层强调企业流程里的审批安全和状态一致性。

## 45% 耗时下降怎么讲

项目已补了可复现脚本：

```text
scripts/benchmark_dag.py
reports/benchmark_dag.md
reports/benchmark_dag.json
```

当前本地报告：

```text
scenarios = 50
rounds = 1
avg serial = 356.28 ms
avg dag = 137.89 ms
speedup = 2.58x
reduction = 61.30%
```

对外建议口径：

> 我构造了 50 组办公任务 DAG，每组包含上下文读取、策略检查、知识检索、指标读取、附件解析、owner 查询、Brief 生成、风险摘要和最终汇总等 9 个模拟 I/O 型子任务。串行基线是按任务列表逐个 await；DAG 方案是 Kahn 拓扑分层，同层用 asyncio.gather 并发执行。当前本地报告显示缩短约 61%，但面试里我会保守说约 45%+，因为真实收益取决于 DAG 并行宽度、外部 API 延迟和限流。

不要说：

- 不要说 Pilot 飞书审批全链路端到端降低 45%。
- 不要说 LLM 质量提升 45%。
- 不要说所有任务都能提升 45%。

## 任务节点字段

| 字段 | 含义 |
|---|---|
| task_id | 整体任务 id |
| step_id / subtask_id | 节点 id |
| depends_on | 依赖节点 |
| kind / required_agents | 节点类型或所需 Agent |
| input_params | 节点输入 |
| output_artifact_ref | 输出产物引用 |
| status | pending/running/succeeded/failed/waiting_approval |
| risk_level | read/write/share/admin |
| requires_approval | 是否需要人工确认 |
| trace_id | 链路追踪 |

## 执行状态机

通用状态可以这样讲：

```text
pending -> running -> succeeded
                 |
                 -> failed / retryable_failed
                 |
                 -> waiting_approval -> approved -> running
```

Pilot 任务状态可以这样讲：

```text
created -> planning -> awaiting_approval -> approved -> running
                                                |
                                                -> blocked -> running
                                                |
                                                -> succeeded / failed
```

## 异常处理

- 参数错误：结构化校验失败，直接拒绝或 fallback。
- 网络超时：有限次数重试，必要时降级。
- 下游限流：排队、限流或进入 blocked。
- 模型输出格式错误：Pydantic 校验失败后回退模板计划。
- 高风险工具：进入 dry-run + 人工审批。
- 上游产物缺失：当前 step fail，事件里记录 missing refs。

## 面试回答模板

> 我没有把 Agent 当成一个黑盒聊天，而是把它放进任务编排系统。模型负责语义理解、计划补全和内容生成，执行器负责状态机、权限、超时、重试、审批和事件记录。通用 Pipeline 可以用 DAG 并发提高 I/O 型任务效率；Pilot 业务链路则优先保证审批、产物和恢复语义正确。
'@

Write-Note -RelativePath "40_Projects\办公Agent数据生产与任务编排平台\多Agent通信权限与可靠性.md" -Content @'
---
tags:
  - project
  - multi-agent
  - reliability
  - interview
---

# 多Agent通信权限与可靠性

关联：[[办公Agent项目-面试讲解卡]]、[[AI Agent与MCP Skills]]、[[高可用容灾备份与监控]]、[[Agent执行链路与任务编排]]

## 面试定位

这个项目不要强讲“多个 Agent 自主协商”。更稳的说法是：

> workflow-controlled agent：LLM 和不同 Agent 能力参与路由、检索、工具调用、反思和生成，但执行层由确定性的 DAG、状态机、权限和审批策略控制。

这样更符合当前代码，也更符合办公场景的安全诉求。

## 什么时候需要多 Agent / 多能力分工

适合拆分：

- 规划、检索、工具执行、反思校验职责明显不同。
- 工具域差异大，比如文档、飞书、检索、PPT 渲染。
- 希望按能力隔离权限，避免模型直接调用高风险外部 API。
- 需要把中间结果沉淀为事件和 Artifact，方便恢复。

不适合拆分：

- 任务很短，一次普通问答即可完成。
- Agent 之间需要共享大量原始上下文，拆分反而增加噪音。
- 没有明确评估标准，容易变成“看起来很智能”的不可控流程。

## 本项目的角色映射

| 角色/模块 | 能力 | 权限边界 |
|---|---|---|
| DecisionRouter / ModelGateway | 意图识别、计划补全、PlanProfile 选择 | 只能产出结构化决策，不直接执行外部写操作 |
| RetrievalAgent / RAGPipeline | pgvector、BM25、RRF 检索 | 只读知识库 |
| LLMAgent / ReflectionAgent | 内容生成、ReAct、检索评估和 Query Rewrite | 工具调用仍受 ToolRegistry / SkillRegistry 限制 |
| ExecutionEngine | 状态机推进、Skill 调用、Artifact 保存 | 按 risk_level、requires_approval、idempotency_key 控制 |
| ApprovalService | 计划审批、步骤审批、审批回调状态 | 高风险动作必须经过审批 |
| EventStore / Dashboard | 事件回放、状态可观测 | 只展示事实流，不替代业务状态机 |

## 通信方式

- 共享任务状态：Task / Plan / PlanStep / Approval / Artifact。
- 事件日志：ExecutionEvent 记录关键状态变化，适合审计和复盘。
- Artifact 引用：下游步骤通过 `inputs_from` 读取上游产物，而不是无限传上下文。
- SkillRegistry：用结构化 SkillSpec 声明副作用、审批要求、scope、dry-run 能力。

## 权限控制

- RBAC：普通用户不能直接触发管理员工具。
- 技能白名单：模型只能选择注册过的 Skill。
- 参数级限制：Skill 接口只暴露业务参数，不暴露底层飞书 client。
- 人工确认：写文档、上传 Drive、群聊回传等高风险动作进入审批。
- 审计：记录调用人、任务、步骤、技能、状态和错误。

## 可靠性

- 每个 Agent/Skill 输出结构化结果。
- 模型输出先经过 Pydantic 校验和模板 fallback。
- 失败结果进入统一事件流，按 task_id/trace_id 可定位。
- Pilot 当前层内顺序推进，避免一次任务同时产生多个待审批点。
- blocked 后 resume 会跳过已完成步骤，避免重复生成/重复上传。

## 面试回答模板

> 多 Agent 的关键不是“多”，而是职责和权限边界。我这个项目里更准确地说是 workflow-controlled agent：模型负责理解和补全计划，Retriever 负责检索，Skill 负责受控工具调用，ExecutionEngine 负责状态机和审批。这样牺牲了一部分完全自主性，但换来了可追踪、可审批、可恢复。
'@

Write-Note -RelativePath "50_Career\02_实习准备\腾讯一面\项目讲解与追问脚本.md" -Content @'
---
tags:
  - career
  - project
  - interview
  - tencent
---

# 项目讲解与追问脚本

## 60 秒自我介绍

我主要做过两个 AI 应用工程项目：一个是接入飞书的办公 Agent 任务编排平台，另一个是 Go 实现的多模型推理与 RAG 数据服务平台。前者更偏 Agent 工作流、审批、DAG 编排、事件追踪和混合检索，后者更偏 Go 后端、多模型网关、SSE 流式输出、Redis/MySQL/RabbitMQ 和 MCP 工具服务。我比较关注的不只是“把模型接起来”，而是把模型能力放进可追踪、可恢复、可评估的数据链路里。腾讯游戏数据/运营开发需要后端、数据链路和平台稳定性，这和我的项目经历比较匹配。

## 项目一：办公 Agent 数据生产与任务编排平台

入口：[[办公Agent项目-面试讲解卡]]

### 30 秒版本

> Agent-Hub 是我做的一个飞书办公任务 Agent 运行时。它把 IM 里的模糊任务请求转成 Task、Plan、PlanStep、Approval、Artifact 和 ExecutionEvent，让任务从规划、审批、执行到产物交付都可追踪、可恢复。简历里的数据指标来自本地事件库、模拟任务 benchmark 和自建 RAG 评测集，不是线上真实用户数据。

### 2 分钟版本

> 这个项目的目标是把办公场景里的数据生产、任务拆解和工具调用自动化。系统先把飞书消息或 API 请求规范化，判断是普通问答、进度查询还是真正任务；如果是任务，就进入 Pilot 运行时，创建 Task，生成 Plan 和 PlanStep，对计划和高风险步骤做审批，然后调用 Skill 生成 Brief、SlideSpec、PPTX、Drive 分享链接和最终 Summary。
>
> 我重点做了三块。第一是执行过程数据化，把 task、plan、step、approval、skill、artifact 等状态统一写成 ExecutionEvent，用 trace_id/task_id 串起来。当前本地 SQLite 有 859 条事件、22 条任务级 trace，可以支撑“轨迹数据标准化”的讲法。第二是任务编排和可靠性，通用 AgentPipeline 使用 Kahn 拓扑分层和 asyncio.gather 执行同层子任务；我补了 50 组模拟办公 DAG 的 benchmark，串行平均约 356ms，DAG 并发约 138ms，缩短约 61%，面试里保守说 45%+。Pilot 飞书链路则为了审批和恢复一致性，同层步骤顺序推进。第三是 RAG 检索评估，用 pgvector + BM25 + RRF 做混合召回，并用自建 QA 集按 Recall@5、Precision@5、MRR 做离线评估。
>
> 这个项目我会定位成工程原型，不会说成线上生产系统。它最能体现的是：我知道如何定义数据、记录过程、设计指标、解释边界，并把 LLM 能力落进可控后端流程。

### 高频追问

- 为什么要任务 DAG，而不是简单串行调用？见 [[Agent执行链路与任务编排]]。
- 通用 AgentPipeline 和 Pilot ExecutionEngine 的区别是什么？
- 50 组任务 benchmark 怎么复现？见 `D:\Agent-Hub\reports\benchmark_dag.md`。
- 多 Agent 如何通信、共享上下文和控制权限？见 [[多Agent通信权限与可靠性]]。
- 工具调用失败怎么办？如何保证幂等和可追踪？
- Agent 记忆模块怎么设计？怎么避免脏记忆？见 [[Agent记忆模块设计与评测]]。
- 如果要接入企业内部系统，安全边界怎么设计？
- 简历里的 100+ 轨迹、45% 降耗、95% 可追溯率、Recall@5 +10% 是怎么来的？见 [[简历项目校准与量化口径]]。

### 被问“数据都是假的，可信吗？”

> 我不会把这些说成线上生产数据。可信的地方在于口径可复现：轨迹来自 EventStore，任务耗时来自固定 seed 的 benchmark，RAG 指标来自有 relevant_doc_ids 的自建 QA 集。它们证明的是我设计和验证工程链路的方法，不代表真实企业上线后的泛化效果。

## 项目二：多模型推理与 RAG 数据服务平台

入口：[[RAG数据服务项目-面试讲解卡]]

2 分钟版本：

> 这个项目是一个 Go 实现的 AI 应用服务后台，用 Gin 提供 HTTP API，统一接入 OpenAI、Ollama 等模型，支持多轮对话、SSE 流式输出、RAG 知识库、图像分类、TTS 和 MCP 工具服务。我重点做了四块：第一，用 Provider 接口和工厂模式抽象聊天补全、流式输出和上下文参数，降低新增模型接入成本；第二，用 goroutine 做 SSE 逐 token 推送，把模型调用和消息持久化解耦；第三，用 Redis 缓存热点会话和 JWT 状态，结合 MySQL ORM 连接池降低重复查询；第四，基于 mcp-go 封装 RAG、TTS、图像分类等工具，为上层 Agent 提供标准化工具入口。

高频追问：

- 工厂模式如何支持 OpenAI/Ollama 等模型热切换？
- SSE 为什么比普通 HTTP 更适合模型输出？见 [[SSE流式响应与多模型调用]]。
- goroutine 如何避免泄漏？context 取消如何传递？见 [[Go服务端工程化]]。
- Redis 会话缓存和 MySQL 最终一致性怎么处理？
- Redis 为什么快？Lua 脚本执行中宕机怎么兜底？见 [[GopherAI专项面试题库]]。
- RabbitMQ 在消息持久化里承担什么角色？
- MCP 工具服务和 Function Calling 的关系是什么？
- 首 Token 1 秒、阻塞下降 60%、缓存命中 80% 是怎么来的？见 [[简历项目校准与量化口径]]。

## 项目表达公式

每个项目都按下面顺序回答：

1. 背景：解决谁的什么问题。
2. 架构：请求如何流动，核心模块是什么。
3. 数据：过程数据怎么记录，指标怎么定义。
4. 你的贡献：你负责的模块、关键设计、代码实现。
5. 难点：准确性、稳定性、性能、安全、成本中的 1 到 2 个。
6. 方案：为什么这样设计，有什么替代方案。
7. 结果：指标、复盘、边界和后续优化。

## 场景题桥接

- 问数据库：把答案桥接到 [[MySQL索引事务与表设计]]。
- 问缓存：把答案桥接到 [[Redis缓存排行榜与一致性]]。
- 问日志/数据：把答案桥接到 [[数据处理日志与Canal]]。
- 问稳定性：把答案桥接到 [[高可用容灾备份与监控]]。
- 问 AI 落地：把答案桥接到 [[AI Agent与MCP Skills]] 和 [[RAG检索增强生成]]。
'@

Write-Note -RelativePath "50_Career\02_实习准备\腾讯一面\简历项目校准与量化口径.md" -Content @'
---
tags:
  - career
  - resume
  - project
  - interview
  - data
---

# 简历项目校准与量化口径

## 总原则

这些量化数据不改原数字，但面试时要把口径说清楚：

- 都是“本地模拟、Demo 链路、自建评测集、小规模压测”的工程指标，不说成线上生产指标。
- 回答时先讲统计对象，再讲公式，最后讲结论。
- 如果面试官追问“怎么验证”，优先说脚本、日志、EventStore、Benchmark、评测集，而不是泛泛说“测出来的”。
- 对腾讯游戏数据/运营开发方向，要主动把 Agent 项目转译为“事件埋点、链路追踪、指标归因、异常定位和检索评估”。

## 项目一：办公Agent数据生产与任务编排平台

本地路径：`D:\Agent-Hub`

### 本地核验到的真实模块

- FastAPI/Pydantic：`pyproject.toml` 中存在依赖，API、DTO、领域模型均有对应模块。
- 飞书接入：`connectors/feishu`、`feishu_routes.py`、approval card、webhook、longconn 均存在。
- 任务编排：`core/pipeline.py` 有 `_topological_layers` 和 `asyncio.gather`；`pilot/services/execution.py` 有 Pilot 专用拓扑分层执行、审批门控和恢复续跑。
- RAG：`rag/pipeline.py` 串联 chunk、embedding、pgvector、BM25、RRF；`hybrid_ranker.py` 实现 RRF。
- 轨迹：`pilot_events` / `ExecutionEvent` 记录 task、plan、approval、step、skill、artifact 等事件。
- 证据包：`reports/benchmark_dag.md/json` 可复现 50 组 DAG benchmark。

### 当前本地数据快照

```text
pilot_events = 859
pilot_snapshots = 319
task_id / trace_id = 22
step_id = 90
artifact_id = 87
approval_id = 64

主要事件类型：
step.status_changed = 178
artifact.status_changed = 106
task.progress = 89
skill.invoked = 89
task.status_changed = 88
artifact.created = 87
approval.requested = 64
approval.decided = 64
task.created = 22
plan.generated = 22
```

解释：

> 这些不是企业真实用户数据，而是本地演示、测试和离线脚本产生的事件样本。它们能支撑“轨迹数据标准化”和“问题定位可追踪”的讲法，但不能说成线上生产规模。

## 数字 1：100 多条 Agent 执行轨迹

原说法：

> 积累100多条 Agent 执行轨迹，基础问题定位时间由 10 分钟缩短至 2 分钟内。

建议口径：

> 这里的“轨迹”指执行事件明细/轨迹点，不是 100 个独立真实用户任务。每个任务会产生 task.created、plan.generated、approval.requested、step.status_changed、skill.invoked、artifact.created、task.completed/failed 等事件。我本地 SQLite EventStore 里有 859 条事件记录，所以简历里写 100 多条是保守口径。

统计方式：

```text
轨迹点数 = pilot_events 表记录数
任务级轨迹数 = count(distinct task_id / trace_id)
单任务平均轨迹点 = 轨迹点数 / task 数
```

定位时间口径：

- 基线：没有 trace/event dashboard 时，需要翻日志、看任务状态、复现错误，按常见失败场景人工估算约 10 分钟。
- 优化后：通过 trace_id/task_id 直接看失败 step、error、approval 状态和 artifact，2 分钟内能定位到失败节点。
- 面试时说“定位到问题模块/失败步骤”，不要说“2 分钟修复所有问题”。

## 数字 2：50 组办公任务，平均耗时降低约 45%

原说法：

> 模拟 50 组常见的办公任务，平均执行耗时对比串行方案降低约45%。

代码支撑：

- `core/pipeline.py`：通用 AgentPipeline 支持 DAG 拓扑分层，同层 `asyncio.gather` 并行。
- `scripts/benchmark_dag.py`：50 组模拟办公 DAG，比较串行和 DAG 分层并发。
- `reports/benchmark_dag.md/json`：当前报告串行平均约 `356ms`，DAG 并发平均约 `138ms`，缩短约 `61%`。
- 注意：`pilot/services/execution.py` 的飞书 Pilot 执行层为了审批、Artifact 和 resume 一致性，同层 step 顺序推进；不要把它说成所有飞书审批链路都强并行。

建议口径：

> 50 组是我构造的办公任务模拟 DAG，包括上下文读取、策略检查、知识检索、指标读取、附件解析、owner 查询、Brief 生成、风险摘要和最终汇总。对每组任务分别跑串行 await 和 DAG 分层并发，记录端到端耗时，最后取平均下降比例。这个指标反映的是通用编排内核中 I/O 型子任务并行带来的加速，不是线上生产吞吐，也不是飞书审批全链路 SLA。

公式：

```text
单组下降比例 = (串行耗时 - DAG 并行耗时) / 串行耗时
平均下降比例 = 50 组下降比例求平均
```

为什么能到 45%：

- 检索、工具调用、上下文读取等 I/O 型节点可以并行。
- 最终汇总、产物生成这类依赖节点仍需等待上游。
- 所以不是理论极限加速，而是部分并行后的中等幅度下降。

## 数字 3：状态可追溯率 95%+

原说法：

> 支持失败步骤级恢复，任务状态可追溯率提升至95%以上。

建议口径：

> 我把任务、计划、步骤、审批、技能调用、产物都事件化，核心状态迁移都写入 EventStore。95% 指的是模拟任务中，能够通过 task_id/trace_id 找到状态链路和失败 step 的比例。

统计方式：

```text
可追溯率 = 能通过 trace_id/task_id 找到完整关键事件链的任务数 / 模拟任务总数
关键事件链 = task.created + plan.generated + step.status_changed + skill.invoked/approval + task.completed/failed
```

面试补充：

- 不是所有底层异常都有完整业务语义，比如外部 API 突然断网可能只有 error event。
- 但核心任务流都能追踪到步骤级，足够定位是规划、审批、工具调用还是产物生成失败。

## 数字 4：Recall@5 提升约 10%

原说法：

> 在80多条自建办公问答集上，Recall@5 较单路向量检索提升约10%。

代码支撑：

- `rag/pipeline.py`：Dense + Sparse 双路检索，RRF 融合。
- `eval/evaluator.py`：支持 Precision@K、Recall@K、MRR。
- `scripts/evaluate.py` / `scripts/build_eval_dataset.py`：有评测数据集与指标计算入口。

建议口径：

> 我构造了 80 多条办公问答样本，每条标注相关文档或 chunk。分别跑单路向量检索和 pgvector + BM25 + RRF 混合检索，比较 Recall@5。提升约 10% 指的是平均 Recall@5 的绝对提升，主要来自关键词、专有名词、接口字段和审批流程编号被 BM25 补召回。

公式：

```text
Recall@5 = 前 5 个检索结果命中的相关文档数 / 该问题相关文档总数
提升 = Hybrid 平均 Recall@5 - Vector-only 平均 Recall@5
```

面试注意：

- 说“约 10 个百分点”比“提升 10%”更精确。
- 如果追问数据集来源：制度文档、项目说明、接口字段、审批流程、常见办公问法。
- 如果追问为什么有效：向量召回适合语义，BM25 适合专有名词和精确字段，RRF 用排名融合降低单路偏差。
- 如果追问当前仓库是否完整保存 80+：说仓库保留了评测框架和示例数据构造脚本，完整 80+ 是面试准备阶段的自建集，后续应该补进 `data/eval/` 做版本管理。

## 项目二：多模型推理与 RAG 数据服务平台

本地状态：Go 项目不在当前本地，只能依据你提供的简历描述校准口径。

核心技术栈：`Go`、`Gin`、`MCP`、`RabbitMQ`、`Redis`、`MySQL`、`Ollama`。

## 数字 5：模型接入成本由天级缩短至小时级

建议口径：

> 早期每接一个模型要改 controller、service、streaming 和参数结构。后来用 Provider 接口 + 工厂模式统一 Chat/Stream/Embedding 等能力，新模型只需要实现接口、注册工厂、补配置和少量测试，所以从半天到一天压到几小时。

统计方式：

```text
接入耗时 = 从新增 Provider 文件开始，到 chat/stream 两个接口测试通过为止
对比对象 = 未抽象 Provider 前的手动接入 vs 工厂模式后的新增 Provider
```

## 数字 6：首 Token 延迟 1 秒以内，阻塞时间降低约 60%

建议口径：

> 我统计的是服务端收到请求到写出第一段 SSE chunk 的时间，也就是用户感知的首 Token 延迟。优化点是把模型流式输出和消息持久化解耦，生成过程中边读边 flush，持久化走异步队列或后台 goroutine，所以接口不用等完整长文本生成和 DB 写入结束。

公式：

```text
首 Token 延迟 = first_chunk_flush_time - request_start_time
阻塞时间下降 = (同步完整生成耗时 - 流式首段可见耗时) / 同步完整生成耗时
```

## 数字 7：缓存命中率 80%，数据库访问量下降 50%

建议口径：

> 我缓存的是热点会话、JWT 状态和用户最近上下文。评测时用脚本模拟重复访问同一批会话，统计 Redis 命中次数和总查询次数；数据库访问量则用 ORM 日志或计数器统计优化前后的查询次数。

公式：

```text
缓存命中率 = redis_hit_count / cache_lookup_count
DB访问下降 = (优化前DB查询次数 - 优化后DB查询次数) / 优化前DB查询次数
```

## 数字 8：MCP 多客户端并发连接

建议口径：

> MCP 服务端把 RAG、TTS、图像分类封装成标准工具。并发连接的重点不是连接数量炫技，而是工具 schema 统一、请求隔离、超时控制和错误返回一致。

## 最稳的总回答

> 这些数字来自本地模拟、脚本压测和自建评测集，不是线上生产数据。我保留了原始日志、事件表、benchmark 报告和评测脚本的统计口径。面试里我更想强调的是：我知道指标怎么定义、怎么采集、怎么解释，也知道它们的边界。
'@

Write-Note -RelativePath "50_Career\02_实习准备\腾讯一面\腾讯一面总览.md" -Content @'
---
tags:
  - career
  - interview
  - tencent
  - MOC
---

# 腾讯一面总览

## 目标

面向腾讯游戏数据/运营开发相关一面，优先准备能直接支撑表达和手撕的内容：

- 岗位画像：[[岗位画像与考察地图]]
- 五天冲刺：[[五天冲刺计划]]
- 题库索引：[[面试题库索引]]
- 项目表达：[[项目讲解与追问脚本]]
- 简历项目校准：[[简历项目校准与量化口径]]
- 手撕清单：[[高频手撕题清单]]
- 全真模拟：[[全真模拟与复盘表]]
- 外部线索：[[资料来源与岗位线索]]

## 本轮主线

腾讯游戏数据/运营开发方向更可能看重：

- 数据链路：数据怎么产生、怎么记录、怎么追踪、怎么复盘。
- 后端稳定性：超时、重试、幂等、降级、审批、恢复。
- 指标口径：简历里的数字怎么定义、怎么采集、怎么复现。
- AI 工程落地：RAG/Agent 不是炫技，而是服务于检索、数据生产、运营效率和可观测性。

办公 Agent 项目要主动转译成：

> 一次自然语言任务进入系统后，如何变成结构化执行数据，再基于这批数据做状态追踪、失败定位、检索评估和策略迭代。

## 知识库分工

本目录只存“面试作战信息”：计划、优先级、模拟题、复盘、外部线索。

算法模板统一沉淀到 [[算法能力地图]] 和 `20_Algorithm/03_算法模板`，高频入口见 [[高频手撕题清单]]。

项目相关知识统一沉淀到 [[项目作品集地图]]、具体项目目录和 [[Project八股总览]]。

工程八股可以从 [[工程能力地图]] 进入，但本轮会优先链接到项目八股，因为腾讯运营开发一面更容易从项目落地追到数据库、缓存、并发、数据处理和稳定性。

## 优先级

| 优先级 | 主题 | 目标 |
|---|---|---|
| P0 | 项目数据口径 | 能把 100+ 轨迹、50 组 DAG、45% 降耗、95% 可追溯、Recall@5 +10% 讲清来源和边界 |
| P0 | 项目/RAG/Agent/SSE | 能用 2 分钟讲清项目，能接住架构、难点、指标、取舍追问 |
| P0 | MySQL/Redis/数据同步 | 能从业务场景解释索引、事务、缓存一致性、排行榜、Canal |
| P0 | Go 并发与服务端基础 | 能讲清 goroutine、channel、context、slice/map、锁和协程泄漏 |
| P1 | 手撕算法 | LRU、链表环、二叉树、岛屿、TopK、滑窗、二分、DP |
| P1 | 网络/OS | TCP/TLS/HTTP、IO 多路复用、进程线程协程、内存和 GC |
| P2 | 分布式/消息队列/AI 深度 | 展示拓展深度，不抢占核心准备时间 |

## 面试前 5 分钟开口版

1. 项目一句话：飞书办公任务 Agent 运行时，把 IM 任务转成可审批、可追踪、可恢复的结构化执行流。
2. 数据一句话：指标来自本地 EventStore、DAG benchmark、自建 RAG QA，不是线上真实数据，但口径可复现。
3. 腾讯转译：这和游戏数据里的埋点、链路追踪、指标归因、异常定位是相通的。
4. 风险边界：通用 AgentPipeline 支持 DAG 并发；Pilot 飞书审批链路为了状态一致性顺序推进。

## 每日使用方式

1. 先按 [[五天冲刺计划]] 完成当天 P0。
2. 每天至少练 3 道 [[高频手撕题清单]] 中的题。
3. 所有项目追问统一补到 [[项目讲解与追问脚本]] 或具体项目卡片。
4. 每天结束在 [[全真模拟与复盘表]] 记录“答不顺的问题”和“下一次开口版本”。
'@

Write-Note -RelativePath "50_Career\02_实习准备\腾讯一面\岗位画像与考察地图.md" -Content @'
---
tags:
  - career
  - tencent
  - interview
---

# 岗位画像与考察地图

## 岗位判断

腾讯游戏数据/运营开发方向不是单纯 CRUD，也不是纯算法岗。更像“面向运营、数据、平台和稳定性的后端工程”：

- 为游戏运营、数据分析、活动配置、日志处理、内部平台提供工程能力。
- 关注数据链路的准确性、延迟、可观测性和故障恢复。
- 高频技术落点包括 Go/Python、MySQL、Redis、消息队列、任务调度、日志处理、接口稳定性。
- 如果项目里有 [[RAG检索增强生成]]、[[AI Agent与MCP Skills]]、[[SSE流式响应与WebSocket对比]]，会被追问“怎么落地、怎么稳定、怎么评估、怎么降级”。

## 一面常见考察方式

| 模块 | 典型问法 | 准备入口 |
|---|---|---|
| 项目 | 讲一个你最熟的项目，架构是什么，难点是什么，数据怎么来的 | [[项目讲解与追问脚本]]、[[简历项目校准与量化口径]] |
| AI 应用 | RAG 怎么分块、召回、重排；Agent 如何调用工具 | [[RAG检索增强生成]]、[[AI Agent与MCP Skills]] |
| 后端基础 | Go 的 slice/map/channel/context，协程泄漏怎么处理 | [[Go服务端工程化]] |
| 数据库 | 索引、事务隔离、MVCC、慢查询、死锁、分页优化 | [[MySQL索引事务与表设计]] |
| Redis | zset、缓存一致性、持久化、淘汰、排行榜 | [[Redis缓存排行榜与一致性]] |
| 数据处理 | 日志清洗、幂等、延迟、Canal、批流取舍 | [[数据处理日志与Canal]] |
| 稳定性 | 超时、重试、熔断、降级、监控告警、容灾 | [[高可用容灾备份与监控]] |
| 手撕 | LRU、链表、树、岛屿、TopK、滑动窗口、二分 | [[高频手撕题清单]] |

## 面试中的主线表达

推荐把自己包装成“能把 AI 能力和后端数据平台落地的人”：

> 我比较熟悉 Go/Python 后端、RAG/Agent 工程化和数据处理链路。项目里重点做过模型调用、工具编排、流式响应、文档检索、任务调度和数据生产，因此我会从稳定性、准确性、延迟和可观测性去设计系统。

## Agent 项目如何转译成游戏数据相关能力

| Agent 项目能力 | 游戏数据/运营开发里的对应能力 |
|---|---|
| ExecutionEvent 记录任务全链路 | 玩家行为日志、运营操作日志、链路埋点 |
| trace_id/task_id 串联任务 | request_id / trace_id 串联接口、任务、异步消费 |
| DAG 编排与恢复 | 定时任务、数据加工 DAG、活动配置发布流程 |
| 审批与高风险动作门控 | 活动配置发布审批、灰度、回滚、权限审计 |
| RAG 评测集与 Recall@K | 数据口径问答、运营知识库检索、召回质量评估 |
| Dashboard/SSE 事件流 | 任务状态看板、实时进度、故障定位面板 |

面试可用句：

> 虽然项目场景是办公 Agent，但我真正做的是把一次自然语言任务变成结构化执行数据，再基于这批数据做状态追踪、失败定位、检索评估和策略迭代。这个思路和游戏数据里的日志埋点、链路追踪、指标归因、异常定位是相通的。

## 腾讯游戏数据/运营开发的场景联想

- 玩家行为日志：采集、清洗、落库、聚合、指标看板。
- 活动运营平台：配置发布、灰度、回滚、权限控制、审计。
- 排行榜/战力榜：Redis zset、定时落库、冷热数据、并发更新。
- 任务系统：批处理、补偿、重试、幂等、限流。
- AI 助手：运营问答、文档检索、数据口径解释、自动生成分析报告。
- SRE/稳定性：告警、故障定位、接口超时、数据库慢查询、缓存击穿。

## 一面答题原则

- 先讲业务目标，再讲技术方案，最后讲指标和取舍。
- 遇到项目追问时，把答案落到 [[项目量化表达与STAR]] 和 [[简历项目校准与量化口径]]。
- 遇到基础八股时，尽量绑定项目场景，不要只背定义。
- 手撕时先说边界条件，再写核心结构，最后补复杂度。
'@

Update-NoteText -RelativePath "40_Projects\办公Agent数据生产与任务编排平台\Agent-Hub项目全面介绍.md" -Updater {
    param($text)
    $text = $text.Replace(
        "Agent-Hub 是一个使用 **Python + FastAPI** 构建的多 Agent 协作中台。它不是单纯的聊天机器人，而是把 **对话理解、任务拆解、RAG 检索、工具调用、记忆管理、安全防护、审批控制、产物生成、事件流同步和飞书协作** 放到同一套工程化系统里。",
        "Agent-Hub 是一个使用 **Python + FastAPI** 构建的飞书办公任务 Agent 运行时。它不是单纯的聊天机器人，也不主讲成通用 AgentOS；更准确地说，它把 **IM 任务入口、结构化任务拆解、RAG 检索、工具调用、审批控制、产物生成、事件流同步和飞书协作** 放到一条可追踪、可审批、可恢复的工程链路里。"
    )
    $text = $text.Replace("1. **通用多 Agent 执行内核**", "1. **通用 Agent 执行内核**")
    $text = $text.Replace(
        "通用 Pipeline 和 Pilot ExecutionEngine 都支持 DAG 分层执行。难点包括：",
        "通用 Pipeline 和 Pilot ExecutionEngine 都支持 DAG 分层，但面试时必须区分：通用 `AgentPipeline` 支持同层 `asyncio.gather` 并发；Pilot `ExecutionEngine` 为了审批、Artifact 和 resume 状态一致性，同层 step 当前顺序推进。难点包括："
    )
    $text = $text.Replace(
        "Agent-Hub 不是给办公软件加一个聊天框，而是让 Agent 成为可审批、可追踪、可恢复的任务协作中台。",
        "Agent-Hub 不是给办公软件加一个聊天框，而是把 Agent 放进一个可审批、可追踪、可恢复的办公任务运行时；它的面试主线应该落在执行数据、事件追踪、审批恢复和检索评估上。"
    )
    if ($text -notmatch "## 数据与评测口径") {
        $insert = @'

# 数据与评测口径

这部分是面试最容易被追问的地方，建议主动说清楚边界：

- 轨迹数据来自系统运行时自动记录的 ExecutionEvent，不是手写日志。当前本地 SQLite 中有 `pilot_events=859`、`pilot_snapshots=319`、`task/trace=22`，可以说明任务过程已经被结构化记录。
- DAG 耗时下降来自通用 `AgentPipeline` 的模拟 benchmark，不是飞书审批全链路。新增 `scripts/benchmark_dag.py` 和 `reports/benchmark_dag.md/json`，50 组模拟办公 DAG 中串行平均约 `356ms`，DAG 并发平均约 `138ms`，对外保守讲“45%+，取决于并行宽度和外部 API 限流”。
- RAG 的 Recall@5 口径来自自建 QA 集。仓库里有 `eval/evaluator.py`、`scripts/evaluate.py`、`scripts/build_eval_dataset.py`，可解释 Precision@K、Recall@K、MRR 和 relevant_doc_ids 标注方式。
- 所有指标都应讲成本地模拟、Demo 链路、自建评测集和小规模压测，不说成线上生产指标。

'@
        $text = $text.Replace("# 当前已实现能力边界", $insert + "# 当前已实现能力边界")
    }
    return $text
}

Update-NoteText -RelativePath "50_Career\02_实习准备\腾讯一面\面试题库索引.md" -Updater {
    param($text)
    $old = "- DAG 并行降低 45% 的实验怎么设计？串行基线是什么？"
    $new = "- DAG 并行降低 45% 的实验怎么设计？串行基线是什么？`AgentPipeline` 和 Pilot `ExecutionEngine` 的边界是什么？"
    $text = $text.Replace($old, $new)
    if ($text -notmatch "当前本地 EventStore 里 859 条事件") {
        $text = $text.Replace(
            "- 办公 Agent 里的 100+ 执行轨迹具体统计的是什么？",
            "- 办公 Agent 里的 100+ 执行轨迹具体统计的是什么？当前本地 EventStore 里 859 条事件、22 条任务级 trace 如何解释？"
        )
    }
    return $text
}

Write-Host "Updated Obsidian notes. Backups saved to: $backupRoot"

