from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.oss import (
    OpenSourceApiSource,
    OpenSourceCacheInfo,
    OpenSourceTraceStep,
    VisualMatch,
)

class OcrBlock(BaseModel):
    text: str
    confidence: float | None = None
    bbox: list[float] = Field(default_factory=list)


class ClientOcr(BaseModel):
    text: str = ""
    translated_text: str | None = None
    language: str | None = None
    blocks: list[OcrBlock] = Field(default_factory=list)


class EvidenceCard(BaseModel):
    source_type: str
    title: str
    snippet: str
    url: str | None = None
    score: float = 0.0
    ad_risk: float = 0.0
    local_signal: float = 0.0
    tourist_signal: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlaceCandidate(BaseModel):
    place_id: int | None = None
    name: str
    name_ja: str | None = None
    category: str = "unknown"
    lat: float | None = None
    lng: float | None = None
    confidence: float = 0.0
    match_reason: str = ""
    distance_meters: float | None = None
    tags: list[str] = Field(default_factory=list)
    photo_potential: float = 0.0


class RelatedPlace(BaseModel):
    place_id: int | None = None
    name: str
    relation: str
    reason: str
    distance_meters: float | None = None


class VisibleClue(BaseModel):
    clue: str
    interpretation: str
    confidence: float = 0.0


class CulturalHypothesis(BaseModel):
    name: str
    entity_type: str = "unknown"
    region: str | None = None
    rationale: str
    confidence: float = 0.0
    evidence_support: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)


class PerspectiveCard(BaseModel):
    perspective: str
    title: str
    summary: str
    reasons: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    followup_prompt: str | None = None


class DeepVisualImage(BaseModel):
    url: str
    caption: str = ""
    source: str = ""


class DeepVisualTable(BaseModel):
    caption: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class DeepVisualSection(BaseModel):
    title: str
    body: str
    bullets: list[str] = Field(default_factory=list)
    chips: list[str] = Field(default_factory=list)
    tables: list[DeepVisualTable] = Field(default_factory=list)
    images: list[DeepVisualImage] = Field(default_factory=list)


class DeepVisualCard(BaseModel):
    title: str
    body: str
    supporting_points: list[str] = Field(default_factory=list)
    next_action: str = ""
    sections: list[DeepVisualSection] = Field(default_factory=list)


class VisualMemoryItem(BaseModel):
    memory_id: str
    title: str
    entity_type: str
    region_hint: str | None = None
    thumbnail_sha256: str | None = None
    status: str = "discovered"


class VisualWorkflowSummary(BaseModel):
    provider: str = "unknown"
    model: str = "vision"
    selected_perspectives: list[str] = Field(default_factory=list)
    knowledge_used: bool = False
    confidence: float = 0.0
    uncertainty: list[str] = Field(default_factory=list)


class ShootHint(BaseModel):
    best_time: str
    stand_where: str
    face_where: str
    how_to_shoot: str
    camera_hint: str | None = None


class VisualExploreInput(BaseModel):
    image_sha256: str | None = None
    image_url: str | None = None
    image_bytes: bytes = b""
    images_bytes: list[bytes] = Field(default_factory=list)
    gps_lat: float | None = None
    gps_lng: float | None = None
    heading_degrees: float | None = None
    captured_at: datetime | None = None
    client_ocr: ClientOcr = Field(default_factory=ClientOcr)
    interest_tags: list[str] = Field(default_factory=list)
    user_context_text: str = ""
    exploration_focus: str = "auto"


class VisualExploreResponse(BaseModel):
    session_id: str
    what_it_is: str
    why_it_matters: str
    why_popular_or_overhyped: str
    related_places: list[RelatedPlace] = Field(default_factory=list)
    shoot_hint: ShootHint
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    confidence: float
    needs_user_confirmation: bool
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    story_title: str = ""
    narrative: str = ""
    visible_clues: list[VisibleClue] = Field(default_factory=list)
    cultural_hypotheses: list[CulturalHypothesis] = Field(default_factory=list)
    meaning_layers: dict[str, str] = Field(default_factory=dict)
    known_comparisons: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    map_memory_status: str = "discovered"
    one_line_answer: str = ""
    deep_cards: list[DeepVisualCard] = Field(default_factory=list)
    perspective_cards: list[PerspectiveCard] = Field(default_factory=list)
    visual_memory_item: VisualMemoryItem | None = None
    audio_script: str = ""
    visual_workflow_summary: VisualWorkflowSummary = Field(
        default_factory=VisualWorkflowSummary
    )
    visual_matches: list[VisualMatch] = Field(default_factory=list)
    api_sources_used: list[OpenSourceApiSource] = Field(default_factory=list)
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    knowledge_cards: list[EvidenceCard] = Field(default_factory=list)
    thinking_steps: list[OpenSourceTraceStep] = Field(default_factory=list)
    cache: OpenSourceCacheInfo = Field(default_factory=OpenSourceCacheInfo)


class VisualExploreApiRequest(BaseModel):
    image_url: str | None = None
    image_base64: str | None = None
    images_base64: list[str] = Field(default_factory=list)
    gps_lat: float | None = None
    gps_lng: float | None = None
    heading_degrees: float | None = None
    captured_at: datetime | None = None
    client_ocr_text: str = ""
    client_ocr_translated_text: str | None = None
    client_ocr_language: str | None = None
    interest_tags: list[str] = Field(default_factory=list)
    user_context_text: str = ""
    exploration_focus: str = "auto"


class VisualFollowupInput(BaseModel):
    session_id: str
    question: str
    image_url: str | None = None
    image_bytes: bytes = b""
    images_bytes: list[bytes] = Field(default_factory=list)
    previous_result: dict[str, Any] = Field(default_factory=dict)
    interest_tags: list[str] = Field(default_factory=list)
    user_context_text: str = ""
    exploration_focus: str = "auto"


class VisualFollowupApiRequest(BaseModel):
    session_id: str
    question: str
    image_url: str | None = None
    image_base64: str | None = None
    images_base64: list[str] = Field(default_factory=list)
    previous_result: dict[str, Any] = Field(default_factory=dict)
    interest_tags: list[str] = Field(default_factory=list)
    user_context_text: str = ""
    exploration_focus: str = "auto"


class VisualFollowupResponse(BaseModel):
    session_id: str
    answer: str
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)


class FollowupRequest(BaseModel):
    session_id: str
    question: str


class FollowupResponse(BaseModel):
    session_id: str
    answer: str
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)


class RankedPlace(BaseModel):
    place: PlaceCandidate
    score: float
    reasons: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
