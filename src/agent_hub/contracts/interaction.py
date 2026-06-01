"""统一交互契约：跨通道入站请求。

定义自然语言主入口的通道无关输入格式：

- :class:`InboundRequest`   —— 来自任何通道（飞书 / API / 评测模拟器）的
  规范化入站请求；
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.contracts.identity import SourceContext, UserContext


class InboundRequest(BaseModel):
    """来自任意通道的规范化入站请求。

    飞书 / API / 评测模拟器等所有入口都应先将其特化字段映射到本模型，
    再交给 :class:`~agent_hub.runtime.agent.turn_runtime.UnifiedTurnRuntime`
    处理。入口层不做规则式意图分类。

    Args:
        trace_id:       链路追踪 ID；未传时自动生成 UUID。
        user_context:   发送者身份（user_id / role）。
        source_context: 通道信息（channel / chat_id / is_at_bot 等）。
        text:           消息正文，文件类消息可为空。
        attachments:    附件键列表（飞书 file_key 或其他平台 ID）。
        message_type:   通道原始消息类型字符串，如 ``"text"`` / ``"file"``
                        / ``"image"``。
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_context: UserContext
    source_context: SourceContext
    text: str = ""
    attachments: list[str] = Field(default_factory=list)
    message_type: str = "text"


__all__ = [
    "InboundRequest",
]
