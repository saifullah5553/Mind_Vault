"""Pydantic data contracts passed between agents.

DESIGN: Agents communicate through typed objects, not loose dicts. This gives us
validation at every hand-off, self-documenting interfaces, and an easy path to
serialize any pipeline stage to disk for checkpoint/resume. `PipelineContext` is
the single object that flows through the whole DAG, accumulating results.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TrendItem(BaseModel):
    topic: str
    category: str
    trend_score: float = 0.0
    reason: str = ""
    estimated_interest: str = "unknown"      # low | medium | high
    recommended_angle: str = ""
    source: str = ""


class ScoredTopic(BaseModel):
    topic: str
    category: str
    subcategory: str | None = None
    angle: str = ""
    virality: float = 0.0
    curiosity: float = 0.0
    evergreen: float = 0.0
    educational: float = 0.0
    emotional: float = 0.0
    competition: float = 0.0
    duplicate: float = 0.0
    total: float = 0.0


class ResearchFact(BaseModel):
    claim: str
    detail: str = ""
    source_name: str = ""
    url: str = ""
    information_type: str = "fact"           # fact | quote | stat | event | date | person
    license: str = "unknown"
    confidence: float = 0.0


class ResearchDossier(BaseModel):
    topic: str
    category: str
    facts: list[ResearchFact] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(default_factory=list)
    overall_confidence: float = 0.0


class FactVerdict(BaseModel):
    claim: str
    confidence: float
    status: str                              # approved | needs_verification | rejected
    note: str = ""


class Hook(BaseModel):
    text: str
    hook_type: str = "curiosity"
    curiosity: float = 0.0
    emotion: float = 0.0
    shock: float = 0.0
    novelty: float = 0.0
    clarity: float = 0.0
    total: float = 0.0


class Script(BaseModel):
    title: str
    hook: str
    introduction: str
    body: str
    ending: str
    cta: str
    full_text: str
    word_count: int = 0
    style: str = "netflix-documentary"
    structure: str = "hook-intro-story-lesson"


class Scene(BaseModel):
    index: int
    narration: str
    visual_prompt: str
    duration: float
    animation: str = "slow-zoom"
    text_overlay: str = ""
    image_path: str | None = None


class ScenePlan(BaseModel):
    scenes: list[Scene] = Field(default_factory=list)
    total_duration: float = 0.0


class VoiceResult(BaseModel):
    audio_path: str
    duration: float
    provider: str
    voice: str


class VideoResult(BaseModel):
    video_path: str
    duration: float
    resolution: list[int]
    engine: str
    has_captions: bool = False
    srt_path: str | None = None


class QualityReport(BaseModel):
    fact_score: float
    originality_score: float
    hook_score: float
    audio_ok: bool
    visual_ok: bool
    copyright_risk: str
    overall_score: float
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class PlatformMetadata(BaseModel):
    platform: str
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    category: str = ""


class PublishPackage(BaseModel):
    """Everything a platform uploader needs to post one video."""

    platform: str
    video_path: str
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    category: str = ""
    thumbnail_path: str | None = None
    srt_path: str | None = None
    privacy: str = "private"                 # start PRIVATE for safety; flip to public later


class PublishResult(BaseModel):
    platform: str
    status: str                              # published | dry_run | failed | skipped
    url: str = ""
    note: str = ""


class PipelineContext(BaseModel):
    """The single object threaded through the whole production DAG."""

    run_id: str
    category: str
    video_format: str = "short"              # short | long
    content_id: int | None = None

    trend: TrendItem | None = None
    topic: ScoredTopic | None = None
    dossier: ResearchDossier | None = None
    fact_verdicts: list[FactVerdict] = Field(default_factory=list)
    hooks: list[Hook] = Field(default_factory=list)
    selected_hook: Hook | None = None
    script: Script | None = None
    scene_plan: ScenePlan | None = None
    voice: VoiceResult | None = None
    presenter_path: str | None = None
    video: VideoResult | None = None
    quality: QualityReport | None = None
    metadata: list[PlatformMetadata] = Field(default_factory=list)
    publish_results: list[PublishResult] = Field(default_factory=list)

    # Free-form scratch space + stage completion tracking for resume.
    completed_stages: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
