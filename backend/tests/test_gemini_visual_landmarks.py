import base64
import json
import os

import httpx
import pytest

from app.schemas.visual import VisualExploreInput
from app.services.vlm import GeminiVlmClient
from app.services.visual_workflow import enrich_visual_response
from app.schemas.visual import ShootHint, VisualExploreResponse


_MATRIX_CASES = [
    (
        "KYU-01",
        "Fukuoka Tower",
        ["Fukuoka Tower", "福岡タワー", "福冈塔"],
        "Fukuoka, Japan",
        ["guide", "style"],
    ),
    (
        "KYU-02",
        "Dazaifu Tenmangu",
        ["Dazaifu Tenmangu", "太宰府天満宮", "太宰府天满宫"],
        "Fukuoka, Japan",
        ["guide", "history", "culture"],
    ),
    (
        "KAN-01",
        "Kiyomizu-dera",
        ["Kiyomizu-dera", "清水寺"],
        "Kyoto, Japan",
        ["history", "culture", "style"],
    ),
    (
        "KAN-10",
        "Himeji Castle",
        ["Himeji Castle", "姫路城"],
        "Hyogo, Japan",
        ["guide", "history"],
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,subject,terms,region,perspectives", _MATRIX_CASES)
async def test_japan_landmark_matrix_mocked_gemini_contract(
    case_id,
    subject,
    terms,
    region,
    perspectives,
):
    async def handler(request: httpx.Request) -> httpx.Response:
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
                                            "subject": subject,
                                            "place_candidates": terms,
                                            "confidence": 0.86,
                                            "visible_clues": [
                                                {
                                                    "clue": f"{subject} distinctive shape",
                                                    "interpretation": f"visible features match {subject}",
                                                    "confidence": 0.82,
                                                }
                                            ],
                                            "cultural_hypotheses": [
                                                {
                                                    "name": subject,
                                                    "entity_type": "landmark",
                                                    "region": region,
                                                    "rationale": f"{case_id} matches the Japan visual matrix.",
                                                    "confidence": 0.84,
                                                    "evidence_support": terms[:2],
                                                    "evidence_against": [
                                                        "single image still needs confirmation"
                                                    ],
                                                }
                                            ],
                                            "meaning_layers": {
                                                "visual": "distinctive landmark geometry",
                                                "cultural_history": "important local cultural context",
                                                "emotional": "arrival and place memory",
                                                "practical": "confirm with map context",
                                            },
                                            "confidence_notes": [
                                                "single image still needs confirmation"
                                            ],
                                            "suggested_perspectives": perspectives,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ],
                "modelVersion": "gemini-3.1-pro-preview",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        visual_reasoning = await GeminiVlmClient(
            api_key="test-gemini-key",
            model="gemini-3.1-pro-preview",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=f"{case_id}-image".encode()))

    response = VisualExploreResponse(
        session_id=f"snap_{case_id}",
        what_it_is=subject,
        why_it_matters=f"{subject} belongs in the Japan golden visual matrix.",
        why_popular_or_overhyped="It should be explained with visible clues and uncertainty.",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="soft light",
            stand_where="front viewing point",
            face_where="toward the landmark",
            how_to_shoot="include the landmark and surrounding context",
        ),
        evidence_cards=[],
        confidence=0.86,
        needs_user_confirmation=False,
        story_title=f"{subject} visual story",
        narrative=f"This image likely shows {subject}.",
    )
    enriched = enrich_visual_response(
        response,
        VisualExploreInput(image_sha256=case_id, image_bytes=b"x"),
        visual_reasoning=visual_reasoning,
        model_used="gemini-3.1-pro-preview",
    )

    joined = " ".join(
        [visual_reasoning["subject"], *visual_reasoning["place_candidates"]]
    )
    assert any(term in joined for term in terms)
    assert visual_reasoning["cultural_hypotheses"][0]["region"] == region
    assert enriched.perspective_cards
    assert set(perspectives).issubset(
        {card.perspective for card in enriched.perspective_cards}
    )
    assert enriched.visual_workflow_summary.uncertainty


@pytest.mark.asyncio
async def test_gemini_visual_live_japan_landmark_gate():
    if os.getenv("RUN_GEMINI_VISUAL_LIVE") != "1":
        pytest.skip("Set RUN_GEMINI_VISUAL_LIVE=1 and GOOGLE_API_KEY to run live test")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY is required for Gemini live visual test")

    # A tiny byte payload is intentionally not a real landmark. This gate only verifies
    # credentials/client path without depending on external image hosting.
    image_bytes = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2w==")
    result = await GeminiVlmClient(api_key=api_key).identify(
        VisualExploreInput(image_bytes=image_bytes)
    )

    assert "subject" in result
    assert "confidence" in result
