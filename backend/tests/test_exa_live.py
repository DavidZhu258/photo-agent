import os

import pytest

from app.services.exa_search import ExaSearchClient


@pytest.mark.asyncio
async def test_exa_live_smoke_searches_travel_evidence():
    if os.getenv("RUN_EXA_LIVE") != "1" or not os.getenv("EXA_API_KEY"):
        pytest.skip("Set RUN_EXA_LIVE=1 and EXA_API_KEY to run live test")

    client = ExaSearchClient(
        api_key=os.environ["EXA_API_KEY"],
        timeout_seconds=20,
    )

    results = await client.search(
        "Kyoto quiet garden temple reddit local traveler recommendation",
        max_results=3,
    )

    assert results
    assert any(result.get("url") for result in results)
