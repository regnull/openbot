from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["openai", "anthropic", "openrouter", "xai"]
HANDLE_RE = r"^[a-z0-9_-]{2,32}$"


class ActorOut(BaseModel):
    id: str
    kind: str
    handle: str
    name: str
    description: str
    enabled: bool
    webhook_url: str | None = None
    created_at: datetime
    updated_at: datetime


class ActorCreate(BaseModel):
    handle: str = Field(pattern=HANDLE_RE)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    webhook_url: str | None = None
    webhook_secret: str | None = None


class ActorUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None


class BotCreate(BaseModel):
    handle: str = Field(pattern=HANDLE_RE)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    instructions: str = ""
    provider: Provider
    model: str = Field(min_length=1)
    model_settings: dict[str, Any] = {}
    tool_names: list[str] = []
    approval_tools: list[str] = []
    memory_enabled: bool = True
    enabled: bool = True


class BotUpdate(BaseModel):
    handle: str | None = Field(default=None, pattern=HANDLE_RE)
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    provider: Provider | None = None
    model: str | None = None
    model_settings: dict[str, Any] | None = None
    tool_names: list[str] | None = None
    approval_tools: list[str] | None = None
    memory_enabled: bool | None = None
    enabled: bool | None = None


class BotOut(BaseModel):
    id: str
    handle: str
    name: str
    description: str
    enabled: bool
    instructions: str
    provider: str
    model: str
    model_settings: dict[str, Any]
    tool_names: list[str]
    approval_tools: list[str]
    memory_enabled: bool
    created_at: datetime
    updated_at: datetime


class ParticipantOut(BaseModel):
    actor_id: str
    kind: str
    handle: str
    name: str


class ThreadCreate(BaseModel):
    title: str = ""
    handles: list[str] = []


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    created_by_actor_id: str | None
    external_ref: str | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    participants: list[ParticipantOut] = []


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    thread_id: str
    sender_actor_id: str | None
    sender_kind: str
    sender_name: str
    content: str
    mentions: list[str]
    hop: int
    run_id: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="meta")
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_id: str
    thread_id: str
    status: str
    interrupt: dict[str, Any] | None
    error: str | None
    langsmith_run_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunDetail(RunOut):
    events: list[RunEventOut] = []


class ThreadDetail(ThreadOut):
    messages: list[MessageOut] = []
    has_more: bool = False
    runs: list[RunOut] = []


class MessageCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    content: str = Field(min_length=1)
    to: list[str] = []
    from_handle: str | None = Field(default=None, alias="from")


class PostMessageOut(BaseModel):
    message: MessageOut
    addressed: list[str]
    unaddressed: bool


class ActorMessageCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    content: str = Field(min_length=1)
    from_handle: str | None = Field(default=None, alias="from")
    thread_id: str | None = None
    external_ref: str | None = None


class ActorMessageOut(BaseModel):
    thread: ThreadOut
    message: MessageOut
    addressed: list[str]


class InboxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_id: str
    thread_id: str | None
    kind: str
    message_id: str | None
    run_id: str | None
    payload: dict[str, Any]
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    processed_at: datetime | None
    message: MessageOut | None = None


class ResumeBody(BaseModel):
    answer: str | None = None
    decisions: list[Literal["approve", "reject"]] | None = None


def to_json(model_cls, obj) -> dict:
    return model_cls.model_validate(obj).model_dump(mode="json")


def actor_out(actor) -> ActorOut:
    return ActorOut(id=actor.id, kind=actor.kind, handle=actor.handle, name=actor.name, description=actor.description,
                    enabled=actor.enabled, webhook_url=actor.external.webhook_url if actor.external else None,
                    created_at=actor.created_at, updated_at=actor.updated_at)


def bot_out(actor) -> BotOut:
    p = actor.bot
    return BotOut(id=actor.id, handle=actor.handle, name=actor.name, description=actor.description, enabled=actor.enabled,
                  instructions=p.instructions, provider=p.provider, model=p.model, model_settings=p.model_settings,
                  tool_names=p.tool_names, approval_tools=p.approval_tools, memory_enabled=p.memory_enabled,
                  created_at=actor.created_at, updated_at=actor.updated_at)
