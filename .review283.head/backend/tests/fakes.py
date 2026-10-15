from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Returns pre-scripted AIMessages (or raises scripted exceptions) in order; bind_tools is a no-op."""

    messages: Any
    seen: ClassVar[list[list[BaseMessage]]] = []

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        ScriptedChatModel.seen.append(list(messages))
        try:
            msg = next(self.messages)
        except StopIteration:
            msg = AIMessage(content="(script exhausted)")
        if isinstance(msg, Exception):
            raise msg
        return ChatResult(generations=[ChatGeneration(message=msg)])


def ai(text: str = "", tool_calls: list[dict] | None = None, usage: dict | None = None) -> AIMessage:
    """`usage` mirrors langchain's usage_metadata: {"input_tokens", "output_tokens", "total_tokens",
    optional "input_token_details": {"cache_read": n}}."""
    return AIMessage(content=text, tool_calls=tool_calls or [], usage_metadata=usage)


def call(name: str, cid: str = "c1", **args) -> dict:
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}
