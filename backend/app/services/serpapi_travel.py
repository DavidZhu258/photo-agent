from __future__ import annotations

from typing import Any

import httpx

from app.schemas.travel import TravelPlanRequest


IATA_BY_CITY = {
    "tokyo": "HND",
    "東京": "HND",
    "东京": "HND",
    "fukuoka": "FUK",
    "福岡": "FUK",
    "福冈": "FUK",
    "osaka": "KIX",
    "大阪": "KIX",
    "kyoto": "ITM",
    "京都": "ITM",
    "beppu": "OIT",
    "別府": "OIT",
    "别府": "OIT",
    "hiroshima": "HIJ",
    "広島": "HIJ",
    "广岛": "HIJ",
    "miyajima": "HIJ",
    "宮島": "HIJ",
    "宫岛": "HIJ",
}


class SerpApiTravelClient:
    """Thin SerpAPI adapter for travel recommendation agents."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://serpapi.com/search.json",
        timeout_seconds: float = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def travel_explore(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        departure_id = _origin_iata(request)
        if departure_id is None:
            return []
        payload = await self._get(
            {
                "engine": "google_travel_explore",
                "departure_id": departure_id,
                "currency": "USD",
                "hl": "zh-cn",
                "gl": "us",
            }
        )
        return _list_from(payload, "destinations", "results", "trips")[:5]

    async def search_flights(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        departure_id = _origin_iata(request)
        arrival_id = _city_iata(request.city)
        if departure_id is None or arrival_id is None or not request.date_range:
            return []
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": request.date_range[0],
            "currency": "USD",
            "hl": "zh-cn",
            "gl": "us",
        }
        if len(request.date_range) > 1:
            params["return_date"] = request.date_range[1]
        payload = await self._get(params)
        return _list_from(payload, "best_flights", "other_flights", "flights")[:5]

    async def search_hotels(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "engine": "google_hotels",
            "q": f"{request.city} hotels",
            "currency": "USD",
            "hl": "zh-cn",
            "gl": "us",
        }
        if len(request.date_range) >= 2:
            params["check_in_date"] = request.date_range[0]
            params["check_out_date"] = request.date_range[1]
        payload = await self._get(params)
        return _list_from(payload, "properties", "hotels", "results")[:8]

    async def search_local(
        self,
        request: TravelPlanRequest,
        category: str,
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            {
                "engine": "google_maps",
                "q": f"{request.city} {category}",
                "type": "search",
                "hl": "zh-cn",
                "gl": "jp",
            }
        )
        return _list_from(payload, "local_results", "places", "results")[:8]

    async def search_query_variants(
        self,
        request: TravelPlanRequest,
        queries: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for query in [item.strip() for item in queries if item and item.strip()][:4]:
            payload = await self._get(
                {
                    "engine": "google_maps",
                    "q": query,
                    "type": "search",
                    "hl": "zh-cn",
                    "gl": "jp",
                }
            )
            for item in _list_from(payload, "local_results", "places", "results"):
                item = dict(item)
                item.setdefault("query_variant", query)
                item.setdefault("serper_endpoint", "places")
                results.append(item)
        return results[:12]

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.http_client.get(
            self.base_url,
            params={**params, "api_key": self.api_key},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _list_from(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _origin_iata(request: TravelPlanRequest) -> str | None:
    if request.origin_city:
        origin = _city_iata(request.origin_city)
        if origin:
            return origin
    text = " ".join(
        [
            request.query,
            request.question,
            " ".join(request.fixed_itinerary),
            " ".join(request.constraints),
        ]
    ).lower()
    for name, iata in IATA_BY_CITY.items():
        if name.lower() in text and name.lower() not in request.city.lower():
            return iata
    return None


def _city_iata(city: str) -> str | None:
    normalized = city.lower()
    for name, iata in IATA_BY_CITY.items():
        if name.lower() in normalized:
            return iata
    return None
