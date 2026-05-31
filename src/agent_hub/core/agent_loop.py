"""Streaming agent turn loop.

This module keeps the first model call in the main conversation path. Planner
and Pilot actions are exposed as tools, so they are used only when the model
decides they are needed for the current turn.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from openai import AsyncOpenAI

from agent_hub.config.settings import Settings
from agent_hub.contracts.capability import ToolSpec
from agent_hub.contracts.identity import SourceContext, UserContext

logger = structlog.get_logger(__name__)

AgentLoopChunk = dict[str, Any]
AgentLoopToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class AgentLoopTool:
    """A model-visible tool and its in-process handler."""

    spec: ToolSpec
    handler: AgentLoopToolHandler


@dataclass(slots=True)
class _ToolCallParts:
    call_id: str = ""
    name: str = ""
    arguments: str = ""


class AgentTurnLoop:
    """One ReAct-style streaming turn with optional tool calls."""

    def __init__(
        self,
        *,
        settings: Settings,
        tools: list[AgentLoopTool],
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        max_rounds: int | None = None,
    ) -> None:
        self._settings = settings
        self._tools = {tool.spec.name: tool for tool in tools}
        self._client = client or AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self._model = model or settings.llm_model
        self._max_rounds = max_rounds or max(1, int(settings.react_max_rounds))

    async def run_stream(
        self,
        *,
        task_message: str,
        user_context: UserContext,
        source_context: SourceContext,
        session_id: str,
        trace_id: str,
    ) -> AsyncGenerator[AgentLoopChunk, None]:
        """Run one agent turn and yield status/tool/token chunks."""
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    user_context=user_context,
                    source_context=source_context,
                    session_id=session_id,
                ),
            },
            {"role": "user", "content": task_message},
        ]
        tool_schemas = [self._to_openai_tool(tool.spec) for tool in self._tools.values()]

        for round_index in range(1, self._max_rounds + 1):
            yield {
                "type": "model_started",
                "content": "",
                "round": round_index,
                "model": self._model,
                "trace_id": trace_id,
            }

            content_parts: list[str] = []
            tool_call_parts: dict[int, _ToolCallParts] = {}

            try:
                stream = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tool_schemas or None,
                    tool_choice="auto" if tool_schemas else None,
                    stream=True,
                    timeout=httpx.Timeout(60.0),
                )

                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    text = getattr(delta, "content", None)
                    if text:
                        content_parts.append(text)
                        yield {"type": "token", "content": text}

                    for tool_delta in getattr(delta, "tool_calls", None) or []:
                        index = int(getattr(tool_delta, "index", 0) or 0)
                        parts = tool_call_parts.setdefault(index, _ToolCallParts())
                        call_id = getattr(tool_delta, "id", None)
                        if call_id:
                            parts.call_id = call_id
                        function_delta = getattr(tool_delta, "function", None)
                        if function_delta is None:
                            continue
                        name = getattr(function_delta, "name", None)
                        if name:
                            parts.name += name
                        arguments = getattr(function_delta, "arguments", None)
                        if arguments:
                            parts.arguments += arguments
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_loop.model_call_failed", error=str(exc))
                yield {"type": "error", "content": str(exc)}
                return

            tool_calls = [
                parts
                for _, parts in sorted(tool_call_parts.items(), key=lambda item: item[0])
                if parts.name
            ]

            if not tool_calls:
                if not content_parts:
                    yield {
                        "type": "error",
                        "content": "Model returned no visible response.",
                    }
                else:
                    yield {"type": "final", "content": ""}
                return

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": call.call_id or f"call_{round_index}_{idx}",
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments or "{}",
                        },
                    }
                    for idx, call in enumerate(tool_calls)
                ],
            }
            messages.append(assistant_message)

            for call in tool_calls:
                call_id = call.call_id or f"call_{round_index}_{call.name}"
                yield {
                    "type": "tool_started",
                    "content": call.name,
                    "tool_name": call.name,
                    "call_id": call_id,
                }
                yield {
                    "type": "tool_progress",
                    "content": "running",
                    "tool_name": call.name,
                    "call_id": call_id,
                }
                result = await self._execute_tool(call, call_id, trace_id)
                if (
                    call.name == "answer_directly"
                    and isinstance(result, dict)
                    and isinstance(result.get("answer"), str)
                ):
                    answer = result["answer"]
                    if answer:
                        yield {
                            "type": "final",
                            "content": answer,
                            "tool_name": call.name,
                            "call_id": call_id,
                        }
                    return

                yield {
                    "type": "tool_finished",
                    "content": call.name,
                    "tool_name": call.name,
                    "call_id": call_id,
                    "result": result,
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": call.name,
                        "content": self._format_tool_result(result),
                    }
                )

        yield {
            "type": "error",
            "content": f"Agent loop reached max rounds ({self._max_rounds}).",
        }

    async def _execute_tool(
        self,
        call: _ToolCallParts,
        call_id: str,
        trace_id: str,
    ) -> object:
        tool = self._tools.get(call.name)
        if tool is None:
            return {"error": f"unknown tool: {call.name}"}

        try:
            arguments = json.loads(call.arguments or "{}")
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
        except json.JSONDecodeError as exc:
            return {"error": f"invalid tool arguments: {exc}"}

        logger.info(
            "agent_loop.tool_started",
            tool=call.name,
            call_id=call_id,
            trace_id=trace_id,
        )
        try:
            return await tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "agent_loop.tool_failed",
                tool=call.name,
                call_id=call_id,
                error=str(exc),
            )
            return {"error": str(exc)}

    def _build_system_prompt(
        self,
        *,
        user_context: UserContext,
        source_context: SourceContext,
        session_id: str,
    ) -> str:
        return (
            "You are Agent-Hub's primary agent loop. Reply in the user's "
            "language. Start answering directly for simple questions and "
            "greetings. Use tools only when they are needed.\n\n"
            "For complex multi-step work that needs DAG decomposition, call "
            "`run_decision_router_plan`; that tool invokes Agent-Hub's "
            "DecisionRouter and executes the resulting plan under policy. "
            "For long-running document/report/PPT style work, call "
            "`start_pilot_task`. For task progress, call `query_task_status`.\n\n"
            "Do not perform a separate intent-classification step. Decide the "
            "next action in this turn, then either answer or call a tool.\n\n"
            f"User role: {user_context.role.value}\n"
            f"Source channel: {source_context.channel}\n"
            f"Chat type: {source_context.chat_type.value}\n"
            f"Session id: {session_id}"
        )

    @staticmethod
    def _to_openai_tool(spec: ToolSpec) -> dict[str, Any]:
        parameters = spec.params_schema or {"type": "object", "properties": {}}
        if parameters.get("type") != "object":
            parameters = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": parameters,
            },
        }

    @staticmethod
    def _format_tool_result(result: object) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            return str(result)


__all__ = ["AgentLoopTool", "AgentTurnLoop"]
