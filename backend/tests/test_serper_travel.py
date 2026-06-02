from __future__ import annotations

import json

import httpx
import pytest

from app.schemas.travel import TravelPlanRequest
from app.services.serper_travel import SerperTravelClient


@pytest.mark.asyncio
async def test_serper_travel_client_uses_x_api_key_and_posts_to_places():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-API-KEY"] == "serper-test-key"
        assert request.method == "POST"
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "title": "Yanagibashi Rengo Market",
                            "rating": 4.3,
                            "ratingCount": 1200,
                            "address": "Fukuoka",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"organic": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        results = await client.search_local(
            TravelPlanRequest(city="Fukuoka", query="local food"),
            "food restaurants",
        )

    assert requests[0].url.path.endswith("/places")
    assert results[0]["title"] == "Yanagibashi Rengo Market"


@pytest.mark.asyncio
async def test_serper_local_search_ignores_places_endpoint_organic_fallback():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "THE 15 BEST Things to Do in Fukuoka",
                            "link": "https://example.com/listicle",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"organic": [{"title": "Fallback search result"}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        results = await client.search_local(
            TravelPlanRequest(city="Fukuoka", query="things to do"),
            "things to do attractions",
        )

    assert paths == ["/places", "/search"]
    assert results[0]["title"] == "Fallback search result"


@pytest.mark.asyncio
async def test_serper_local_search_reports_places_http_failure_without_search_fallback():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/places"):
            return httpx.Response(
                400,
                json={"message": "Not enough credits", "statusCode": 400},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Fukuoka useful fallback",
                        "snippet": "Things to do, neighborhoods, and practical notes.",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_local(
                TravelPlanRequest(city="Fukuoka", query="things to do"),
                "things to do attractions",
            )

    assert paths == ["/places"]


@pytest.mark.asyncio
async def test_serper_query_variants_report_places_http_failure_without_search_fallback():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        paths.append(request.url.path)
        if request.url.path.endswith("/places"):
            return httpx.Response(
                400,
                json={"message": "Not enough credits", "statusCode": 400},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": f"{payload['q']} fallback guide",
                        "link": f"https://example.com/{len(paths)}",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_query_variants(
                TravelPlanRequest(city="Fukuoka", query="福冈有什么好玩的？"),
                ["福冈有什么好玩的？", "Fukuoka things to do"],
            )

    assert paths == ["/places"]


@pytest.mark.asyncio
async def test_serper_raw_query_uses_localized_payload_and_japanese_query_variants():
    payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        payloads.append({"path": request.url.path, **payload})
        return httpx.Response(
            200,
            json={
                "places": [{"title": payload["q"], "address": "Fukuoka"}],
                "organic": [{"title": payload["q"], "link": "https://example.com"}],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        results = await client.search_raw_query(
            TravelPlanRequest(city="Fukuoka", query="nicolai 福冈 香水")
        )

    queries = [payload["q"] for payload in payloads]
    assert "nicolai 福冈 香水" in queries
    assert "Nicolai Parfumeur 福岡" in queries
    assert "ニコライ 香水 福岡" in queries
    assert "NOSE SHOP Nicolai 福岡" in queries
    assert "Nicolai Bergmann 福岡" not in queries
    assert any(payload["path"] == "/places" for payload in payloads)
    assert any(payload["path"] == "/search" for payload in payloads)
    assert all(payload["gl"] == "jp" for payload in payloads)
    assert all(payload["location"] == "Fukuoka, Japan" for payload in payloads)
    assert all(payload["num"] == 10 for payload in payloads)
    assert all(payload["autocorrect"] is True for payload in payloads)
    assert len(results) == len({item["title"] for item in results})


@pytest.mark.asyncio
async def test_serper_raw_query_keeps_bergmann_variants_for_explicit_bergmann_query():
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        queries.append(payload["q"])
        return httpx.Response(200, json={"places": [{"title": payload["q"]}], "organic": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        await client.search_raw_query(
            TravelPlanRequest(city="Fukuoka", query="Nicolai Bergmann 福冈 花店")
        )

    assert "Nicolai Bergmann 福岡" in queries
    assert "ニコライ・バーグマン 福岡" in queries


@pytest.mark.asyncio
async def test_serper_travel_client_uses_search_fallback_for_flights_and_hotels():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Tokyo to Fukuoka flights",
                        "snippet": "Compare direct flight options.",
                        "link": "https://example.com/flights",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        flights = await client.search_flights(
            TravelPlanRequest(
                city="Fukuoka",
                origin_city="Tokyo",
                date_range=["2026-06-10", "2026-06-12"],
            )
        )
        hotels = await client.search_hotels(
            TravelPlanRequest(
                city="Fukuoka",
                date_range=["2026-06-10", "2026-06-12"],
            )
        )

    assert paths == ["/search", "/search"]
    assert flights[0]["title"] == "Tokyo to Fukuoka flights"
    assert hotels[0]["title"] == "Tokyo to Fukuoka flights"


@pytest.mark.asyncio
async def test_serper_travel_client_adds_budget_transport_and_optional_searches():
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        queries.append(payload)
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Useful travel result",
                        "snippet": "Budget, transport, visa, weather, and safety context.",
                        "link": "https://example.com/travel-context",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://google.serper.dev",
    ) as http_client:
        client = SerperTravelClient(
            api_key="serper-test-key",
            base_url="https://google.serper.dev",
            http_client=http_client,
        )
        request = TravelPlanRequest(
            city="Fukuoka",
            origin_city="Tokyo",
            budget="中等预算",
            query="女生 solo 旅行，担心天气和入境政策",
        )
        budget = await client.search_budget(request)
        transport = await client.search_transport(request)
        visa = await client.search_visa(request)
        weather = await client.search_weather(request)
        safety = await client.search_safety(request)

    assert all(result[0]["title"] == "Useful travel result" for result in [budget, transport, visa, weather, safety])
    joined = "\n".join(queries).lower()
    assert "daily budget" in joined
    assert "hidden fees" in joined
    assert "tokyo to fukuoka" in joined
    assert "metro" in joined
    assert "taxi" in joined
    assert "visa" in joined
    assert "weather" in joined
    assert "solo" in joined
