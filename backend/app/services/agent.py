from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from app.schemas.visual import (
    EvidenceCard,
    VisualExploreInput,
    VisualExploreResponse,
    VisualFollowupInput,
    VisualFollowupResponse,
)
from app.services.cache import InMemorySnapCache, RedisJsonCache
from app.services.composer import EvidenceAwareComposer
from app.services.evidence import SeedEvidenceStore
from app.services.place_resolver import HeuristicPlaceResolver
from app.services.ranking import RecommendationRanker
from app.services.vlm import (
    DeepInfraNarrativeClient,
    DeepInfraVlmClient,
    GeminiVlmClient,
    HeuristicNarrativeClient,
    HeuristicVlmClient,
)
from app.services.open_source_stack import attach_visual_metadata
from app.services.visual_history import SerperOfficialHistoryClient
from app.services.visual_workflow import enrich_visual_response
from app.config import Settings, settings


class RouteIntent(StrEnum):
    TEXT_TRANSLATION = "text_translation"
    PLACE_EXPLAIN = "place_explain"
    OBJECT_EXPLAIN = "object_explain"


@dataclass
class AgentDependencies:
    cache: object
    vlm: object
    place_resolver: object
    evidence_store: object
    composer: object
    ranker: RecommendationRanker | None = None
    narrative_client: object | None = None
    official_history_enricher: object | None = None


class VisualExploreAgent:
    """Explicit, bounded orchestration for P0 visual exploration."""

    def __init__(self, dependencies: AgentDependencies | None = None) -> None:
        self.dependencies = dependencies or AgentDependencies(
            cache=InMemorySnapCache(),
            vlm=HeuristicVlmClient(),
            place_resolver=HeuristicPlaceResolver(),
            evidence_store=SeedEvidenceStore(),
            composer=EvidenceAwareComposer(),
            ranker=RecommendationRanker(),
        )
        if self.dependencies.ranker is None:
            self.dependencies.ranker = RecommendationRanker()
        if self.dependencies.narrative_client is None:
            self.dependencies.narrative_client = HeuristicNarrativeClient()

    async def explore(self, request: VisualExploreInput) -> VisualExploreResponse:
        cache_key = self._cache_key(request)
        cached = await self.dependencies.cache.get(cache_key)
        if cached is not None:
            cached = enrich_visual_response(
                cached,
                request,
                visual_reasoning={},
                model_used=getattr(self.dependencies.vlm, "model", "vision"),
            )
            return attach_visual_metadata(
                cached,
                request,
                cache_key=cache_key,
                cache_hit=True,
                model_used=getattr(self.dependencies.vlm, "model", "vision"),
            )

        intent = self.route_intent(request)
        vlm_result = await self.dependencies.vlm.identify(request)
        history_result = await self._enrich_official_history(request, vlm_result)
        vlm_result = _merge_history_enrichment(vlm_result, history_result)
        candidates = await self.dependencies.place_resolver.resolve(request, vlm_result)
        evidence_by_place_id = await self.dependencies.evidence_store.search(
            request, candidates
        )
        ranked = self.dependencies.ranker.rank(
            candidates,
            evidence_by_place_id=evidence_by_place_id,
            interest_tags=request.interest_tags,
        )
        evidence_for_story = [
            *_top_evidence(ranked, evidence_by_place_id),
            *_history_evidence_cards(history_result),
        ]
        narrative_result = await self._compose_narrative(
            request, vlm_result, evidence_for_story
        )
        response = await self.dependencies.composer.compose(
            request,
            intent,
            candidates,
            ranked,
            evidence_by_place_id,
            visual_reasoning=vlm_result,
            narrative_result=narrative_result,
        )
        history_cards = _history_evidence_cards(history_result)
        if history_cards:
            response = response.model_copy(
                update={"evidence_cards": [*response.evidence_cards, *history_cards]}
            )
        response = enrich_visual_response(
            response,
            request,
            visual_reasoning=vlm_result,
            model_used=getattr(self.dependencies.vlm, "model", "vision"),
        )
        response = attach_visual_metadata(
            response,
            request,
            visual_reasoning=vlm_result,
            evidence_cards=evidence_for_story,
            cache_key=cache_key,
            model_used=getattr(self.dependencies.vlm, "model", "vision"),
        )
        await self.dependencies.cache.put(cache_key, response)
        return response

    async def followup(self, request: VisualFollowupInput) -> VisualFollowupResponse:
        visual_request = VisualExploreInput(
            image_url=request.image_url,
            image_bytes=request.image_bytes,
            images_bytes=request.images_bytes,
            interest_tags=request.interest_tags,
            user_context_text=_followup_context_text(request),
            exploration_focus=request.exploration_focus,
        )
        visual_reasoning = {}
        if visual_request.image_url or visual_request.image_bytes or visual_request.images_bytes:
            visual_reasoning = await self.dependencies.vlm.identify(visual_request)
        if not visual_reasoning.get("subject"):
            visual_reasoning["subject"] = (
                request.previous_result.get("what_it_is")
                or request.previous_result.get("story_title")
                or request.previous_result.get("one_line_answer")
                or ""
            )
        history_result = await self._enrich_official_history(visual_request, visual_reasoning)
        visual_reasoning = _merge_history_enrichment(visual_reasoning, history_result)
        responder = getattr(self.dependencies.narrative_client, "answer_followup", None)
        if callable(responder):
            try:
                return await responder(request, visual_reasoning)
            except Exception:
                pass
        return _heuristic_followup_response(request, visual_reasoning)

    def route_intent(self, request: VisualExploreInput) -> RouteIntent:
        text = request.client_ocr.text.strip()
        if self._is_text_heavy(text):
            return RouteIntent.TEXT_TRANSLATION
        if any(token in text for token in ("寺", "神社", "院", "城", "跡", "店")):
            return RouteIntent.PLACE_EXPLAIN
        return RouteIntent.OBJECT_EXPLAIN

    async def _compose_narrative(
        self,
        request: VisualExploreInput,
        vlm_result: dict,
        evidence_cards: list,
    ) -> dict:
        try:
            return await self.dependencies.narrative_client.compose(
                request, vlm_result, evidence_cards
            )
        except Exception as exc:
            fallback = await HeuristicNarrativeClient().compose(
                request, vlm_result, evidence_cards
            )
            fallback["provider_error"] = exc.__class__.__name__
            return fallback

    @staticmethod
    def _is_text_heavy(text: str) -> bool:
        if len(text) < 16:
            return False
        menu_markers = ("円", "営業時間", "定休日", "メニュー", "ランチ", "価格")
        has_menu_marker = any(marker in text for marker in menu_markers)
        return has_menu_marker or text.count("\n") >= 2

    def _cache_key(self, request: VisualExploreInput) -> str:
        image_hash = request.image_sha256 or self._primary_image_hash(request)
        lat = f"{request.gps_lat:.4f}" if request.gps_lat is not None else "na"
        lng = f"{request.gps_lng:.4f}" if request.gps_lng is not None else "na"
        heading = (
            f"{round(request.heading_degrees):03d}"
            if request.heading_degrees is not None
            else "na"
        )
        captured_at = (
            request.captured_at.isoformat(timespec="minutes")
            if request.captured_at is not None
            else "na"
        )
        interest_tags = "|".join(
            sorted(tag.strip().lower() for tag in request.interest_tags if tag.strip())
        )
        context_seed = "\0".join(
            [
                request.client_ocr.text.strip(),
                (request.client_ocr.translated_text or "").strip(),
                (request.client_ocr.language or "").strip().lower(),
                interest_tags,
                heading,
                captured_at,
                request.user_context_text.strip(),
                request.exploration_focus.strip().lower(),
                "official-history-v1",
                self._images_hash(request),
            ]
        )
        context_hash = hashlib.sha256(context_seed.encode("utf-8")).hexdigest()[:12]
        return f"snap:{image_hash}:{lat}:{lng}:{context_hash}"

    def _session_id(self, request: VisualExploreInput) -> str:
        image_hash = request.image_sha256 or self._primary_image_hash(request)
        return f"snap_{image_hash[:12]}"

    async def _enrich_official_history(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict,
    ) -> dict:
        enricher = getattr(self.dependencies, "official_history_enricher", None)
        enrich = getattr(enricher, "enrich", None)
        if not callable(enrich):
            return {}
        try:
            result = await enrich(request, visual_reasoning)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            notes = [str(item) for item in visual_reasoning.get("confidence_notes") or []]
            notes.append(f"官方历史补全失败：{exc.__class__.__name__}")
            visual_reasoning["confidence_notes"] = notes
            return {}

    @staticmethod
    def _primary_image_hash(request: VisualExploreInput) -> str:
        if request.image_url:
            return hashlib.sha256(request.image_url.encode("utf-8")).hexdigest()
        return hashlib.sha256(request.image_bytes).hexdigest()

    @staticmethod
    def _images_hash(request: VisualExploreInput) -> str:
        images = request.images_bytes or ([request.image_bytes] if request.image_bytes else [])
        if not images:
            return "no-images"
        digest = hashlib.sha256()
        for image in images:
            digest.update(hashlib.sha256(image).digest())
        return digest.hexdigest()[:16]


def build_visual_agent(app_settings: Settings = settings) -> VisualExploreAgent:
    vlm = HeuristicVlmClient()
    narrative_client = HeuristicNarrativeClient()
    official_history_enricher = None
    if (
        app_settings.visual_primary_provider.lower() == "gemini"
        and app_settings.google_api_key
    ):
        vlm = GeminiVlmClient(
            api_key=app_settings.google_api_key,
            model=app_settings.gemini_vision_model,
            base_url=app_settings.gemini_base_url,
            thinking_level=app_settings.gemini_thinking_level,
            media_resolution=app_settings.gemini_media_resolution,
            timeout_seconds=app_settings.external_api_timeout_seconds,
        )
    elif (
        app_settings.vlm_provider.lower() == "deepinfra"
        and app_settings.deepinfra_api_key
    ):
        vlm = DeepInfraVlmClient(
            api_key=app_settings.deepinfra_api_key,
            model=app_settings.deepinfra_vision_model,
            base_url=app_settings.deepinfra_base_url,
            timeout_seconds=app_settings.external_api_timeout_seconds,
        )
        narrative_client = DeepInfraNarrativeClient(
            api_key=app_settings.deepinfra_api_key,
            model=app_settings.deepinfra_narrative_model,
            base_url=app_settings.deepinfra_base_url,
            timeout_seconds=app_settings.external_api_timeout_seconds,
        )
    if app_settings.serper_api_key:
        official_history_enricher = SerperOfficialHistoryClient(
            api_key=app_settings.serper_api_key,
            base_url=app_settings.serper_base_url,
            timeout_seconds=app_settings.external_api_timeout_seconds,
        )
    return VisualExploreAgent(
        AgentDependencies(
            cache=RedisJsonCache(
                app_settings.redis_url,
                VisualExploreResponse,
                namespace="visual:snap",
            ),
            vlm=vlm,
            place_resolver=HeuristicPlaceResolver(),
            evidence_store=SeedEvidenceStore(),
            composer=EvidenceAwareComposer(),
            ranker=RecommendationRanker(),
            narrative_client=narrative_client,
            official_history_enricher=official_history_enricher,
        )
    )


def _top_evidence(ranked, evidence_by_place_id):
    if not ranked:
        return []
    top_place_id = ranked[0].place.place_id
    return evidence_by_place_id.get(top_place_id, [])


def _history_evidence_cards(history_result: dict) -> list[EvidenceCard]:
    cards = history_result.get("evidence_cards")
    if not isinstance(cards, list):
        return []
    return [card for card in cards if isinstance(card, EvidenceCard)]


def _merge_history_enrichment(
    visual_reasoning: dict,
    history_result: dict,
) -> dict:
    if not history_result:
        return visual_reasoning
    merged = dict(visual_reasoning)
    existing_layers = (
        dict(merged.get("meaning_layers"))
        if isinstance(merged.get("meaning_layers"), dict)
        else {}
    )
    history_layers = (
        dict(history_result.get("meaning_layers"))
        if isinstance(history_result.get("meaning_layers"), dict)
        else {}
    )
    if history_layers:
        merged["meaning_layers"] = {**existing_layers, **history_layers}
    sources = history_result.get("official_history_sources")
    if isinstance(sources, list) and sources:
        merged["official_history_sources"] = [item for item in sources if isinstance(item, dict)]
    notes = [
        *[str(item) for item in merged.get("confidence_notes") or []],
        *[str(item) for item in history_result.get("confidence_notes") or []],
    ]
    if notes:
        merged["confidence_notes"] = list(dict.fromkeys(item for item in notes if item.strip()))
    return merged


def _followup_context_text(request: VisualFollowupInput) -> str:
    parts = [
        request.user_context_text.strip(),
        f"用户追问：{request.question.strip()}",
        f"上一轮识别：{_previous_summary(request.previous_result)}",
    ]
    return "\n".join(part for part in parts if part)


def _previous_summary(previous_result: dict) -> str:
    values = [
        previous_result.get("one_line_answer"),
        previous_result.get("what_it_is"),
        previous_result.get("story_title"),
        previous_result.get("narrative"),
    ]
    return " / ".join(str(value).strip() for value in values if str(value or "").strip())[:900]


def _heuristic_followup_response(
    request: VisualFollowupInput,
    visual_reasoning: dict,
) -> VisualFollowupResponse:
    subject = (
        str(visual_reasoning.get("subject") or "").strip()
        or str(request.previous_result.get("what_it_is") or "").strip()
        or str(request.previous_result.get("story_title") or "").strip()
        or "这张照片"
    )
    clue = ""
    clues = visual_reasoning.get("visible_clues")
    if isinstance(clues, list) and clues:
        first = clues[0]
        if isinstance(first, dict):
            clue = str(first.get("interpretation") or first.get("clue") or "").strip()
    answer = (
        f"围绕{subject}来看，{request.question.strip()} 可以先从画面里已经确认的主体、位置线索和上一轮判断出发。"
        f"{(' 关键线索是：' + clue + '。') if clue else ''}"
        f"{(' 官方历史资料里可参考：' + _official_history_text(visual_reasoning) + '。') if _official_history_text(visual_reasoning) else ''}"
        "如果你想把它放进旅行安排，我会优先核对地图位置、周边动线和现场可见标识。"
    )
    evidence_cards = _official_history_cards_from_reasoning(visual_reasoning)
    if not evidence_cards:
        evidence_cards = [
            EvidenceCard(
                source_type="visual_session",
                title=subject,
                snippet=_previous_summary(request.previous_result) or "来自当前图片会话。",
                score=0.6,
            )
        ]
    return VisualFollowupResponse(
        session_id=request.session_id,
        answer=answer,
        evidence_cards=evidence_cards,
        followup_questions=[
            "这附近可以顺路去哪？",
            "这张图最值得看的细节是什么？",
        ],
    )


def _official_history_text(visual_reasoning: dict) -> str:
    layers = visual_reasoning.get("meaning_layers")
    if not isinstance(layers, dict):
        return ""
    return str(layers.get("cultural_history") or "").strip()


def _official_history_cards_from_reasoning(visual_reasoning: dict) -> list[EvidenceCard]:
    sources = visual_reasoning.get("official_history_sources")
    if not isinstance(sources, list):
        return []
    cards: list[EvidenceCard] = []
    fallback_snippet = _official_history_text(visual_reasoning)
    for source in sources[:3]:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        if not title:
            continue
        cards.append(
            EvidenceCard(
                source_type="official_history",
                title=title,
                snippet=str(source.get("snippet") or fallback_snippet or "官方历史来源").strip(),
                url=str(source.get("url") or "").strip() or None,
                score=0.86,
            )
        )
    return cards
