from __future__ import annotations

import hashlib
from typing import Any

from app.schemas.visual import (
    DeepVisualCard,
    DeepVisualSection,
    PerspectiveCard,
    VisualExploreInput,
    VisualExploreResponse,
    VisualMemoryItem,
    VisualWorkflowSummary,
)


_PERSPECTIVE_LABELS = {
    "guide": "导游视角",
    "history": "历史视角",
    "culture": "文化视角",
    "art_critic": "艺术评论视角",
    "style": "风格视角",
    "map_linker": "地图联动视角",
}

_BANNED_PUBLIC_TERMS = (
    "候选",
    "置信度",
    "不确定",
    "高价值候选",
    "绝对定论",
    "fallback",
    "模型",
    "可能",
)

_IDENTITY_SECTION_TITLES = ["主体身份", "地点/类型", "核心特征"]
_WORTH_SECTION_TITLES = ["导游视角", "历史视角", "文化视角", "风格视角"]
_LOOK_SECTION_TITLES = ["画面线索", "判断依据", "继续探索"]

_MEANING_BUCKET_KEYWORDS = {
    "guide": (
        "practical",
        "guide",
        "visitor",
        "route",
        "experience",
        "photography",
        "tour",
        "实用",
        "导游",
        "游览",
        "动线",
        "体验",
        "路线",
        "拍摄",
    ),
    "history": (
        "cultural_history",
        "history",
        "historical",
        "heritage",
        "origin",
        "temple",
        "shrine",
        "历史",
        "沿革",
        "传承",
        "遗产",
        "寺院",
        "神社",
    ),
    "culture": (
        "culture",
        "cultural",
        "emotional",
        "social",
        "symbolic",
        "local",
        "community",
        "ritual",
        "文化",
        "情感",
        "地方",
        "社区",
        "象征",
        "仪式",
    ),
    "style": (
        "visual",
        "style",
        "aesthetic",
        "material",
        "materials",
        "craft",
        "architecture",
        "design",
        "form",
        "视觉",
        "风格",
        "美学",
        "材料",
        "材质",
        "工艺",
        "建筑",
        "设计",
        "形制",
    ),
}


def enrich_visual_response(
    response: VisualExploreResponse,
    request: VisualExploreInput,
    *,
    visual_reasoning: dict[str, Any] | None = None,
    model_used: str = "vision",
    knowledge_used: bool | None = None,
) -> VisualExploreResponse:
    """Add visual-first workflow fields without breaking the legacy contract."""

    visual_reasoning = visual_reasoning or {}
    selected = _selected_perspectives(visual_reasoning)
    confidence = _confidence(response, visual_reasoning)
    uncertainty = _uncertainty(response, visual_reasoning)
    provider = str(
        visual_reasoning.get("provider")
        or ("heuristic" if visual_reasoning.get("provider_error") else _provider_from_model(model_used))
    )
    memory = _memory_item(response, request, visual_reasoning)
    perspective_cards = [
        _perspective_card(name, response, visual_reasoning, confidence)
        for name in selected
    ]
    one_line_answer = response.one_line_answer or _one_line_answer(
        response, visual_reasoning
    )
    deep_cards = _normalize_deep_cards(
        response.deep_cards or _deep_cards(response, visual_reasoning),
        response,
        visual_reasoning,
    )
    summary = VisualWorkflowSummary(
        provider=provider,
        model=str(visual_reasoning.get("model") or model_used),
        selected_perspectives=selected,
        knowledge_used=(
            bool(response.knowledge_cards or response.evidence_cards)
            if knowledge_used is None
            else knowledge_used
        ),
        confidence=confidence,
        uncertainty=uncertainty,
    )
    return response.model_copy(
        update={
            "one_line_answer": _public_text(one_line_answer)
            or _public_text(
                _one_line_answer(
                    response.model_copy(update={"narrative": ""}),
                    visual_reasoning,
                )
            ),
            "deep_cards": deep_cards,
            "perspective_cards": response.perspective_cards or perspective_cards,
            "visual_memory_item": response.visual_memory_item or memory,
            "audio_script": response.audio_script or _audio_script(response, uncertainty),
            "visual_workflow_summary": summary,
        }
    )


def _selected_perspectives(visual_reasoning: dict[str, Any]) -> list[str]:
    raw = visual_reasoning.get("suggested_perspectives")
    if isinstance(raw, str):
        raw = [raw]
    selected = [
        str(item).strip()
        for item in raw or []
        if str(item).strip() in _PERSPECTIVE_LABELS
    ]
    if selected:
        return selected[:4]

    subject = str(visual_reasoning.get("subject") or "").lower()
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    entity_types = " ".join(
        str(item.get("entity_type", "")).lower()
        for item in hypotheses
        if isinstance(item, dict)
    ) if isinstance(hypotheses, list) else ""
    if any(token in f"{subject} {entity_types}" for token in ("landmark", "shrine", "temple", "castle")):
        return ["guide", "history", "culture", "style"]
    return ["guide", "culture", "style"]


def _perspective_card(
    perspective: str,
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
    confidence: float,
) -> PerspectiveCard:
    label = _PERSPECTIVE_LABELS[perspective]
    clues = _visible_clue_texts(visual_reasoning)
    subject = str(visual_reasoning.get("subject") or response.what_it_is)
    if perspective == "history":
        summary = _meaning(visual_reasoning, "cultural_history") or response.why_it_matters
    elif perspective == "culture":
        summary = _hypothesis_rationale(visual_reasoning) or response.why_it_matters
    elif perspective == "art_critic":
        summary = _meaning(visual_reasoning, "visual") or response.narrative or response.why_it_matters
    elif perspective == "style":
        summary = response.shoot_hint.how_to_shoot
    elif perspective == "map_linker":
        summary = "可以把这次发现保存为地图记忆，之后和附近地点、路线或旅行计划联动。"
    else:
        summary = response.narrative or response.why_it_matters
    reasons = clues or response.confidence_notes or ["这张照片仍需要更多角度或上下文确认。"]
    return PerspectiveCard(
        perspective=perspective,
        title=f"{label}：{subject}",
        summary=summary,
        reasons=reasons[:3],
        confidence=confidence,
        followup_prompt=_followup_for(perspective),
    )


def _one_line_answer(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> str:
    narrative = _first_sentence(response.narrative)
    if narrative:
        return narrative
    subject = str(visual_reasoning.get("subject") or response.what_it_is).strip()
    why = _first_sentence(response.why_it_matters)
    if subject and why:
        return f"{subject}：{why}"
    return subject or "这张照片还有待继续确认，但已经能看出一些值得追踪的线索。"


def _deep_cards(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[DeepVisualCard]:
    return [
        DeepVisualCard(
            title="识别",
            body=_identity_body(response, visual_reasoning),
            supporting_points=_identity_points(visual_reasoning, response),
            sections=_identity_sections(response, visual_reasoning),
            next_action=_identity_next_action(response),
        ),
        DeepVisualCard(
            title="看点",
            body=_worth_body(response, visual_reasoning),
            supporting_points=_worth_points(visual_reasoning, response),
            sections=_worth_sections(response, visual_reasoning),
            next_action="如果要继续深入，可以追问它和周边街区、历史人物、节庆或相似地点的关系。",
        ),
        DeepVisualCard(
            title="线索",
            body=_look_body(response, visual_reasoning),
            supporting_points=_look_points(visual_reasoning, response),
            sections=_look_sections(response, visual_reasoning),
            next_action=_look_next_action(response, visual_reasoning),
        ),
    ]


def _identity_body(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> str:
    subject = str(visual_reasoning.get("subject") or response.what_it_is).strip()
    rationale = _hypothesis_rationale(visual_reasoning)
    if rationale:
        return f"{subject}。{rationale}"
    return f"{subject}。这个判断来自画面里的形制、材质、环境和已识别线索。"


def _worth_body(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> str:
    cultural = _meaning(visual_reasoning, "cultural_history") or response.meaning_layers.get(
        "cultural_history", ""
    )
    visual = _meaning(visual_reasoning, "visual") or response.meaning_layers.get(
        "visual", ""
    )
    narrative = response.narrative or response.why_it_matters
    parts = [
        public
        for public in (_public_text(part) for part in (narrative, cultural, visual))
        if public
    ]
    if parts:
        return _public_text(" ".join(dict.fromkeys(parts)))
    return "它值得看的地方不只是名称，而是画面里的地方气质、历史痕迹和人的使用方式如何叠在一起。"


def _look_body(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> str:
    clues = _visible_clue_texts(visual_reasoning)
    practical = _meaning(visual_reasoning, "practical") or response.meaning_layers.get(
        "practical", ""
    )
    if clues and practical:
        return f"先看这些线索：{'；'.join(clues[:3])}。{practical}"
    if clues:
        return f"先看这些线索：{'；'.join(clues[:3])}。它们会比单纯记住名称更能帮助你理解这张照片。"
    return f"可以从构图、光线和主体与环境的关系入手。{response.shoot_hint.how_to_shoot}"


def _worth_sections(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[DeepVisualSection]:
    practical = _meaning_bucket(response, visual_reasoning, "guide")
    cultural = _meaning_bucket(response, visual_reasoning, "history")
    emotional = _meaning_bucket(response, visual_reasoning, "culture")
    visual = _meaning_bucket(response, visual_reasoning, "style")
    clues = _visible_clue_texts(visual_reasoning)
    hypothesis = _hypothesis_rationale(visual_reasoning)
    return [
        DeepVisualSection(
            title="导游视角",
            body=_balanced_section_body(
                practical,
                response.narrative,
                response.why_it_matters,
                fallback="先按现场游览来读：看它怎样和路线、停留点、周边空间发生关系。",
            ),
            bullets=_unique_nonempty(
                [
                    response.shoot_hint.stand_where,
                    response.shoot_hint.best_time,
                    response.followup_questions[0] if response.followup_questions else "",
                ]
            )[:3],
            chips=[],
        ),
        DeepVisualSection(
            title="历史视角",
            body=_balanced_section_body(
                cultural,
                hypothesis,
                response.why_it_matters,
                fallback="从历史上看，它的价值在于把具体地点、制度记忆和长期使用痕迹连接起来。",
            ),
            bullets=_unique_nonempty(response.known_comparisons[:2]),
            chips=_unique_nonempty(response.known_comparisons[:3]),
        ),
        DeepVisualSection(
            title="文化视角",
            body=_balanced_section_body(
                emotional,
                response.why_popular_or_overhyped,
                response.why_it_matters,
                fallback="文化上更值得看的是它如何承载地方气质、人的停留方式和共同记忆。",
            ),
            bullets=_unique_nonempty(
                [response.why_popular_or_overhyped, response.followup_questions[0] if response.followup_questions else ""]
            )[:2],
            chips=[],
        ),
        DeepVisualSection(
            title="风格视角",
            body=_balanced_section_body(
                visual,
                "；".join(clues[:2]),
                fallback="风格上先看轮廓、尺度、材料和空间关系，它们决定了画面第一眼的气质。",
            ),
            bullets=_unique_nonempty(_visible_clue_texts(visual_reasoning)[:2]),
            chips=[],
        ),
    ]


def _look_sections(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[DeepVisualSection]:
    clues = _visible_clue_texts(visual_reasoning)
    supports = _hypothesis_supports(visual_reasoning)
    rationale = _hypothesis_rationale(visual_reasoning)
    return [
        DeepVisualSection(
            title="画面线索",
            body=_public_text("；".join(clues[:3]) or "观察主体形状、材料、文字、构图、环境和使用痕迹之间的关系。"),
            bullets=_unique_nonempty(clues[:3]),
            chips=_unique_nonempty(clues[:3]),
        ),
        DeepVisualSection(
            title="判断依据",
            body=_public_text(rationale or "把可见形态、材料、环境和地点语境合在一起判断，而不是只看单个物体标签。"),
            bullets=_unique_nonempty(supports[:4]),
            chips=[],
        ),
        DeepVisualSection(
            title="继续探索",
            body=_public_text(_look_next_action(response, visual_reasoning)),
            bullets=[],
            chips=_unique_nonempty(response.followup_questions[:2]),
        ),
    ]


def _identity_sections(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[DeepVisualSection]:
    subject = str(visual_reasoning.get("subject") or response.what_it_is).strip()
    entity_type = _entity_type(visual_reasoning)
    region = _region_hint(visual_reasoning)
    identity_points = _identity_points(visual_reasoning, response)
    return [
        DeepVisualSection(
            title="主体身份",
            body=_public_text(subject or response.what_it_is or "这是照片中的主要视觉主体。"),
            bullets=[],
            chips=_unique_nonempty([entity_type if entity_type != "unknown" else ""]),
        ),
        DeepVisualSection(
            title="地点/类型",
            body=_public_text(
                " / ".join(
                    _unique_nonempty(
                        [region or "", entity_type if entity_type != "unknown" else ""]
                    )
                )
                or response.what_it_is
                or subject
            ),
            bullets=[],
            chips=_unique_nonempty([region or ""]),
        ),
        DeepVisualSection(
            title="核心特征",
            body=_public_text("；".join(identity_points[:3]) or "可从主体轮廓、材质、尺度和环境关系辨认。"),
            bullets=identity_points[:4],
            chips=[],
        ),
    ]


def _identity_points(
    visual_reasoning: dict[str, Any],
    response: VisualExploreResponse,
) -> list[str]:
    points = _visible_clue_texts(visual_reasoning)
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    if isinstance(hypotheses, list):
        for hypothesis in hypotheses:
            if isinstance(hypothesis, dict):
                points.extend(str(item) for item in hypothesis.get("evidence_support", [])[:2])
    if not points and response.what_it_is:
        points.append(response.what_it_is)
    return _unique_nonempty(points)[:4]


def _worth_points(
    visual_reasoning: dict[str, Any],
    response: VisualExploreResponse,
) -> list[str]:
    layers = visual_reasoning.get("meaning_layers")
    points: list[str] = []
    if isinstance(layers, dict):
        for key in ("cultural_history", "visual", "emotional"):
            value = str(layers.get(key) or "").strip()
            if value:
                points.append(value)
    points.extend(str(item) for item in visual_reasoning.get("known_comparisons", [])[:2])
    if response.why_popular_or_overhyped:
        points.append(response.why_popular_or_overhyped)
    return _unique_nonempty(points)[:4]


def _look_points(
    visual_reasoning: dict[str, Any],
    response: VisualExploreResponse,
) -> list[str]:
    points = _visible_clue_texts(visual_reasoning)
    if response.shoot_hint.best_time:
        points.append(f"适合观察/拍摄时间：{response.shoot_hint.best_time}")
    if response.shoot_hint.stand_where:
        points.append(f"站位：{response.shoot_hint.stand_where}")
    return _unique_nonempty(points)[:4]


def _identity_next_action(response: VisualExploreResponse) -> str:
    return "可以查看现场说明、地图位置或周边街景，把名称、位置和画面线索对上。"


def _look_next_action(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> str:
    practical = _meaning(visual_reasoning, "practical") or response.meaning_layers.get(
        "practical", ""
    )
    return _public_text(practical or response.shoot_hint.how_to_shoot)


def _normalize_deep_cards(
    cards: list[DeepVisualCard],
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[DeepVisualCard]:
    fallback = _deep_cards(response, visual_reasoning)
    normalized: list[DeepVisualCard] = []
    for index, title in enumerate(("识别", "看点", "线索")):
        source = cards[index] if index < len(cards) else fallback[index]
        if _has_public_thinking_trace(source):
            source = fallback[index]
        mapped_title = _public_card_title(source.title, index)
        sections = source.sections
        if mapped_title == "识别" and (
            not _has_expected_sections(sections, _IDENTITY_SECTION_TITLES)
            or _has_thin_sections(sections, min_length=8)
        ):
            sections = _identity_sections(response, visual_reasoning)
        if mapped_title == "看点" and not sections:
            sections = _worth_sections(response, visual_reasoning)
        if mapped_title == "看点" and (
            not _has_expected_sections(sections, _WORTH_SECTION_TITLES)
            or _has_thin_sections(sections, min_length=28)
            or _missing_worth_meaning(sections, response, visual_reasoning)
        ):
            sections = _worth_sections(response, visual_reasoning)
        if mapped_title == "线索" and (
            not _has_expected_sections(sections, _LOOK_SECTION_TITLES)
            or _has_thin_sections(sections, min_length=10)
        ):
            sections = _look_sections(response, visual_reasoning)
        normalized.append(
            DeepVisualCard(
                title=title,
                body=_public_or_fallback(source.body, fallback[index].body),
                supporting_points=[
                    _public_text(point)
                    for point in (source.supporting_points or fallback[index].supporting_points)
                    if _public_text(point)
                ][:4],
                next_action=_public_or_fallback(source.next_action, fallback[index].next_action),
                sections=[
                    DeepVisualSection(
                        title=_public_text(section.title),
                        body=_public_text(section.body),
                        bullets=[
                            _public_text(item)
                            for item in section.bullets
                            if _public_text(item)
                        ],
                        chips=[
                            _public_text(item)
                            for item in section.chips
                            if _public_text(item)
                        ],
                    )
                    for section in sections
                ],
            )
        )
    return normalized


def _has_expected_sections(sections: list[DeepVisualSection], expected: list[str]) -> bool:
    return [section.title for section in sections] == expected


def _has_thin_sections(sections: list[DeepVisualSection], *, min_length: int) -> bool:
    return any(len(_public_text(section.body)) < min_length for section in sections)


def _missing_worth_meaning(
    sections: list[DeepVisualSection],
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> bool:
    section_text = " ".join(_public_text(section.body) for section in sections)
    for bucket in ("guide", "history", "culture", "style"):
        meaning = _meaning_bucket(response, visual_reasoning, bucket)
        if not meaning:
            continue
        anchor = _meaning_anchor(meaning)
        if anchor and anchor not in section_text:
            return True
    return False


def _public_card_title(value: str, index: int) -> str:
    mapping = {
        "这是什么": "识别",
        "为什么值得看": "看点",
        "怎么看更懂": "线索",
        "识别": "识别",
        "看点": "看点",
        "线索": "线索",
    }
    return mapping.get(str(value).strip(), ("识别", "看点", "线索")[index])


def _has_public_thinking_trace(card: DeepVisualCard) -> bool:
    text = " ".join(
        [
            card.title,
            card.body,
            card.next_action,
            " ".join(card.supporting_points),
            " ".join(
                " ".join([section.title, section.body, " ".join(section.bullets), " ".join(section.chips)])
                for section in card.sections
            ),
        ]
    )
    return any(term.lower() in text.lower() for term in _BANNED_PUBLIC_TERMS)


def _memory_item(
    response: VisualExploreResponse,
    request: VisualExploreInput,
    visual_reasoning: dict[str, Any],
) -> VisualMemoryItem:
    subject = str(visual_reasoning.get("subject") or response.what_it_is or "visual discovery")
    entity_type = _entity_type(visual_reasoning)
    region = _region_hint(visual_reasoning)
    image_hash = request.image_sha256 or _request_image_hash(request)
    return VisualMemoryItem(
        memory_id=f"visual_{image_hash[:16]}",
        title=subject,
        entity_type=entity_type,
        region_hint=region,
        thumbnail_sha256=image_hash[:16] if image_hash else None,
        status=response.map_memory_status or "discovered",
    )


def _audio_script(response: VisualExploreResponse, uncertainty: list[str]) -> str:
    title = response.story_title or response.what_it_is or "这张照片背后的线索"
    narrative = (
        _public_text(response.one_line_answer)
        or _public_text(response.narrative)
        or _public_text(response.why_it_matters)
        or _public_text(response.what_it_is)
    )
    script = f"{title}。{narrative}".strip()
    if uncertainty:
        script = f"{script} 我还不确定的是：{uncertainty[0]}。"
    return script[:900]


def _confidence(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> float:
    try:
        return max(0.0, min(1.0, float(visual_reasoning.get("confidence", response.confidence))))
    except (TypeError, ValueError):
        return response.confidence


def _uncertainty(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> list[str]:
    notes = visual_reasoning.get("confidence_notes") or response.confidence_notes
    if isinstance(notes, str):
        return [notes]
    if isinstance(notes, list):
        return [str(item) for item in notes if str(item).strip()]
    return []


def _visible_clue_texts(visual_reasoning: dict[str, Any]) -> list[str]:
    clues = visual_reasoning.get("visible_clues")
    if not isinstance(clues, list):
        return []
    values: list[str] = []
    for clue in clues:
        if isinstance(clue, dict):
            text = str(clue.get("interpretation") or clue.get("clue") or "").strip()
            if text:
                values.append(text)
    return values


def _combined_meaning_layers(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
) -> dict[str, str]:
    combined: dict[str, str] = {}
    for source in (response.meaning_layers, visual_reasoning.get("meaning_layers")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            text = _public_text(str(value or ""))
            if text:
                combined[str(key)] = text
    return combined


def _meaning_bucket(
    response: VisualExploreResponse,
    visual_reasoning: dict[str, Any],
    bucket: str,
) -> str:
    keywords = _MEANING_BUCKET_KEYWORDS[bucket]
    values: list[str] = []
    for key, value in _combined_meaning_layers(response, visual_reasoning).items():
        normalized_key = str(key).lower()
        if any(keyword.lower() in normalized_key for keyword in keywords):
            values.append(value)
    if bucket == "style":
        for key, value in _combined_meaning_layers(response, visual_reasoning).items():
            normalized_key = str(key).lower()
            if normalized_key not in {
                "practical",
                "cultural_history",
                "emotional",
                "visual",
            } and value not in values:
                values.append(value)
    return _join_unique_sentences(values, max_sentences=3)


def _meaning(visual_reasoning: dict[str, Any], key: str) -> str:
    layers = visual_reasoning.get("meaning_layers")
    if isinstance(layers, dict):
        return str(layers.get(key) or "").strip()
    return ""


def _hypothesis_rationale(visual_reasoning: dict[str, Any]) -> str:
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict) and item.get("rationale"):
                return str(item["rationale"])
    return ""


def _hypothesis_supports(visual_reasoning: dict[str, Any]) -> list[str]:
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    supports: list[str] = []
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict):
                supports.extend(str(value) for value in item.get("evidence_support", []))
    return _unique_nonempty(supports)


def _entity_type(visual_reasoning: dict[str, Any]) -> str:
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict) and item.get("entity_type"):
                return str(item["entity_type"])
    return "unknown"


def _region_hint(visual_reasoning: dict[str, Any]) -> str | None:
    hypotheses = visual_reasoning.get("cultural_hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict) and item.get("region"):
                return str(item["region"])
    return None


def _request_image_hash(request: VisualExploreInput) -> str:
    if request.image_url:
        return hashlib.sha256(request.image_url.encode("utf-8")).hexdigest()
    images = request.images_bytes or ([request.image_bytes] if request.image_bytes else [])
    digest = hashlib.sha256()
    for image in images:
        digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()


def _provider_from_model(model_used: str) -> str:
    model = model_used.lower()
    if "gemini" in model:
        return "gemini"
    if "deepinfra" in model or "mistral" in model or "qwen" in model:
        return "deepinfra"
    return "heuristic"


def _followup_for(perspective: str) -> str | None:
    prompts = {
        "guide": "附近还有哪些相关地点？",
        "history": "它背后的历史脉络是什么？",
        "culture": "当地人会怎样理解它？",
        "art_critic": "它的美学和风格特别在哪里？",
        "style": "我应该怎么拍这张照片？",
        "map_linker": "把它加入地图记忆并规划路线。",
    }
    return prompts.get(perspective)


def _public_text(value: str) -> str:
    text = str(value or "").strip()
    if _looks_like_json_artifact(text):
        return ""
    replacements = {
        "这很可能是": "这是",
        "这可能是": "这是",
        "它可能是": "这是",
        "最可能指向": "指向",
        "可能指向": "指向",
        "可能是": "是",
        "可能": "",
        "高价值候选": "重点线索",
        "候选": "线索",
        "当前置信度约": "",
        "置信度": "判断强度",
        "不确定": "待补充",
        "绝对定论": "最终结论",
        "fallback": "备用结果",
        "Fallback": "备用结果",
        "模型": "系统",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = " ".join(text.split())
    return text.strip(" ；;，,")


def _public_or_fallback(value: str, fallback: str) -> str:
    return _public_text(value) or _public_text(fallback)


def _looks_like_json_artifact(value: str) -> bool:
    text = str(value or "")
    if not any(char in text for char in "{}[]"):
        return False
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "story_title",
            "one_line_answer",
            "deep_cards",
            "supporting_points",
            "next_action",
            "meaning_layers",
            '"title"',
            '"body"',
        )
    )


def _balanced_section_body(*values: str, fallback: str) -> str:
    text = _join_unique_sentences([*values, fallback], max_sentences=3)
    if len(text) >= 35:
        return text
    supplement = _public_text(fallback)
    if supplement and supplement not in text:
        text = _join_unique_sentences([text, supplement], max_sentences=3)
    return text or supplement


def _join_unique_sentences(values: list[str], *, max_sentences: int) -> str:
    sentences: list[str] = []
    seen: set[str] = set()
    for value in values:
        for sentence in _split_sentences(_public_text(value)):
            key = _sentence_key(sentence)
            if not key or key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)
            if len(sentences) >= max_sentences:
                return "".join(sentences)
    return "".join(sentences)


def _split_sentences(value: str) -> list[str]:
    text = _public_text(value)
    if not text:
        return []
    sentences: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in "。！？.!?":
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip(" ；;，,") + "。")
    return sentences


def _sentence_key(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())[:36].lower()


def _meaning_anchor(value: str) -> str:
    text = _public_text(value)
    if not text:
        return ""
    for separator in ("，", "、", "。", "；", ";", ","):
        if separator in text:
            return text.split(separator)[0][:10]
    return text[:10]


def _first_sentence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for separator in ("。", "！", "？", ".", "!", "?"):
        index = text.find(separator)
        if index >= 0:
            return text[: index + len(separator)].strip()
    return text[:140].strip()


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
