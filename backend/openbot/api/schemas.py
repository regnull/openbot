from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openbot.bot_icons import DEFAULT_BOT_ICON, validate_bot_icon

Provider = Literal["auto", "openai", "anthropic", "openrouter", "xai", "ollama"]
HANDLE_RE = r"^[a-z0-9_-]{2,32}$"
# ~3.5 MB of decoded image bytes (base64 inflates by 4/3).
MAX_IMAGE_CHARS = 4_700_000
# Per-message aggregate cap across attachments (~14 MB decoded): keeps a full row of
# max-size images from blowing up the Message.meta payload.
MAX_TOTAL_IMAGE_CHARS = 3 * MAX_IMAGE_CHARS


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
    icon: str = DEFAULT_BOT_ICON
    instructions: str = ""
    provider: Provider = "auto"
    model: str = ""
    model_settings: dict[str, Any] = {}
    tool_names: list[str] = []
    approval_tools: list[str] = []
    memory_enabled: bool = True
    enabled: bool = True

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, value: str) -> str:
        return validate_bot_icon(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str, info) -> str:
        if info.data.get("provider", "auto") != "auto" and not value:
            raise ValueError("model is required unless provider is \"auto\"")
        return value


class BotUpdate(BaseModel):
    handle: str | None = Field(default=None, pattern=HANDLE_RE)
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    instructions: str | None = None
    provider: Provider | None = None
    model: str | None = None
    model_settings: dict[str, Any] | None = None
    tool_names: list[str] | None = None
    approval_tools: list[str] | None = None
    memory_enabled: bool | None = None
    enabled: bool | None = None

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, value: str | None) -> str | None:
        return validate_bot_icon(value) if value is not None else None


class BotOut(BaseModel):
    id: str
    handle: str
    name: str
    description: str
    icon: str
    enabled: bool
    active: bool = False
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
    default_bot_handle: str | None = Field(default=None, pattern=HANDLE_RE)
    working_directory: str | None = Field(default=None, max_length=1000)


class ThreadUpdate(BaseModel):
    default_bot_handle: str = Field(pattern=HANDLE_RE)


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    kind: str = "chat"
    created_by_actor_id: str | None
    default_bot_actor_id: str | None
    default_bot_handle: str | None = None
    working_directory: str | None
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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_tokens: int | None = None
    model_calls: int | None = None
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


class ThreadUsage(BaseModel):
    """Running LLM totals over every run in a thread, for the thread header."""
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0


MAX_IMAGES = 4
MAX_NAME_CHARS = 200
DATA_URL_RE = r"^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$"


class Attachment(BaseModel):
    """One image attached to a message: a data URL plus an optional display name."""

    url: str
    name: str | None = Field(default=None, max_length=MAX_NAME_CHARS)


class MessageCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    content: str = Field(default="", max_length=20000)
    to: list[str] = []
    from_handle: str | None = Field(default=None, alias="from")
    attachments: list[Attachment] = Field(default=[], max_length=MAX_IMAGES)

    @field_validator("attachments")
    @classmethod
    def _validate_attachments(cls, v: list[Attachment]) -> list[Attachment]:
        total = 0
        for a in v:
            if not re.fullmatch(DATA_URL_RE, a.url):
                raise ValueError("attachment urls must be data URLs (data:image/png|jpeg|webp|gif;base64,...)")
            if len(a.url) > MAX_IMAGE_CHARS:
                raise ValueError("image is too large")
            total += len(a.url)
        if total > MAX_TOTAL_IMAGE_CHARS:
            raise ValueError("attachments are too large in total")
        return v

    @model_validator(mode="after")
    def _require_content_without_attachments(self) -> MessageCreate:
        if not self.content.strip() and not self.attachments:
            raise ValueError("content is required unless the message has attachments")
        return self


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
    thread_id: str
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


class BotInboxItemOut(InboxItemOut):
    """An item in a bot's inbox as the operator sees it: what woke the bot, how the run went, what it said."""
    thread_kind: str = "chat"
    run_status: str | None = None
    reply: MessageOut | None = None


class DirectPost(BaseModel):
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v


class MemoryOut(BaseModel):
    key: str
    content: str
    created_at: datetime | None
    updated_at: datetime | None


class ResumeBody(BaseModel):
    answer: str | None = None
    decisions: list[Literal["approve", "reject"]] | None = None


def to_json(model_cls, obj) -> dict:
    return model_cls.model_validate(obj).model_dump(mode="json")


def actor_out(actor) -> ActorOut:
    return ActorOut(id=actor.id, kind=actor.kind, handle=actor.handle, name=actor.name, description=actor.description,
                    enabled=actor.enabled, webhook_url=actor.external.webhook_url if actor.external else None,
                    created_at=actor.created_at, updated_at=actor.updated_at)


def bot_out(actor, *, active: bool = False) -> BotOut:
    p = actor.bot
    return BotOut(id=actor.id, handle=actor.handle, name=actor.name, description=actor.description,
                  icon=p.icon or DEFAULT_BOT_ICON, enabled=actor.enabled, active=active,
                  instructions=p.instructions, provider=p.provider, model=p.model, model_settings=p.model_settings,
                  tool_names=p.tool_names, approval_tools=p.approval_tools, memory_enabled=p.memory_enabled,
                  created_at=actor.created_at, updated_at=actor.updated_at)


class McpServerOut(BaseModel):
    name: str
    transport: str
    status: str
    enabled: bool
    oauth: bool
    url: str | None
    error: str | None
    tools: list[str]
    source: str = "db"
    authorization_url: str | None = None    # present while the server waits for the operator to authorize
    # The stored spec, secrets masked, for the edit dialog.
    command: str | None = None
    args: list[str] = []
    cwd: str | None = None
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


def _check_url(v: str) -> str:
    from urllib.parse import urlparse
    v = v.strip()
    if "${" in v:                     # a variable reference; checked after expansion, when connecting
        return v
    u = urlparse(v)
    if not u.netloc:
        raise ValueError("url must be absolute, for example https://mcp.example.com/mcp")
    local = u.hostname in ("localhost", "127.0.0.1", "::1")
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise ValueError("url must use https (http is allowed for localhost only)")
    return v


class McpServerCreate(BaseModel):
    """An MCP server added from Settings: remote (url, headers) or local stdio (command, args, env, cwd).
    `${VAR}` in any value expands from the server environment when connecting."""
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] = {}
    command: str | None = Field(default=None, max_length=2000)
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = Field(default=None, max_length=2000)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _check_url(v) if v else None

    @model_validator(mode="after")
    def _one_transport(self):
        if bool(self.url) == bool(self.command):
            raise ValueError('exactly one of "url" (remote) or "command" (local stdio) is required')
        return self


class McpServerUpdate(BaseModel):
    """Partial edit. For headers/env the dict replaces the stored one, except that an empty value keeps
    the stored secret for that key (the UI shows masks and sends them back blank)."""
    url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] | None = None
    command: str | None = Field(default=None, max_length=2000)
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _check_url(v) if v else v


class McpConnectOut(BaseModel):
    status: str
    authorization_url: str | None = None


class SettingOut(BaseModel):
    key: str
    group: str
    label: str
    description: str
    type: str
    value: Any
    default: Any
    overridden: bool
