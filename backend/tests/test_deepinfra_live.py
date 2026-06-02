import base64
import os

import httpx
import pytest

from app.config import settings
from app.schemas.visual import ClientOcr, VisualExploreInput
from app.schemas.travel import TravelPlanRequest
from app.services.travel_planner import LightweightTravelPlanner
from app.services.travel_reasoning import DeepInfraTravelDecisionClient
from app.services.vlm import DeepInfraNarrativeClient, DeepInfraVlmClient


TRAVEL_DEEPINFRA_MODELS = list(
    dict.fromkeys(
        [
            settings.travel_model_router,
            settings.travel_model_fast,
            settings.travel_model_reasoning,
            settings.travel_model_critic,
            settings.travel_model_formatter,
            settings.travel_decision_model,
        ]
    )
)

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)

_LANDMARK_CASES = [
    (
        "Eiffel Tower",
        "https://images.unsplash.com/photo-1511739001486-6bfe10ce785f?w=900&q=80&fm=jpg",
        {"eiffel", "tour eiffel", "埃菲尔", "艾菲尔"},
    ),
    (
        "Taj Mahal",
        "https://images.unsplash.com/photo-1564507592333-c60657eea523?w=900&q=80&fm=jpg",
        {"taj mahal", "泰姬陵"},
    ),
    (
        "Sydney Opera House",
        "https://images.unsplash.com/photo-1506973035872-a4ec16b8e8d9?w=900&q=80&fm=jpg",
        {"sydney opera", "悉尼歌剧院"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", TRAVEL_DEEPINFRA_MODELS)
async def test_travel_deepinfra_exact_model_ids_live_smoke(model: str):
    if os.getenv("RUN_TRAVEL_MODEL_LIVE") != "1" or not os.getenv("DEEPINFRA_API_KEY"):
        pytest.skip("Set RUN_TRAVEL_MODEL_LIVE=1 and DEEPINFRA_API_KEY to verify travel models")

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{os.getenv('DEEPINFRA_BASE_URL', 'https://api.deepinfra.com/v1/openai').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['DEEPINFRA_API_KEY']}"},
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 512,
                "messages": [
                    {
                        "role": "user",
                        "content": "Return strict JSON only: {\"ok\": true}",
                    }
                ],
            },
        )

    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert "ok" in content.lower()


@pytest.mark.asyncio
async def test_deepinfra_live_smoke_identifies_valid_image():
    if os.getenv("RUN_DEEPINFRA_LIVE") != "1" or not os.getenv("DEEPINFRA_API_KEY"):
        pytest.skip("Set RUN_DEEPINFRA_LIVE=1 and DEEPINFRA_API_KEY to run live test")

    client = DeepInfraVlmClient(
        api_key=os.environ["DEEPINFRA_API_KEY"],
        model=os.getenv("DEEPINFRA_VISION_MODEL", settings.deepinfra_vision_model),
        timeout_seconds=45,
    )
    result = await client.identify(
        VisualExploreInput(
            image_bytes=_ONE_PIXEL_PNG,
            client_ocr=ClientOcr(text="live smoke test image"),
            interest_tags=["test"],
        )
    )

    assert result.get("provider") == "deepinfra"
    assert "provider_error" not in result
    assert result.get("subject")


@pytest.mark.asyncio
async def test_deepinfra_live_smoke_composes_narrative():
    if os.getenv("RUN_DEEPINFRA_LIVE") != "1" or not os.getenv("DEEPINFRA_API_KEY"):
        pytest.skip("Set RUN_DEEPINFRA_LIVE=1 and DEEPINFRA_API_KEY to run live test")

    client = DeepInfraNarrativeClient(
        api_key=os.environ["DEEPINFRA_API_KEY"],
        model=os.getenv("DEEPINFRA_NARRATIVE_MODEL", "google/gemma-4-26B-A4B-it"),
        timeout_seconds=45,
    )
    result = await client.compose(
        VisualExploreInput(user_context_text="live smoke test", exploration_focus="object"),
        visual_reasoning={
            "subject": "one pixel image",
            "visible_clues": [
                {
                    "clue": "single white pixel",
                    "interpretation": "test image with no cultural meaning",
                    "confidence": 0.99,
                }
            ],
        },
        evidence_cards=[],
    )

    assert result.get("provider") == "deepinfra"
    assert "provider_error" not in result
    assert result.get("story_title")
    assert result.get("one_line_answer")
    assert len(result.get("deep_cards") or []) == 3


@pytest.mark.asyncio
async def test_deepinfra_live_smoke_makes_travel_decision():
    if os.getenv("RUN_DEEPINFRA_LIVE") != "1" or not os.getenv("DEEPINFRA_API_KEY"):
        pytest.skip("Set RUN_DEEPINFRA_LIVE=1 and DEEPINFRA_API_KEY to run live test")

    ranked = (
        await LightweightTravelPlanner().plan(
            TravelPlanRequest(
                city="Kyoto",
                question="我下午到京都，想避开游客，有没有值得深入看的地方？",
                interest_tags=["quiet", "garden", "history"],
                constraints=["avoid crowds"],
            )
        )
    ).recommendations
    client = DeepInfraTravelDecisionClient(
        api_key=os.environ["DEEPINFRA_API_KEY"],
        model=os.getenv("TRAVEL_DECISION_MODEL", settings.travel_decision_model),
        reasoning_effort=settings.travel_model_reasoning_effort,
        timeout_seconds=45,
    )
    result = await client.decide(
        TravelPlanRequest(
            city="Kyoto",
            question="我下午到京都，想避开游客，有没有值得深入看的地方？",
            interest_tags=["quiet", "garden", "history"],
            constraints=["avoid crowds"],
        ),
        ranked,
    )

    assert result.get("summary")
    assert result.get("recommendations")
    assert result["recommendations"][0].get("decision") in {
        "recommended",
        "conditional",
        "not_recommended",
        "insufficient_evidence",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("label,image_url,expected_terms", _LANDMARK_CASES)
async def test_deepinfra_live_identifies_iconic_buildings_without_text(
    label, image_url, expected_terms
):
    if (
        os.getenv("RUN_DEEPINFRA_LANDMARK_LIVE") != "1"
        or not os.getenv("DEEPINFRA_API_KEY")
    ):
        pytest.skip(
            "Set RUN_DEEPINFRA_LANDMARK_LIVE=1 and DEEPINFRA_API_KEY to run landmark live test"
        )

    client = DeepInfraVlmClient(
        api_key=os.environ["DEEPINFRA_API_KEY"],
        model=os.getenv("DEEPINFRA_VISION_MODEL", settings.deepinfra_vision_model),
        timeout_seconds=60,
    )
    image_bytes = await _download_landmark_image(image_url)
    result = await client.identify(
        VisualExploreInput(image_bytes=image_bytes, exploration_focus="place")
    )

    haystack = " ".join(
        [
            str(result.get("subject") or ""),
            " ".join(str(item) for item in result.get("place_candidates") or []),
            " ".join(
                str(item.get("name") or "")
                for item in result.get("cultural_hypotheses") or []
                if isinstance(item, dict)
            ),
        ]
    ).lower()
    assert any(term.lower() in haystack for term in expected_terms), (
        label,
        result,
    )
    assert result.get("confidence", 0) >= 0.5


async def _download_landmark_image(url: str) -> bytes:
    async with httpx.AsyncClient(
        timeout=45,
        headers={
            "User-Agent": "photo-agent-landmark-live-test/0.1 (local self-test)",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
        },
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
