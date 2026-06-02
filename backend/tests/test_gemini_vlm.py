import json

import httpx
import pytest

from app.schemas.visual import ClientOcr, VisualExploreInput
from app.services.vlm import GeminiVlmClient


@pytest.mark.asyncio
async def test_gemini_client_sends_multimodal_payload_and_parses_visual_json():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "subject": "Kushida Shrine",
                                            "place_candidates": [
                                                "Kushida Shrine",
                                                "櫛田神社",
                                            ],
                                            "confidence": 0.84,
                                            "visible_clues": [
                                                {
                                                    "clue": "shrine gate and lanterns",
                                                    "interpretation": "Hakata shrine architecture",
                                                    "confidence": 0.78,
                                                }
                                            ],
                                            "cultural_hypotheses": [
                                                {
                                                    "name": "Kushida Shrine",
                                                    "entity_type": "landmark",
                                                    "region": "Fukuoka, Japan",
                                                    "rationale": "visible shrine features match Hakata context",
                                                    "confidence": 0.82,
                                                    "evidence_support": [
                                                        "gate",
                                                        "lanterns",
                                                    ],
                                                    "evidence_against": [
                                                        "single angle only"
                                                    ],
                                                }
                                            ],
                                            "meaning_layers": {
                                                "visual": "shrine textures and lanterns",
                                                "cultural_history": "Hakata cultural anchor",
                                                "emotional": "quiet arrival point",
                                                "practical": "check with map context",
                                            },
                                            "known_comparisons": ["Hakata shrines"],
                                            "confidence_notes": ["needs map confirmation"],
                                            "suggested_perspectives": [
                                                "guide",
                                                "history",
                                                "culture",
                                            ],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 80},
                "modelVersion": "gemini-3.1-pro-preview",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GeminiVlmClient(
            api_key="test-gemini-key",
            model="gemini-3.1-pro-preview",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            thinking_level="HIGH",
            media_resolution="HIGH",
            http_client=http_client,
        ).identify(
            VisualExploreInput(
                image_bytes=b"fake-jpeg",
                images_bytes=[b"fake-jpeg", b"second-angle"],
                client_ocr=ClientOcr(text=""),
                gps_lat=33.593,
                gps_lng=130.410,
                user_context_text="福冈博多附近",
                exploration_focus="auto",
            )
        )

    assert "/models/gemini-3.1-pro-preview:generateContent" in captured["url"]
    assert "key=test-gemini-key" in captured["url"]
    payload = captured["payload"]
    parts = payload["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[0]["inlineData"]["data"]
    assert parts[1]["inlineData"]["data"]
    assert "strict JSON" in parts[-1]["text"]
    assert "福冈博多附近" in parts[-1]["text"]
    assert payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "HIGH"
    assert payload["generationConfig"]["mediaResolution"] == "HIGH"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert result["provider"] == "gemini"
    assert result["model"] == "gemini-3.1-pro-preview"
    assert result["subject"] == "Kushida Shrine"
    assert result["place_candidates"] == ["Kushida Shrine", "櫛田神社"]
    assert result["visible_clues"][0]["clue"] == "shrine gate and lanterns"
    assert result["cultural_hypotheses"][0]["region"] == "Fukuoka, Japan"
    assert result["usage"]["promptTokenCount"] == 120


@pytest.mark.asyncio
async def test_gemini_client_falls_back_on_provider_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GeminiVlmClient(
            api_key="test-gemini-key",
            model="gemini-3.1-pro-preview",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=b"fake-jpeg"))

    assert result["subject"] == "unknown visual subject"
    assert result["provider_error"] == "HTTPStatusError"
