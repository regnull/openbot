from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from openbot.bot_icons import DEFAULT_BOT_ICON

ACTIVE_RUN_STATUSES = ("running", "waiting_human")
OPEN_RUN_STATUSES = ("queued", "running", "waiting_human")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """DateTime type that always round-trips as a tz-aware UTC datetime.

    SQLite has no native timezone support, so values written as tz-aware UTC
    come back from the driver as naive datetimes. This decorator normalizes
    on the way in (converting aware datetimes to UTC, treating naive input as
    already UTC) and re-attaches UTC on the way out (treating naive values
    read back as UTC, converting any aware value to UTC just in case).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Actor(TimestampMixin, Base):
    __tablename__ = "actors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    handle: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bot: Mapped[BotProfile | None] = relationship(back_populates="actor", uselist=False, lazy="selectin",
                                                   cascade="all, delete-orphan")
    external: Mapped[ExternalProfile | None] = relationship(back_populates="actor", uselist=False, lazy="selectin",
                                                             cascade="all, delete-orphan")


class BotProfile(Base):
    __tablename__ = "bot_profiles"
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True)
    icon: Mapped[str] = mapped_column(String(32), default=DEFAULT_BOT_ICON, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    model_settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tool_names: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approval_tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    actor: Mapped[Actor] = relationship(back_populates="bot")


class ExternalProfile(Base):
    __tablename__ = "external_profiles"
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True)
    webhook_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor: Mapped[Actor] = relationship(back_populates="external")


class Thread(TimestampMixin, Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_by_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    default_bot_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    working_directory: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    hop_limit_notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ThreadParticipant(Base):
    __tablename__ = "thread_participants"
    __table_args__ = (UniqueConstraint("thread_id", "actor_id", name="uq_participant"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("actors.id", ondelete="CASCADE"), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_created", "thread_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    sender_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sender_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    hop: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class InboxItem(Base):
    __tablename__ = "inbox_items"
    __table_args__ = (Index("ix_inbox_actor_status_created", "actor_id", "status", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("actors.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_actor_thread_status", "actor_id", "thread_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("actors.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    interrupt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    langsmith_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
