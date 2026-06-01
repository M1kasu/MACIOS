#!/usr/bin/env python3
"""Pipeline 性能基准测试。

直接运行::

    python scripts/benchmark.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# 确保 src 在 sys.path 中（未 pip install -e 时可直接运行）
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent_hub.config.settings import get_settings
from agent_hub.core.enums import UserRole
from agent_hub.core.models import SourceChatType, SourceContext, TaskInput, UserContext
from agent_hub.core.pipeline import AgentPipeline


async def benchmark() -> None:
    settings = get_settings()
    pipeline = AgentPipeline(settings)

    test_cases: list[tuple[str, str, str]] = [
        ("帮我写一个二分查找", "user", "task_generation"),
        ("RAG的召回率怎么计算？", "user", "retrieval"),
        ("列出当前可用的 MCP 工具服务", "user", "tool_execution"),
        ("好的", "user", "group_chat"),
    ]

    header = f"{'测试用例':<30} {'预期意图':<20} {'耗时(ms)':<10} {'状态'}"
    print(header)
    print("-" * 75)

    for message, role, expected_intent in test_cases:
        ctx = UserContext(
            user_id="bench-user",
            role=UserRole(role),
        )
        task_input = TaskInput(
            user_context=ctx,
            source_context=SourceContext(
                channel="benchmark",
                chat_id="bench-session",
                chat_type=SourceChatType.DIRECT,
                sender_id="bench-user",
            ),
            raw_message=message,
            attachments=[],
        )

        start = time.monotonic()
        output = await pipeline.run_router_plan(task_input)
        elapsed = int((time.monotonic() - start) * 1000)

        print(f"{message:<30} {expected_intent:<20} {elapsed:<10} {output.status}")

    print("-" * 75)
    print("基准测试完成")


if __name__ == "__main__":
    asyncio.run(benchmark())
