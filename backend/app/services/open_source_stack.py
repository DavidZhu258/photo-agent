from __future__ import annotations

import hashlib

from app.schemas.oss import (
    OpenSourceApiSource,
    OpenSourceCacheInfo,
    OpenSourceTraceStep,
    VisualMatch,
)
from app.schemas.visual import EvidenceCard, VisualExploreInput, VisualExploreResponse
from app.services.oss_runtime import provider_runtime_refs


TRAVEL_COMMERCIAL_DISCLOSURE = (
    "Serper.dev 是默认 Google Search/Places/Images 数据入口，只作为候选、地图和评论摘要来源；"
    "DeepInfra 是默认模型推理入口。"
    "不会把它们伪装成无广告证据。Reddit、Wikivoyage、OpenTripMap/OSM、Exa 页面检索会单独标注。"
)

VISUAL_COMMERCIAL_DISCLOSURE = (
    "Serper.dev/Google 数据只用于 exact/visual match 候选；"
    "DeepInfra 负责视觉推理和叙事，结论仍需要外部知识或用户确认。"
)


def travel_sources() -> list[OpenSourceApiSource]:
    return [
        OpenSourceApiSource(
            provider="serper",
            name="Serper.dev Google Search/Places/Images",
            source_type="commercial_api",
            format="Serper JSON",
            commercial=True,
            ad_risk=0.35,
            url="https://google.serper.dev/",
        ),
        OpenSourceApiSource(
            provider="exa",
            name="Exa Search API",
            source_type="web_retrieval",
            format="exa-py search/get_contents",
            url="https://github.com/exa-labs/exa-py",
        ),
        OpenSourceApiSource(
            provider="wikivoyage",
            name="Wikivoyage",
            source_type="open_data",
            format="Wikimedia Enterprise JSON",
            url="https://enterprise.wikimedia.com/project-data/wikivoyage-api/",
        ),
        OpenSourceApiSource(
            provider="opentripmap",
            name="OpenTripMap",
            source_type="open_data",
            format="OpenTripMap JSON/GeoJSON",
            url="https://dev.opentripmap.org/",
        ),
        OpenSourceApiSource(
            provider="deepinfra",
            name="DeepInfra",
            source_type="llm_gateway",
            format="OpenAI-compatible chat/completions",
            url="https://deepinfra.com/",
        ),
        OpenSourceApiSource(
            provider="redis",
            name="Redis",
            source_type="cache",
            format="Redis key/value TTL",
            url="https://github.com/redis/redis",
        ),
        OpenSourceApiSource(
            provider="langfuse",
            name="Langfuse",
            source_type="trace",
            format="Langfuse trace/session/observation",
            url="https://github.com/langfuse/langfuse",
        ),
    ]


def visual_sources() -> list[OpenSourceApiSource]:
    return [
        OpenSourceApiSource(
            provider="serpapi_google_lens",
            name="SerpAPI Google Lens",
            source_type="commercial_api",
            format="Google Lens JSON",
            commercial=True,
            ad_risk=0.35,
            url="https://serpapi.com/google-lens-api",
        ),
        OpenSourceApiSource(
            provider="deepinfra_litellm",
            name="DeepInfra vision via LiteLLM",
            source_type="llm_gateway",
            format="OpenAI-compatible image_url content",
            url="https://github.com/BerriAI/litellm",
        ),
        OpenSourceApiSource(
            provider="exa",
            name="Exa Search API",
            source_type="web_retrieval",
            format="exa-py search/get_contents",
            url="https://github.com/exa-labs/exa-py",
        ),
        OpenSourceApiSource(
            provider="wikivoyage",
            name="Wikivoyage",
            source_type="open_data",
            format="Wikimedia Enterprise JSON",
            url="https://enterprise.wikimedia.com/project-data/wikivoyage-api/",
        ),
        OpenSourceApiSource(
            provider="opentripmap",
            name="OpenTripMap",
            source_type="open_data",
            format="OpenTripMap JSON/GeoJSON",
            url="https://dev.opentripmap.org/",
        ),
        OpenSourceApiSource(
            provider="redis",
            name="Redis",
            source_type="cache",
            format="Redis key/value TTL",
            url="https://github.com/redis/redis",
        ),
        OpenSourceApiSource(
            provider="langfuse",
            name="Langfuse",
            source_type="trace",
            format="Langfuse trace/session/observation",
            url="https://github.com/langfuse/langfuse",
        ),
    ]


def source_breakdown(sources: list[OpenSourceApiSource]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.source_type] = counts.get(source.source_type, 0) + 1
    return counts


def cache_info(namespace: str, key_seed: str, *, hit: bool = False) -> OpenSourceCacheInfo:
    digest = hashlib.sha256(key_seed.encode("utf-8")).hexdigest()[:16]
    return OpenSourceCacheInfo(
        provider="redis",
        key=f"{namespace}:{digest}",
        hit=hit,
        ttl_seconds=900,
        metadata={"format": "Redis TTL cache key", "fallback": "in-process if Redis is unavailable"},
    )


def travel_trace_steps(
    *,
    llm_used: bool,
    model_used: str,
    suggestion_source: str,
    search_used: bool,
    cache_hit: bool = False,
) -> list[OpenSourceTraceStep]:
    return [
        OpenSourceTraceStep(
            step_id="travel.pipeline",
            framework="haystack",
            title="Haystack Pipeline",
            summary="POI 候选、路线、搜索、知识补全按 Haystack Pipeline/ComponentTool 的图式组织。",
            metadata={
                "pipeline": "travel_decision",
                "suggestion_source": suggestion_source,
                "search_used": search_used,
            },
        ),
        OpenSourceTraceStep(
            step_id="travel.agent",
            framework="pydantic_ai",
            title="PydanticAI Agent",
            summary="请求解析和最终决策卡按 PydanticAI typed Agent/structured output 约束。",
            metadata={"output_type": "TravelPlanResponse"},
        ),
        OpenSourceTraceStep(
            step_id="travel.gateway",
            framework="litellm",
            title="LiteLLM Gateway",
            summary="模型调用使用 OpenAI-compatible/LiteLLM 网关格式，便于后续接 DeepInfra、Gemini、Pixtral。",
            status="completed" if llm_used else "skipped",
            metadata={"model": model_used, "llm_used": llm_used},
        ),
        OpenSourceTraceStep(
            step_id="travel.cache",
            framework="redis",
            title="Redis Cache",
            summary="API、模型和 session 状态按 Redis TTL cache key 表达，避免自造缓存协议。",
            metadata={"hit": cache_hit},
        ),
        OpenSourceTraceStep(
            step_id="travel.trace",
            framework="langfuse",
            title="Langfuse Trace",
            summary="prompt 版本、tool call、检索步骤、成本和延迟按 Langfuse trace/observation 记录。",
            metadata={"trace_name": "travel.plan", "session_kind": "travel"},
        ),
    ]


def visual_trace_steps(
    *,
    model_used: str,
    cache_hit: bool = False,
) -> list[OpenSourceTraceStep]:
    return [
        OpenSourceTraceStep(
            step_id="visual.pipeline",
            framework="haystack",
            title="Haystack Pipeline",
            summary="Google Lens 候选、VLM 解释、Exa/Wikivoyage 知识和故事生成按 Pipeline 节点展示。",
            metadata={"pipeline": "visual_explore"},
        ),
        OpenSourceTraceStep(
            step_id="visual.agent",
            framework="pydantic_ai",
            title="PydanticAI Agent",
            summary="视觉解释输出按 typed schema 校验，再映射到故事卡和证据卡。",
            metadata={"output_type": "VisualExploreResponse"},
        ),
        OpenSourceTraceStep(
            step_id="visual.gateway",
            framework="litellm",
            title="LiteLLM Gateway",
            summary="视觉与叙事模型使用 OpenAI-compatible/LiteLLM 网关格式调用。",
            metadata={"model": model_used},
        ),
        OpenSourceTraceStep(
            step_id="visual.cache",
            framework="redis",
            title="Redis Cache",
            summary="图片 URL/hash、上下文和焦点组成 Redis TTL cache key。",
            metadata={"hit": cache_hit},
        ),
        OpenSourceTraceStep(
            step_id="visual.trace",
            framework="langfuse",
            title="Langfuse Trace",
            summary="可见线索、工具调用和不确定性按 Langfuse trace 展示，不暴露隐藏推理链。",
            metadata={"trace_name": "visual.explore", "session_kind": "visual"},
        ),
    ]


def provider_refs(scope: str) -> dict[str, object]:
    return provider_runtime_refs(scope)


def visual_matches_from_request(
    request: VisualExploreInput,
    visual_reasoning: dict,
) -> list[VisualMatch]:
    if request.image_url:
        title = str(visual_reasoning.get("subject") or "Google Lens visual match candidate")
        return [
            VisualMatch(
                provider="serpapi_google_lens",
                title=title,
                source="Google Lens",
                url=request.image_url,
                match_type="visual_match",
                confidence=float(visual_reasoning.get("confidence") or 0.5),
                metadata={"input": "image_url", "format": "SerpAPI Google Lens JSON"},
            )
        ]
    return [
        VisualMatch(
            provider="serpapi_google_lens",
            title="Google Lens candidate unavailable for private upload",
            source="Google Lens",
            match_type="requires_public_image_url",
            confidence=0.0,
            metadata={"input": "base64", "reason": "SerpAPI Lens needs a public image URL"},
        )
    ]


def knowledge_cards_from_evidence(evidence_cards: list[EvidenceCard]) -> list[EvidenceCard]:
    if evidence_cards:
        return evidence_cards
    return [
        EvidenceCard(
            source_type="exa",
            title="External knowledge pending",
            snippet="当前没有独立知识卡；正式运行时由 Exa/Wikivoyage/OpenTripMap 补充背景。",
            score=0.0,
            ad_risk=0.0,
            metadata={"format": "Haystack retriever document"},
        )
    ]


def attach_visual_metadata(
    response: VisualExploreResponse,
    request: VisualExploreInput,
    *,
    visual_reasoning: dict | None = None,
    evidence_cards: list[EvidenceCard] | None = None,
    cache_key: str = "visual",
    cache_hit: bool = False,
    model_used: str = "vision",
) -> VisualExploreResponse:
    sources = visual_sources()
    visual_reasoning = visual_reasoning or {}
    evidence_cards = evidence_cards if evidence_cards is not None else response.evidence_cards
    cache = cache_info("visual", cache_key, hit=cache_hit)
    return response.model_copy(
        update={
            "visual_matches": response.visual_matches
            or visual_matches_from_request(request, visual_reasoning),
            "api_sources_used": response.api_sources_used or sources,
            "source_breakdown": response.source_breakdown or source_breakdown(sources),
            "knowledge_cards": response.knowledge_cards
            or knowledge_cards_from_evidence(evidence_cards),
            "thinking_steps": response.thinking_steps
            or visual_trace_steps(model_used=model_used, cache_hit=cache.hit),
            "cache": response.cache if response.cache.key else cache,
        }
    )
