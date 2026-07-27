"""SQLAlchemy models — the full Mind_Vault schema.

Every table requested across the three project stages is implemented here. JSON
columns (SQLAlchemy's portable `JSON` type) are used for flexible, evolving
fields like keyword lists and retention curves so the schema doesn't need a
migration every time an agent records a new signal.

Tables
------
- Content            : the canonical record of each piece of content
- ContentMemory      : the "Topic DNA" of every produced video (learning input)
- Analytics          : per-video, per-platform performance
- Topic              : the scored topic pipeline (idea backlog)
- Source             : provenance / licensing of every fact used
- AIMemory           : what worked / what failed (the learning store)
- Hook               : generated hooks + their measured performance
- Thumbnail          : thumbnail variants for A/B testing
- CEOReport          : weekly AI CEO strategy reports
- AgentRun           : an execution record for EVERY agent invocation (ops/audit)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database.base import Base, TimestampMixin


class ContentStatus(str, Enum):
    IDEA = "idea"
    RESEARCHED = "researched"
    SCRIPTED = "scripted"
    PRODUCED = "produced"
    QUALITY_PASSED = "quality_passed"
    QUALITY_FAILED = "quality_failed"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    FAILED = "failed"


# ── CONTENT ─────────────────────────────────────────────────────────────────
class Content(Base, TimestampMixin):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(50), index=True)          # psychology | history
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_format: Mapped[str] = mapped_column(String(20), default="short")  # short | long
    status: Mapped[str] = mapped_column(String(30), default=ContentStatus.IDEA.value, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_date: Mapped[datetime | None] = mapped_column(nullable=True)

    memory: Mapped["ContentMemory | None"] = relationship(back_populates="content", uselist=False)
    analytics: Mapped[list["Analytics"]] = relationship(back_populates="content")


# ── CONTENT MEMORY (Topic DNA) ──────────────────────────────────────────────
class ContentMemory(Base, TimestampMixin):
    __tablename__ = "content_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("content.id"), index=True)
    topic: Mapped[str] = mapped_column(String(500))
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    story_structure: Mapped[str | None] = mapped_column(String(120), nullable=True)
    script_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    thumbnail_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    visual_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    content: Mapped["Content"] = relationship(back_populates="memory")


# ── ANALYTICS ───────────────────────────────────────────────────────────────
class Analytics(Base, TimestampMixin):
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("content.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)               # click-through rate %
    avg_view_duration: Mapped[float] = mapped_column(Float, default=0.0)  # seconds
    watch_time: Mapped[float] = mapped_column(Float, default=0.0)         # total hours
    retention: Mapped[float] = mapped_column(Float, default=0.0)          # % avg retention
    retention_curve: Mapped[list | None] = mapped_column(JSON, default=list)  # [%,%,...] per decile
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    subscribers_generated: Mapped[int] = mapped_column(Integer, default=0)

    content: Mapped["Content"] = relationship(back_populates="analytics")


# ── TOPIC PIPELINE ──────────────────────────────────────────────────────────
class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    angle: Mapped[str | None] = mapped_column(Text, nullable=True)  # curiosity-driven reframing
    difficulty: Mapped[float] = mapped_column(Float, default=0.0)
    virality_score: Mapped[float] = mapped_column(Float, default=0.0)
    curiosity_score: Mapped[float] = mapped_column(Float, default=0.0)
    evergreen_score: Mapped[float] = mapped_column(Float, default=0.0)
    educational_score: Mapped[float] = mapped_column(Float, default=0.0)
    emotional_score: Mapped[float] = mapped_column(Float, default=0.0)
    competition_score: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)  # candidate|approved|rejected|used


# ── SOURCES ─────────────────────────────────────────────────────────────────
class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int | None] = mapped_column(ForeignKey("content.id"), nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    date_used: Mapped[datetime | None] = mapped_column(nullable=True)
    information_type: Mapped[str | None] = mapped_column(String(120), nullable=True)  # fact|quote|stat|event
    license: Mapped[str | None] = mapped_column(String(120), nullable=True)           # public-domain|CC-BY|...
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


# ── AI MEMORY (learning store) ──────────────────────────────────────────────
class AIMemory(Base, TimestampMixin):
    __tablename__ = "ai_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)   # topic|hook|format|structure|timing
    key: Mapped[str] = mapped_column(String(300), index=True)   # e.g. the hook text or format name
    outcome: Mapped[str] = mapped_column(String(20))            # worked | failed | neutral
    score: Mapped[float] = mapped_column(Float, default=0.0)    # measured performance
    samples: Mapped[int] = mapped_column(Integer, default=1)    # how many videos back this up
    detail: Mapped[dict | None] = mapped_column(JSON, default=dict)


# ── HOOKS ───────────────────────────────────────────────────────────────────
class Hook(Base, TimestampMixin):
    __tablename__ = "hooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int | None] = mapped_column(ForeignKey("content.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    hook_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    curiosity: Mapped[float] = mapped_column(Float, default=0.0)
    emotion: Mapped[float] = mapped_column(Float, default=0.0)
    shock: Mapped[float] = mapped_column(Float, default=0.0)
    novelty: Mapped[float] = mapped_column(Float, default=0.0)
    clarity: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    selected: Mapped[bool] = mapped_column(default=False)
    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)


# ── THUMBNAILS ──────────────────────────────────────────────────────────────
class Thumbnail(Base, TimestampMixin):
    __tablename__ = "thumbnails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    design_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected: Mapped[bool] = mapped_column(default=False)


# ── CEO REPORTS ─────────────────────────────────────────────────────────────
class CEOReport(Base, TimestampMixin):
    __tablename__ = "ceo_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(40))     # e.g. "2026-W30"
    summary: Mapped[str] = mapped_column(Text)
    findings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    actions: Mapped[list | None] = mapped_column(JSON, default=list)


# ── AGENT RUNS (operational audit for EVERY agent execution) ────────────────
class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)   # correlates a whole pipeline run
    agent: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)   # success | error | retry
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
