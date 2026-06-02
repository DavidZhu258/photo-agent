from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.oss import OpenSourceApiSource, OpenSourceCacheInfo, OpenSourceTraceStep
from app.schemas.visual import EvidenceCard, PlaceCandidate


class TravelPlanRequest(BaseModel):
    city: str
    query: str = ""
    origin_city: str | None = None
    budget: str = ""
    travelers: int = 1
    arrive_at: datetime | None = None
    arrival_time: datetime | None = None
    question: str = ""
    interest_tags: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    fixed_itinerary: list[str] = Field(default_factory=list)
    requested_categories: list[str] = Field(default_factory=list)
    previous_context: dict[str, object] = Field(default_factory=dict)
    date_range: list[str] = Field(default_factory=list)
    current_location: dict[str, float] | None = None
    pace: str = "balanced"
    transport_mode: str = "walking"
    max_results: int = 5
    allow_web_search: bool = True
    evidence_refresh: Literal["auto", "force", "cache_only"] = "auto"

    @model_validator(mode="after")
    def normalize_query_fields(self) -> "TravelPlanRequest":
        if not self.question and self.query:
            self.question = self.query
        if not self.query and self.question:
            self.query = self.question
        if self.arrive_at is None and self.arrival_time is not None:
            self.arrive_at = self.arrival_time
        return self


class TravelRecommendation(BaseModel):
    place: PlaceCandidate
    score: float
    reasons: list[str] = Field(default_factory=list)
    caution: str
    ad_risk_label: str
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    decision: str = "conditional"
    decision_reason: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    evidence_confidence: str = "medium"
    route_minutes: float | None = None
    route_warning: str | None = None


class TravelSuggestionGroup(BaseModel):
    title: str
    intent: str
    items: list[str] = Field(default_factory=list)
    reason: str
    evidence_needed: bool = True


class TravelDisplayCard(BaseModel):
    id: str
    title: str
    category: str = ""
    subcategory: str = ""
    subtitle: str = ""
    description: str = ""
    rating: float | None = None
    review_count: int | None = None
    price: str = ""
    address: str = ""
    image_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    image_status: Literal["place_photo", "source_item", "missing"] = "missing"
    source_url: str = ""
    source_provider: str = ""
    place_id: str = ""
    photo_attributions: list[str] = Field(default_factory=list)
    reason: str = ""
    display_reason: str = ""
    lat: float | None = None
    lng: float | None = None
    tags: list[str] = Field(default_factory=list)
    trip_state: Literal["none", "liked", "planned"] = "none"
    google_maps_uri: str = ""
    directions_uri: str = ""
    match_reason: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    match_score: int = 0
    source_query: str = ""


class TravelWorkflowStep(BaseModel):
    phase: str
    actor: str
    action: str
    tools: list[str] = Field(default_factory=list)
    observation: dict[str, object] = Field(default_factory=dict)
    status: str = "completed"


class TravelSectionImage(BaseModel):
    url: str
    caption: str = ""
    source: str = ""


class TravelSectionTable(BaseModel):
    caption: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class TravelAnswerSection(BaseModel):
    id: str = ""
    title: str
    body: str = ""
    bullets: list[str] = Field(default_factory=list)
    chips: list[str] = Field(default_factory=list)
    tables: list[TravelSectionTable] = Field(default_factory=list)
    images: list[TravelSectionImage] = Field(default_factory=list)
    card_ids: list[str] = Field(default_factory=list)
    pin_ids: list[str] = Field(default_factory=list)


class TravelItineraryBlock(BaseModel):
    title: str = ""
    place_ids: list[str] = Field(default_factory=list)
    route_note: str = ""
    budget_note: str = ""
    why: str = ""
    alternatives: list[str] = Field(default_factory=list)

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class TravelItineraryDay(BaseModel):
    day: int = 1
    title: str = ""
    date: str = ""
    time_blocks: list[TravelItineraryBlock] = Field(default_factory=list)

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class TravelItineraryPlan(BaseModel):
    title: str = ""
    summary: str = ""
    days: list[TravelItineraryDay] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class TravelDecisionCard(BaseModel):
    id: str
    title: str
    decision: Literal["recommend", "conditional", "not_recommended", "data_gap"] = "recommend"
    supplier_capability: str = "places"
    category: str = ""
    reason: str = ""
    tradeoffs: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    card_id: str = ""
    source_url: str = ""
    confidence: str = "medium"


class TravelHotelOffer(BaseModel):
    id: str
    title: str
    provider: str = "serpapi_google_hotels"
    price: str = ""
    rating: float | None = None
    review_count: int | None = None
    address: str = ""
    image_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    source_url: str = ""
    booking_url: str = ""
    check_in_date: str = ""
    check_out_date: str = ""
    currency: str = ""
    display_reason: str = ""
    data_gaps: list[str] = Field(default_factory=list)


class TravelFlightOffer(BaseModel):
    id: str
    title: str
    provider: str = "serpapi_google_flights"
    airline: str = ""
    departure_airport: str = ""
    arrival_airport: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    duration: str = ""
    stops: str = ""
    price: str = ""
    currency: str = ""
    source_url: str = ""
    booking_url: str = ""
    display_reason: str = ""
    data_gaps: list[str] = Field(default_factory=list)


class TravelActivityOffer(BaseModel):
    id: str
    title: str
    provider: str = "serpapi_google_maps"
    category: str = ""
    price: str = ""
    rating: float | None = None
    review_count: int | None = None
    address: str = ""
    image_url: str = ""
    image_urls: list[str] = Field(default_factory=list)
    source_url: str = ""
    booking_url: str = ""
    lat: float | None = None
    lng: float | None = None
    display_reason: str = ""
    data_gaps: list[str] = Field(default_factory=list)


class TravelRouteOption(BaseModel):
    id: str
    title: str
    provider: str = "mapbox"
    duration: str = ""
    distance: str = ""
    mode: str = ""
    source_url: str = ""
    display_reason: str = ""
    data_gaps: list[str] = Field(default_factory=list)


class TravelPlanResponse(BaseModel):
    summary: str
    workflow_status: Literal["completed", "failed"] = "completed"
    capability_plan: dict[str, object] = Field(default_factory=dict)
    agent_errors: list[dict[str, object]] = Field(default_factory=list)
    recommendations: list[TravelRecommendation] = Field(default_factory=list)
    not_recommended: list[TravelRecommendation] = Field(default_factory=list)
    conditional_options: list[TravelRecommendation] = Field(default_factory=list)
    excluded_candidates: list[TravelRecommendation] = Field(default_factory=list)
    decision_notes: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    route_summary: dict[str, object] = Field(default_factory=dict)
    budget_summary: dict[str, object] = Field(default_factory=dict)
    transport_summary: dict[str, object] = Field(default_factory=dict)
    optional_context: dict[str, object] = Field(default_factory=dict)
    suggestion_groups: list[TravelSuggestionGroup] = Field(default_factory=list)
    category_groups: list[TravelSuggestionGroup] = Field(default_factory=list)
    resolved_intent: dict[str, object] = Field(default_factory=dict)
    intent_summary: str = ""
    plan_draft: dict[str, object] = Field(default_factory=dict)
    decision_cards: list[TravelDecisionCard] = Field(default_factory=list)
    itinerary_plan: TravelItineraryPlan = Field(default_factory=TravelItineraryPlan)
    hotel_offers: list[TravelHotelOffer] = Field(default_factory=list)
    flight_offers: list[TravelFlightOffer] = Field(default_factory=list)
    activity_offers: list[TravelActivityOffer] = Field(default_factory=list)
    route_options: list[TravelRouteOption] = Field(default_factory=list)
    narrative_answer: str = ""
    answer_sections: list[TravelAnswerSection] = Field(default_factory=list)
    followup_slots: list[str] = Field(default_factory=list)
    search_plan: dict[str, object] = Field(default_factory=dict)
    answer_mode: str = "place_cards"
    candidate_verification: list[dict[str, object]] = Field(default_factory=list)
    display_cards: list[TravelDisplayCard] = Field(default_factory=list)
    map_view: dict[str, object] = Field(default_factory=dict)
    suggestion_source: str = "none"
    api_sources_used: list[OpenSourceApiSource] = Field(default_factory=list)
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    commercial_disclosure: str = ""
    raw_provider_refs: dict[str, object] = Field(default_factory=dict)
    thinking_steps: list[OpenSourceTraceStep] = Field(default_factory=list)
    agentic_workflow: list[TravelWorkflowStep] = Field(default_factory=list)
    workflow_summary: dict[str, object] = Field(default_factory=dict)
    cache: OpenSourceCacheInfo = Field(default_factory=OpenSourceCacheInfo)
    search_used: bool = False
    search_queries: list[str] = Field(default_factory=list)
    sources_consulted: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    optional_followups: list[str] = Field(default_factory=list)
    evidence_freshness: str = "seed"
    llm_used: bool = False
    model_used: str = "deterministic"
    formatted_markdown: str = ""
    formatter_model_used: str = "none"
    reasoning_mode: str = "deterministic_ranker"
    needs_user_confirmation: bool


class TravelPlanJobCreateResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    poll_url: str
    created_at: datetime


class TravelPlanJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    response: TravelPlanResponse | None = None
    error: dict[str, object] | None = None


class EvidenceSearchRequest(BaseModel):
    city: str
    query: str
    interest_tags: list[str] = Field(default_factory=list)
    trigger_reason: str = "manual_admin"
    max_results: int = 5


class EvidenceSearchRunResponse(BaseModel):
    query: str
    city: str | None = None
    trigger_reason: str
    status: str
    result_count: int = 0
    imported_count: int = 0
    error: str | None = None
    created_at: str | None = None
