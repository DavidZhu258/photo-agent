from __future__ import annotations

import json

import httpx
import pytest

from app.schemas.visual import VisualExploreInput
from app.services.visual_history import SerperOfficialHistoryClient


@pytest.mark.asyncio
async def test_serper_official_history_client_prefers_official_history_result():
    captured_payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Shoren-in Monzeki - Wikipedia",
                        "link": "https://en.wikipedia.org/wiki/Sh%C5%8Dren-in",
                        "snippet": "General encyclopedia result.",
                    },
                    {
                        "title": "Official history | Shoren-in Monzeki",
                        "link": "https://www.shorenin.com/english/history/",
                        "snippet": "The temple traces its origin to the Tendai school and preserves imperial-monzeki history.",
                    },
                ]
            },
        )

    client = SerperOfficialHistoryClient(
        api_key="serper-test-key",
        base_url="https://google.serper.dev",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.enrich(
        VisualExploreInput(
            image_bytes=b"fake-image",
            exploration_focus="history",
            user_context_text="青蓮院門跡",
        ),
        {
            "subject": "Shoren-in Monzeki",
            "place_candidates": ["青蓮院門跡"],
            "meaning_layers": {"visual": "painted gate"},
        },
    )

    assert captured_payloads
    assert "Shoren-in Monzeki" in captured_payloads[0]["q"]
    assert "official" in captured_payloads[0]["q"].lower()
    assert result["official_history_sources"][0]["url"] == "https://www.shorenin.com/english/history/"
    assert "Official history" in result["official_history_sources"][0]["title"]
    assert "Tendai school" in result["meaning_layers"]["cultural_history"]
    assert result["evidence_cards"][0].source_type == "official_history"


@pytest.mark.asyncio
async def test_serper_official_history_client_skips_non_history_object_requests():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("non-history object requests should not call Serper")

    client = SerperOfficialHistoryClient(
        api_key="serper-test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.enrich(
        VisualExploreInput(image_bytes=b"fake-image", exploration_focus="auto"),
        {"subject": "cream kitten", "place_candidates": []},
    )

    assert result == {}
