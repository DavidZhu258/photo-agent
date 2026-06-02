from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from app.schemas.visual import (
    EvidenceCard,
    VisualExploreInput,
    VisualFollowupInput,
    VisualFollowupResponse,
)


class HeuristicVlmClient:
    """Local-safe VLM placeholder.

    This keeps P0 endpoints usable even before a remote model is configured.
    """

    async def identify(self, request: VisualExploreInput) -> dict[str, Any]:
        text = request.client_ocr.text.strip()
        candidates = []
        for token in ("青蓮院", "清水寺", "別府", "宮島", "太宰府"):
            if token in text:
                candidates.append(token)
        subject = "unknown visual subject"
        if candidates:
            subject = candidates[0]
        elif re.search(r"寺|神社|院|城|跡", text):
            subject = "historic site sign"
        visible_clues = [
            {
                "clue": "limited local heuristic context",
                "interpretation": "Only OCR/GPS hints are available; visual meaning needs a model call.",
                "confidence": 0.25,
            }
        ]
        return {
            "subject": subject,
            "place_candidates": candidates,
            "confidence": 0.45 if not candidates else 0.72,
            "visible_clues": visible_clues,
            "cultural_hypotheses": [
                {
                    "name": subject,
                    "entity_type": "unknown",
                    "region": None,
                    "rationale": "Fallback heuristic result with weak evidence.",
                    "confidence": 0.35,
                    "evidence_support": [text[:80]] if text else [],
                    "evidence_against": ["No remote vision model was available."],
                }
            ],
            "meaning_layers": {
                "visual": "视觉线索不足，需要更多图片或远程模型。",
                "cultural_history": "暂无可靠文化历史判断。",
                "emotional": "当前只能给出谨慎的候选解释。",
                "practical": "补充地点、角度或上下文会显著提升判断。",
            },
            "known_comparisons": [],
            "confidence_notes": ["Heuristic fallback; do not treat as confirmed."],
        }


class HeuristicNarrativeClient:
    async def compose(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict[str, Any],
        evidence_cards: list[Any],
    ) -> dict[str, Any]:
        subject = visual_reasoning.get("subject") or "这张照片"
        clue = _first_visible_clue(visual_reasoning)
        return {
            "story_title": f"{subject} 背后的线索",
            "narrative": (
                f"这张照片最值得看的不是一个确定标签，而是它留下的线索：{clue}。"
                "目前证据还不够完整，所以我会把它当作一个需要继续确认的故事开端。"
            ),
            "one_line_answer": (
                f"这张照片展示的是 {subject}，重点在于画面留下的视觉线索和地方气质。"
            ),
            "deep_cards": [
                {
                    "title": "识别",
                    "body": f"这是 {subject}。画面中的主体、周边环境和可见痕迹共同构成第一层识别依据。",
                    "supporting_points": [clue],
                    "next_action": "可以继续观察主体周边的文字、门脸、街景和使用痕迹。",
                    "sections": [],
                },
                {
                    "title": "看点",
                    "body": "它值得继续看的原因在于画面留下了可追踪的地方、材质或使用痕迹，而不只是一个标签。",
                    "supporting_points": ["地方气质", "材料与使用痕迹"],
                    "next_action": "结合城市或街区信息，可以把它放进更具体的文化和历史背景里。",
                    "sections": [
                        {"title": "历史/文化", "body": "画面保留了地方生活、建筑或器物传统的入口。", "bullets": [], "chips": []},
                        {"title": "美学/风格", "body": "主体的轮廓、材质和环境关系形成第一层视觉吸引力。", "bullets": [], "chips": []},
                        {"title": "体验/地方意义", "body": "它适合被当作一次现场观察，而不是只记住名称。", "bullets": [], "chips": []},
                    ],
                },
                {
                    "title": "线索",
                    "body": "先看主体和环境的关系，再看有没有文字、纹样、材料、年代感或使用痕迹。",
                    "supporting_points": ["Only OCR/GPS hints are available; visual meaning needs a model call."],
                    "next_action": "换一个更正面或更包含周边环境的角度再拍。",
                    "sections": [
                        {"title": "画面细节", "body": "主体、环境、文字、材料和使用痕迹是理解画面的入口。", "bullets": [], "chips": []},
                        {"title": "下一步探索", "body": "换一个角度或补充地点信息，可以连接到附近相似地点和拍摄建议。", "bullets": [], "chips": []},
                    ],
                },
            ],
            "meaning_layers": visual_reasoning.get("meaning_layers") or {},
            "confidence_notes": visual_reasoning.get("confidence_notes")
            or ["叙事由本地 fallback 生成，可靠性低于远程模型。"],
            "followup_questions": [
                request.user_context_text
                and "能否再补一张包含周边环境或说明牌的照片？"
                or "这张照片拍摄于哪个城市或地区？"
            ],
        }

    async def answer_followup(
        self,
        request: VisualFollowupInput,
        visual_reasoning: dict[str, Any],
    ) -> VisualFollowupResponse:
        subject = str(
            visual_reasoning.get("subject")
            or request.previous_result.get("what_it_is")
            or request.previous_result.get("story_title")
            or "这张照片"
        ).strip()
        answer = (
            f"关于“{request.question.strip()}”，我会先沿着 {subject} 这条线索看："
            "把画面主体、上一轮识别和你补充的兴趣放在一起，再判断它适合怎么参观、怎么拍或怎么顺路安排。"
        )
        return VisualFollowupResponse(
            session_id=request.session_id,
            answer=answer,
            evidence_cards=[
                EvidenceCard(
                    source_type="visual_session",
                    title=subject,
                    snippet=str(request.previous_result.get("one_line_answer") or request.previous_result.get("narrative") or "当前图片会话"),
                    score=0.5,
                )
            ],
            followup_questions=["这附近可以顺路去哪？", "这张图有哪些容易忽略的细节？"],
        )


class DeepInfraVlmClient:
    """DeepInfra OpenAI-compatible vision client for meaning-first models."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepinfra.com/v1/openai",
        timeout_seconds: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._fallback = HeuristicVlmClient()

    async def identify(self, request: VisualExploreInput) -> dict[str, Any]:
        if not request.image_bytes and not request.image_url:
            return await self._fallback.identify(request)

        payload = self._build_payload(request)
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
            response.raise_for_status()
            body = response.json()
            return self._parse_response(body)
        except Exception as exc:
            fallback = await self._fallback.identify(request)
            fallback["provider_error"] = exc.__class__.__name__
            return fallback

    def _build_payload(self, request: VisualExploreInput) -> dict[str, Any]:
        image_parts = []
        if request.image_url:
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": request.image_url},
                }
            )
        for image_bytes in _image_bytes_for_request(request):
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            mime_type = _detect_image_mime(image_bytes)
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                }
            )
        context = {
            "gps_lat": request.gps_lat,
            "gps_lng": request.gps_lng,
            "heading_degrees": request.heading_degrees,
            "client_ocr": request.client_ocr.text,
            "client_translation": request.client_ocr.translated_text,
            "interest_tags": request.interest_tags,
            "user_context_text": request.user_context_text,
            "exploration_focus": request.exploration_focus,
        }
        instruction = (
            "Return strict JSON only with keys: subject (string), "
            "place_candidates (array of short names), confidence (0..1), "
            "visible_clues (array of objects with clue, interpretation, confidence), "
            "cultural_hypotheses (array of objects with name, entity_type, region, "
            "rationale, confidence, evidence_support, evidence_against), "
            "meaning_layers (object with visual, cultural_history, emotional, practical), "
            "known_comparisons (array), confidence_notes (array), text_seen (string). "
            "Use visible evidence only. Do not reveal hidden chain-of-thought. "
            "If the image shows a famous landmark or iconic building, identify the "
            "canonical landmark name in subject and place_candidates even when the "
            "user provided no text. "
            "If uncertain, provide 2-3 hypotheses with support and counter-evidence. "
            "All natural-language JSON values must be Simplified Chinese by default "
            "unless the user explicitly asks for another language. "
            f"Context JSON: {json.dumps(context, ensure_ascii=False)}"
        )
        return {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 2400,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a meaning-first visual reasoning analyst for a "
                        "travel/photo exploration app. You analyze architecture, "
                        "vegetation, terrain, materials, craft, age, and local culture. "
                        "You do not merely identify objects, and you do not optimize for OCR. "
                        "Default to Simplified Chinese for all natural-language JSON values "
                        "unless the user explicitly asks for another language."
                    ),
                },
                {
                    "role": "user",
                    "content": [*image_parts, {"type": "text", "text": instruction}],
                },
            ],
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _parse_response(self, body: dict[str, Any]) -> dict[str, Any]:
        content, _images = _chat_message_text_and_images(body)
        parsed = _loads_jsonish(content)
        candidates = parsed.get("place_candidates") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        return {
            "subject": str(parsed.get("subject") or "unknown visual subject"),
            "place_candidates": [str(item) for item in candidates],
            "confidence": _clamp_confidence(parsed.get("confidence")),
            "visible_clues": _ensure_list(parsed.get("visible_clues")),
            "cultural_hypotheses": _normalize_hypotheses(
                parsed.get("cultural_hypotheses")
            ),
            "meaning_layers": _ensure_dict(parsed.get("meaning_layers")),
            "known_comparisons": _ensure_string_list(parsed.get("known_comparisons")),
            "confidence_notes": _ensure_string_list(parsed.get("confidence_notes")),
            "text_seen": str(parsed.get("text_seen") or ""),
            "provider": "deepinfra",
            "model": body.get("model", self.model),
            "usage": body.get("usage", {}),
        }


class GeminiVlmClient:
    """Google Gemini visual reasoning client using generateContent-style REST."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.1-pro-preview",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        thinking_level: str = "HIGH",
        media_resolution: str = "HIGH",
        timeout_seconds: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._fallback = HeuristicVlmClient()

    async def identify(self, request: VisualExploreInput) -> dict[str, Any]:
        if not request.image_bytes and not request.image_url:
            return await self._fallback.identify(request)

        payload = self._build_payload(request)
        try:
            url = self._url()
            if self._http_client is not None:
                response = await self._http_client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        url,
                        headers=self._headers(),
                        json=payload,
                    )
            response.raise_for_status()
            body = response.json()
            return self._parse_response(body)
        except Exception as exc:
            fallback = await self._fallback.identify(request)
            fallback["provider_error"] = exc.__class__.__name__
            return fallback

    def _url(self) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        if self.api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}key={self.api_key}"
        return url

    def _build_payload(self, request: VisualExploreInput) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for image_bytes in _image_bytes_for_request(request):
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            parts.append(
                {
                    "inlineData": {
                        "mimeType": _detect_image_mime(image_bytes),
                        "data": image_b64,
                    }
                }
            )
        if request.image_url:
            parts.append({"fileData": {"fileUri": request.image_url}})
        parts.append({"text": self._instruction(request)})
        return {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1800,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": self.thinking_level},
                "mediaResolution": self.media_resolution,
            },
        }

    def _instruction(self, request: VisualExploreInput) -> str:
        context = {
            "gps_lat": request.gps_lat,
            "gps_lng": request.gps_lng,
            "heading_degrees": request.heading_degrees,
            "client_ocr": request.client_ocr.text,
            "client_translation": request.client_ocr.translated_text,
            "interest_tags": request.interest_tags,
            "user_context_text": request.user_context_text,
            "exploration_focus": request.exploration_focus,
        }
        return (
            "You are a visual-first reasoning engine for a Chance AI style "
            "travel/photo exploration app. Analyze visible architecture, materials, "
            "vegetation, terrain, craft, era, local culture, and emotional meaning. "
            "Return strict JSON only with keys: subject, place_candidates, confidence, "
            "visible_clues, cultural_hypotheses, meaning_layers, known_comparisons, "
            "confidence_notes, text_seen, suggested_perspectives. If this is a famous "
            "landmark or iconic building, include the canonical landmark name. If "
            "uncertain, give 2-3 hypotheses with support and counter-evidence. Do not "
            "reveal hidden chain-of-thought. "
            f"Context JSON: {json.dumps(context, ensure_ascii=False)}"
        )

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _parse_response(self, body: dict[str, Any]) -> dict[str, Any]:
        content = ""
        candidates = body.get("candidates") or []
        if candidates:
            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    content = str(part["text"])
                    break
        parsed = _loads_jsonish(content)
        place_candidates = parsed.get("place_candidates") or []
        if isinstance(place_candidates, str):
            place_candidates = [place_candidates]
        return {
            "subject": str(parsed.get("subject") or "unknown visual subject"),
            "place_candidates": [str(item) for item in place_candidates],
            "confidence": _clamp_confidence(parsed.get("confidence")),
            "visible_clues": _ensure_list(parsed.get("visible_clues")),
            "cultural_hypotheses": _normalize_hypotheses(
                parsed.get("cultural_hypotheses")
            ),
            "meaning_layers": _ensure_dict(parsed.get("meaning_layers")),
            "known_comparisons": _ensure_string_list(parsed.get("known_comparisons")),
            "confidence_notes": _ensure_string_list(parsed.get("confidence_notes")),
            "suggested_perspectives": _ensure_string_list(
                parsed.get("suggested_perspectives")
            ),
            "text_seen": str(parsed.get("text_seen") or ""),
            "provider": "gemini",
            "model": body.get("modelVersion", self.model),
            "usage": body.get("usageMetadata", {}),
        }


class DeepInfraNarrativeClient:
    """Story-first composer using an OpenAI-compatible DeepInfra text model."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepinfra.com/v1/openai",
        timeout_seconds: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._fallback = HeuristicNarrativeClient()

    async def compose(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict[str, Any],
        evidence_cards: list[Any],
    ) -> dict[str, Any]:
        payload = self._build_payload(request, visual_reasoning, evidence_cards)
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
            response.raise_for_status()
            body = response.json()
            parsed = self._parse_response(body)
            return _ensure_narrative_depth(parsed, visual_reasoning)
        except Exception as exc:
            fallback = await self._fallback.compose(
                request, visual_reasoning, evidence_cards
            )
            fallback["provider_error"] = exc.__class__.__name__
            return fallback

    async def answer_followup(
        self,
        request: VisualFollowupInput,
        visual_reasoning: dict[str, Any],
    ) -> VisualFollowupResponse:
        payload = self._build_followup_payload(request, visual_reasoning)
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
            response.raise_for_status()
            body = response.json()
            return self._parse_followup_response(body, request)
        except Exception:
            return await HeuristicNarrativeClient().answer_followup(request, visual_reasoning)

    def _build_followup_payload(
        self,
        request: VisualFollowupInput,
        visual_reasoning: dict[str, Any],
    ) -> dict[str, Any]:
        context = {
            "session_id": request.session_id,
            "question": request.question,
            "user_context_text": request.user_context_text,
            "exploration_focus": request.exploration_focus,
            "interest_tags": request.interest_tags,
            "previous_result": _compact_previous_visual_result(request.previous_result),
            "visual_reasoning": visual_reasoning,
        }
        content: list[dict[str, Any]] = [
            *_followup_image_parts(request),
            {
                "type": "text",
                "text": (
                    "Return strict JSON only with keys: answer, evidence_cards, followup_questions. "
                    "Answer the user's follow-up about the same image. Use the image, previous_result, "
                    "focus, interests, and visual_reasoning. Be concise, warm, and practical. "
                    "Do not invent exact opening hours, prices, routes, or coordinates. "
                    "All public natural-language JSON values must be Simplified Chinese unless the user asks otherwise. "
                    f"Context JSON: {json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ]
        return {
            "model": self.model,
            "temperature": 0.35,
            "max_tokens": 1800,
            "messages": [
                {
                    "role": "system",
                    "content": "You answer follow-up questions about one already uploaded travel/photo image.",
                },
                {"role": "user", "content": content},
            ],
        }

    def _parse_followup_response(
        self,
        body: dict[str, Any],
        request: VisualFollowupInput,
    ) -> VisualFollowupResponse:
        content, _images = _chat_message_text_and_images(body)
        parsed = _loads_jsonish(content)
        cards = []
        for item in _ensure_list(parsed.get("evidence_cards"))[:4]:
            if not isinstance(item, dict):
                continue
            cards.append(
                EvidenceCard(
                    source_type=str(item.get("source_type") or "visual_session"),
                    title=str(item.get("title") or "当前图片"),
                    snippet=str(item.get("snippet") or ""),
                    score=_clamp_confidence(item.get("score")),
                )
            )
        return VisualFollowupResponse(
            session_id=request.session_id,
            answer=str(parsed.get("answer") or "").strip() or "我会把这个问题继续放回当前图片和上一轮识别里看，但这次模型没有返回可用回答。",
            evidence_cards=cards,
            followup_questions=_ensure_string_list(parsed.get("followup_questions"))[:4],
        )

    def _build_payload(
        self,
        request: VisualExploreInput,
        visual_reasoning: dict[str, Any],
        evidence_cards: list[Any],
    ) -> dict[str, Any]:
        evidence_json = [
            card.model_dump() if hasattr(card, "model_dump") else card
            for card in evidence_cards[:8]
        ]
        context = {
            "user_context_text": request.user_context_text,
            "exploration_focus": request.exploration_focus,
            "interest_tags": request.interest_tags,
            "visual_reasoning": visual_reasoning,
            "evidence_cards": evidence_json,
        }
        return {
            "model": self.model,
            "temperature": 0.65,
            "max_tokens": 6000,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the warm narrative voice of a Chance AI style "
                        "travel/photo explorer. Write in Chinese with curator-level "
                        "depth. Be intimate and story-first, but never pretend "
                        "uncertainty is certainty. Use visible clues and "
                        "evidence/counter-evidence, not hidden chain-of-thought. "
                        "Prefer specific cultural, historical, aesthetic, practical "
                        "meaning over generic encyclopedia prose. Default to Simplified "
                        "Chinese for every public natural-language JSON value unless the "
                        "user explicitly asks for another language."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Return strict JSON only with keys: story_title, narrative, "
                        "one_line_answer, deep_cards, meaning_layers, confidence_notes, "
                        "followup_questions. one_line_answer must be one polished "
                        "sentence. deep_cards must contain exactly three objects with "
                        "titles: 识别, 看点, 线索. Each card must have body, "
                        "supporting_points, next_action, and optional sections. Public "
                        "fields must be product copy, not reasoning logs: do not mention "
                        "candidate, confidence, uncertainty, model, fallback, missing "
                        "signage/map/text, or chain-of-thought. 看点 should include "
                        "sections for 历史/文化, 美学/风格, 体验/地方意义. 线索 should "
                        "analyze visible details and may add next exploration, nearby "
                        "similar places, or shooting advice. All natural-language JSON "
                        "values must be Simplified Chinese by default unless the user "
                        "explicitly asks for another language. "
                        f"Context JSON: {json.dumps(context, ensure_ascii=False)}"
                    ),
                },
            ],
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _parse_response(self, body: dict[str, Any]) -> dict[str, Any]:
        content, response_images = _chat_message_text_and_images(body)
        parsed = _loads_jsonish(content)
        if parsed.get("_parse_error"):
            return {
                "story_title": "照片背后的线索",
                "narrative": "",
                "one_line_answer": "",
                "deep_cards": [],
                "meaning_layers": {},
                "confidence_notes": ["叙事 JSON 未完整返回，已使用视觉线索生成公开内容。"],
                "followup_questions": [],
                "provider": "deepinfra",
                "model": body.get("model", self.model),
                "usage": body.get("usage", {}),
            }
        return {
            "story_title": str(parsed.get("story_title") or "照片背后的线索"),
            "narrative": str(parsed.get("narrative") or "").strip(),
            "one_line_answer": str(parsed.get("one_line_answer") or "").strip(),
            "deep_cards": _normalize_deep_cards(
                parsed.get("deep_cards"),
                response_images=response_images,
            ),
            "meaning_layers": _ensure_dict(parsed.get("meaning_layers")),
            "confidence_notes": _ensure_string_list(parsed.get("confidence_notes")),
            "followup_questions": _ensure_string_list(parsed.get("followup_questions")),
            "provider": "deepinfra",
            "model": body.get("model", self.model),
            "usage": body.get("usage", {}),
        }


def _chat_message_text_and_images(body: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    message = body.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content or ""), []

    text_parts: list[str] = []
    images: list[dict[str, str]] = []
    for item in content:
        if isinstance(item, str):
            text_parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text)
            continue
        if item_type in {"output_text", "text_delta"} and isinstance(item.get("content"), str):
            text_parts.append(str(item["content"]))
            continue
        image = _normalize_image_entry(item)
        if image:
            images.append(image)
    return "\n".join(text_parts), images


def _loads_jsonish(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {
            "_parse_error": "json_decode",
            "_raw_text_preview": text[:200],
            "place_candidates": [],
            "confidence": 0.2,
        }
    return loaded if isinstance(loaded, dict) else {}


def _clamp_confidence(value: Any) -> float:
    if isinstance(value, str):
        text = value.strip()
        is_percent = text.endswith("%")
        if is_percent:
            text = text[:-1].strip()
        try:
            numeric = float(text)
        except ValueError:
            return 0.2
        if is_percent or numeric > 1:
            numeric = numeric / 100
        return max(0.0, min(1.0, numeric))
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.2
    if numeric > 1:
        numeric = numeric / 100
    return max(0.0, min(1.0, numeric))


def _image_bytes_for_request(request: VisualExploreInput) -> list[bytes]:
    images = [image for image in request.images_bytes if image]
    if images:
        return images
    return [request.image_bytes] if request.image_bytes else []


def _followup_image_parts(request: VisualFollowupInput) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if request.image_url:
        parts.append({"type": "image_url", "image_url": {"url": request.image_url}})
    images = [image for image in request.images_bytes if image] or (
        [request.image_bytes] if request.image_bytes else []
    )
    for image_bytes in images:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        mime_type = _detect_image_mime(image_bytes)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
            }
        )
    return parts


def _compact_previous_visual_result(value: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "session_id",
        "what_it_is",
        "one_line_answer",
        "story_title",
        "narrative",
        "meaning_layers",
        "visible_clues",
        "cultural_hypotheses",
        "followup_questions",
    ]
    compact = {key: value.get(key) for key in keys if value.get(key)}
    deep_cards = value.get("deep_cards")
    if isinstance(deep_cards, list):
        compact["deep_cards"] = [
            {
                "title": item.get("title"),
                "body": item.get("body"),
                "supporting_points": item.get("supporting_points"),
            }
            for item in deep_cards[:3]
            if isinstance(item, dict)
        ]
    return compact


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_deep_cards(
    value: Any,
    response_images: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    cards = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        copy["title"] = str(copy.get("title") or "").strip()
        copy["body"] = str(copy.get("body") or "").strip()
        copy["supporting_points"] = _ensure_string_list(copy.get("supporting_points"))
        copy["next_action"] = str(copy.get("next_action") or "").strip()
        copy["sections"] = _normalize_deep_card_sections(copy.get("sections"))
        supplemental = _supplemental_section_from_card_media(copy)
        if supplemental:
            copy["sections"].append(supplemental)
        normalized.append(copy)
    if response_images and normalized:
        normalized[0]["sections"].append(
            {
                "title": "补充图像",
                "body": "",
                "bullets": [],
                "chips": [],
                "images": response_images,
            }
        )
    return normalized


def _normalize_deep_card_sections(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [_normalize_deep_card_section(raw, title=str(title)) for title, raw in value.items()]
    if isinstance(value, list):
        return [_normalize_deep_card_section(raw) for raw in value]
    return []


def _normalize_deep_card_section(raw: Any, title: str = "") -> dict[str, Any]:
    if isinstance(raw, dict):
        section_title = str(raw.get("title") or title).strip()
        raw_body = str(raw.get("body") or raw.get("text") or raw.get("summary") or "").strip()
        markdown_tables = _parse_markdown_tables(raw_body)
        body = _strip_markdown_tables(raw_body).strip() if markdown_tables else raw_body
        bullets = _ensure_string_list(raw.get("bullets") or raw.get("points"))
        chips = _ensure_string_list(raw.get("chips"))
        tables = _normalize_tables(raw.get("tables") or raw.get("table")) + markdown_tables
        images = _normalize_images(
            raw.get("images")
            or raw.get("image_urls")
            or raw.get("image_url")
            or raw.get("gallery")
        )
        return {
            "title": section_title,
            "body": body,
            "bullets": bullets,
            "chips": chips,
            **({"tables": tables} if tables else {}),
            **({"images": images} if images else {}),
        }
    if isinstance(raw, list):
        return {
            "title": title.strip(),
            "body": "",
            "bullets": _ensure_string_list(raw),
            "chips": [],
        }
    raw_text = str(raw or "").strip()
    markdown_tables = _parse_markdown_tables(raw_text)
    return {
        "title": title.strip(),
        "body": _strip_markdown_tables(raw_text).strip() if markdown_tables else raw_text,
        "bullets": [],
        "chips": [],
        **({"tables": markdown_tables} if markdown_tables else {}),
    }


def _supplemental_section_from_card_media(card: dict[str, Any]) -> dict[str, Any] | None:
    tables = _normalize_tables(card.pop("tables", None) or card.pop("table", None))
    images = _normalize_images(
        card.pop("images", None)
        or card.pop("image_urls", None)
        or card.pop("image_url", None)
        or card.pop("gallery", None)
    )
    if not tables and not images:
        return None
    return {
        "title": "补充资料",
        "body": "",
        "bullets": [],
        "chips": [],
        **({"tables": tables} if tables else {}),
        **({"images": images} if images else {}),
    }


def _normalize_tables(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    tables: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            tables.extend(_parse_markdown_tables(item))
            continue
        if not isinstance(item, dict):
            continue
        columns = _ensure_string_list(item.get("columns") or item.get("headers"))
        rows = _normalize_table_rows(item.get("rows"))
        if not columns and rows:
            columns = [f"列 {index + 1}" for index in range(len(rows[0]))]
        if not columns:
            continue
        tables.append(
            {
                "caption": str(item.get("caption") or item.get("title") or "").strip(),
                "columns": columns,
                "rows": rows,
            }
        )
    return tables


def _normalize_table_rows(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows: list[list[str]] = []
    for row in value:
        if isinstance(row, dict):
            rows.append([str(item).strip() for item in row.values()])
        elif isinstance(row, list):
            rows.append([str(item).strip() for item in row])
        elif row is not None:
            rows.append([str(row).strip()])
    return [row for row in rows if any(cell for cell in row)]


def _parse_markdown_tables(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines()]
    tables: list[dict[str, Any]] = []
    index = 0
    while index < len(lines) - 1:
        header = lines[index]
        separator = lines[index + 1]
        if not (_looks_like_table_row(header) and _looks_like_markdown_separator(separator)):
            index += 1
            continue
        columns = _split_markdown_table_row(header)
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and _looks_like_table_row(lines[index]):
            row = _split_markdown_table_row(lines[index])
            if row:
                rows.append(row)
            index += 1
        if columns and rows:
            tables.append({"caption": "", "columns": columns, "rows": rows})
        continue
    return tables


def _strip_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index].strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if _looks_like_table_row(current) and _looks_like_markdown_separator(next_line):
            index += 2
            while index < len(lines) and _looks_like_table_row(lines[index].strip()):
                index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept)


def _looks_like_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _looks_like_markdown_separator(line: str) -> bool:
    if not _looks_like_table_row(line):
        return False
    cells = _split_markdown_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_images(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    images: list[dict[str, str]] = []
    for item in items:
        image = _normalize_image_entry(item)
        if image:
            images.append(image)
    return images


def _normalize_image_entry(value: Any) -> dict[str, str] | None:
    if isinstance(value, str):
        url = value.strip()
        caption = ""
        source = ""
    elif isinstance(value, dict):
        image_url = value.get("image_url")
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
        else:
            url = str(
                value.get("url")
                or value.get("imageUrl")
                or value.get("src")
                or value.get("uri")
                or image_url
                or ""
            ).strip()
        caption = str(value.get("caption") or value.get("alt") or value.get("title") or "").strip()
        source = str(value.get("source") or value.get("provider") or "").strip()
    else:
        return None
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    return {"url": url, "caption": caption, "source": source}


def _normalize_hypotheses(value: Any) -> list[Any]:
    items = value if isinstance(value, list) else []
    normalized: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        copy = dict(item)
        for key in ("evidence_support", "evidence_against"):
            raw = copy.get(key)
            if isinstance(raw, str):
                copy[key] = [raw] if raw.strip() else []
            elif raw is None:
                copy[key] = []
            elif not isinstance(raw, list):
                copy[key] = [str(raw)]
        normalized.append(copy)
    return normalized


def _ensure_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _ensure_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _first_visible_clue(visual_reasoning: dict[str, Any]) -> str:
    clues = visual_reasoning.get("visible_clues")
    if isinstance(clues, list) and clues:
        first = clues[0]
        if isinstance(first, dict):
            return str(first.get("clue") or first.get("interpretation") or "线索不足")
        return str(first)
    return "线索还很少"


def _ensure_narrative_depth(
    result: dict[str, Any],
    visual_reasoning: dict[str, Any],
) -> dict[str, Any]:
    narrative = str(result.get("narrative") or "").strip()
    story_title = str(result.get("story_title") or "").strip()
    if not result.get("one_line_answer"):
        result["one_line_answer"] = _first_sentence(
            narrative or story_title or _subject_from_reasoning(visual_reasoning)
        )
    cards = result.get("deep_cards")
    if not isinstance(cards, list) or len(cards) != 3:
        result["deep_cards"] = _fallback_deep_cards(result, visual_reasoning)
    return result


def _fallback_deep_cards(
    result: dict[str, Any],
    visual_reasoning: dict[str, Any],
) -> list[dict[str, Any]]:
    subject = _subject_from_reasoning(visual_reasoning)
    clue = _first_visible_clue(visual_reasoning)
    layers = visual_reasoning.get("meaning_layers")
    cultural = ""
    practical = ""
    visual = ""
    if isinstance(layers, dict):
        visual = str(layers.get("visual") or "").strip()
        cultural = str(layers.get("cultural_history") or "").strip()
        practical = str(layers.get("practical") or "").strip()
    narrative = str(result.get("narrative") or "").strip()
    return [
        {
            "title": "识别",
            "body": (
                f"这是 {subject}。画面里的主体形态、材质、环境和可见线索构成核心识别依据。"
            ),
            "supporting_points": [clue],
            "next_action": "继续观察现场说明、周边街景和主体细节，可以把画面和真实地点连接起来。",
            "sections": [],
        },
        {
            "title": "看点",
            "body": (
                narrative
                or cultural
                or visual
                or "它值得看的地方不只是名称，而是画面里的地方气质、历史痕迹和人的使用方式如何叠在一起。"
            ),
            "supporting_points": [item for item in (cultural, visual) if item],
            "next_action": "可以继续追问它的历史、文化背景、相似地点或在当地生活里的真实用途。",
            "sections": [
                {"title": "历史/文化", "body": cultural or "它连接了地方记忆、日常使用和可见的文化痕迹。", "bullets": [], "chips": []},
                {"title": "美学/风格", "body": visual or "主体轮廓、尺度关系和材质细节构成画面的美感。", "bullets": [], "chips": []},
                {"title": "体验/地方意义", "body": narrative or "它适合作为现场观察的入口，让照片和真实地点发生关系。", "bullets": [], "chips": []},
            ],
        },
        {
            "title": "线索",
            "body": (
                practical
                or f"先看这条线索：{clue}。再看主体和环境之间的关系，而不是只记住一个名称。"
            ),
            "supporting_points": [clue],
            "next_action": "换一个角度再拍，或者补充城市/街区信息，我可以把它和附近地点继续联动。",
            "sections": [
                {"title": "画面细节", "body": f"先看这条线索：{clue}。", "bullets": [], "chips": [clue]},
                {"title": "下一步探索", "body": practical or "换一个角度或补充城市/街区信息，可以连接到附近相似地点和拍摄建议。", "bullets": [], "chips": []},
            ],
        },
    ]


def _subject_from_reasoning(visual_reasoning: dict[str, Any]) -> str:
    return str(visual_reasoning.get("subject") or "这张照片里的主体").strip()


def _first_sentence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for separator in ("。", "！", "？", ".", "!", "?"):
        index = text.find(separator)
        if index >= 0:
            return text[: index + len(separator)].strip()
    return text[:160].strip()


def _detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
