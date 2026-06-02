from __future__ import annotations

import hashlib

from app.schemas.visual import (
    EvidenceCard,
    RelatedPlace,
    ShootHint,
    VisualExploreInput,
    VisualExploreResponse,
    RankedPlace,
)


class EvidenceAwareComposer:
    """Deterministic answer composer that never claims unsupported detail."""

    async def compose(
        self,
        request: VisualExploreInput,
        intent: str,
        candidates,
        ranked: list[RankedPlace],
        evidence_by_place_id: dict[int | None, list[EvidenceCard]],
        visual_reasoning: dict | None = None,
        narrative_result: dict | None = None,
    ) -> VisualExploreResponse:
        visual_reasoning = visual_reasoning or {}
        narrative_result = narrative_result or {}
        if not ranked:
            return self._uncertain_response(request, visual_reasoning, narrative_result)

        top = ranked[0]
        place = top.place
        evidence = evidence_by_place_id.get(place.place_id, [])
        display_name = place.name_ja or place.name
        evidence_summary = "、".join(card.title for card in evidence[:2]) or "暂无可靠证据"
        needs_confirmation = place.confidence < 0.55 or not evidence
        story_title = str(
            narrative_result.get("story_title")
            or f"{display_name} 背后的线索"
        )
        narrative = str(
            narrative_result.get("narrative")
            or f"这张照片可能指向 {display_name}，但我会把它当作需要证据继续确认的线索。"
        )
        confidence_notes = _string_list(
            narrative_result.get("confidence_notes")
            or visual_reasoning.get("confidence_notes")
        )
        if needs_confirmation and not confidence_notes:
            confidence_notes = ["地点或文化含义仍需要更多角度、上下文或证据确认。"]

        return VisualExploreResponse(
            session_id=_session_id(request),
            what_it_is=f"{display_name}，类别：{place.category}",
            why_it_matters=(
                narrative
                if narrative
                else (
                    f"它和你的兴趣 {', '.join(request.interest_tags) or '未设置'} 的匹配点是："
                    f"{', '.join(top.reasons) or '需要更多证据'}。证据：{evidence_summary}。"
                )
            ),
            why_popular_or_overhyped=(
                "有游客过热或信息缺口，建议错峰/核查。"
                if top.penalties
                else (
                    "目前证据没有显示明显过热风险。"
                    if evidence
                    else "当前证据不足以判断热度，不把它硬说成网红点。"
                )
            ),
            related_places=[
                RelatedPlace(
                    place_id=place.place_id,
                    name=display_name,
                    relation="current_candidate",
                    reason=place.match_reason,
                    distance_meters=place.distance_meters,
                )
            ],
            shoot_hint=ShootHint(
                best_time="日落前 60-30 分钟",
                stand_where="站在入口或庭院边缘，避开正中人流",
                face_where=(
                    f"按当前指南针 {request.heading_degrees:.0f} 度微调"
                    if request.heading_degrees is not None
                    else "朝主体建筑或光线侧面"
                ),
                how_to_shoot="用低机位保留前景层次，等待人流空档再拍",
                camera_hint="24-35mm 或手机 1x",
            ),
            evidence_cards=evidence,
            confidence=place.confidence,
            needs_user_confirmation=needs_confirmation,
            candidates=[item.place for item in ranked[:3]],
            story_title=story_title,
            narrative=narrative,
            visible_clues=_list_of_dicts(visual_reasoning.get("visible_clues")),
            cultural_hypotheses=_list_of_dicts(
                visual_reasoning.get("cultural_hypotheses")
            ),
            meaning_layers=_meaning_layers(
                narrative_result.get("meaning_layers")
                or visual_reasoning.get("meaning_layers")
            ),
            known_comparisons=_string_list(visual_reasoning.get("known_comparisons")),
            confidence_notes=confidence_notes,
            followup_questions=_string_list(narrative_result.get("followup_questions")),
            one_line_answer=str(narrative_result.get("one_line_answer") or ""),
            deep_cards=_list_of_dicts(narrative_result.get("deep_cards")),
            map_memory_status="discovered",
        )

    def _uncertain_response(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict | None = None,
        narrative_result: dict | None = None,
    ) -> VisualExploreResponse:
        visual_reasoning = visual_reasoning or {}
        narrative_result = narrative_result or {}
        story_title = str(
            narrative_result.get("story_title")
            or visual_reasoning.get("subject")
            or "还不能确定的线索"
        )
        narrative = str(
            narrative_result.get("narrative")
            or "我能看到一些线索，但还没有足够证据把它落到具体地点、物件或文化传统上。"
        )
        return VisualExploreResponse(
            session_id=_session_id(request),
            what_it_is="我还不能可靠识别这个地点",
            why_it_matters=narrative,
            why_popular_or_overhyped="没有证据时不判断热度或是否值得去。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="光线稳定时",
                stand_where="靠近说明牌或主体正面",
                face_where="朝向清晰文字或建筑主体",
                how_to_shoot="补拍一张包含招牌/说明牌/GPS 的照片",
            ),
            evidence_cards=[],
            confidence=0.0,
            needs_user_confirmation=True,
            story_title=story_title,
            narrative=narrative,
            visible_clues=_list_of_dicts(visual_reasoning.get("visible_clues")),
            cultural_hypotheses=_list_of_dicts(
                visual_reasoning.get("cultural_hypotheses")
            ),
            meaning_layers=_meaning_layers(
                narrative_result.get("meaning_layers")
                or visual_reasoning.get("meaning_layers")
            ),
            known_comparisons=_string_list(visual_reasoning.get("known_comparisons")),
            confidence_notes=_string_list(
                narrative_result.get("confidence_notes")
                or visual_reasoning.get("confidence_notes")
                or ["缺少可靠证据，不能把猜测当作结论。"]
            ),
            followup_questions=_string_list(narrative_result.get("followup_questions")),
            one_line_answer=str(narrative_result.get("one_line_answer") or ""),
            deep_cards=_list_of_dicts(narrative_result.get("deep_cards")),
        )


def _session_id(request: VisualExploreInput) -> str:
    if request.image_url:
        seed = hashlib.sha256(request.image_url.encode("utf-8")).hexdigest()
    else:
        seed = request.image_sha256 or hashlib.sha256(request.image_bytes).hexdigest()
    return f"snap_{seed[:12]}"


def _list_of_dicts(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _meaning_layers(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
