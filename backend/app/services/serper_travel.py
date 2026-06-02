from __future__ import annotations

from typing import Any

import httpx

from app.schemas.travel import TravelPlanRequest


class SerperTravelClient:
    """Serper.dev adapter with the same methods the supervisor expects."""

    provider_name = "serper"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://google.serper.dev",
        timeout_seconds: float = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def travel_explore(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        return await self._search(
            f"{request.city} travel guide best season itinerary local food hotels",
            request=request,
        )

    async def search_flights(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        origin = request.origin_city or "origin"
        dates = " ".join(request.date_range)
        return await self._search(
            f"{origin} to {request.city} flights {dates} price schedule direct",
            request=request,
        )

    async def search_hotels(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        dates = " ".join(request.date_range)
        budget = request.budget or "good value"
        return await self._search(
            f"{request.city} hotels {dates} {budget} best area reviews",
            request=request,
        )

    async def search_budget(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        return await self._search(
            " ".join(
                [
                    request.city,
                    "daily budget travel cost value comparison hidden fees",
                    request.budget or "",
                    "food transport hotel attractions",
                ]
            ),
            request=request,
        )

    async def search_transport(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        origin = (request.origin_city or "").strip()
        destination = request.city.strip()
        intercity = (
            f"{origin} to {destination} train bus flight route timetable fare"
            if origin and destination and origin.lower() != destination.lower()
            else ""
        )
        return await self._search(
            " ".join(
                [
                    intercity or destination,
                    "local transport metro subway bus train taxi Grab rental car pass",
                    "airport transfer day trip practical guide",
                ]
            ),
            request=request,
        )

    async def search_visa(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        origin = request.origin_city or "traveler"
        return await self._search(
            f"{request.city} visa entry requirements immigration policy {origin}",
            request=request,
        )

    async def search_weather(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        dates = " ".join(request.date_range)
        return await self._search(
            f"{request.city} weather best travel time season risk typhoon rain {dates}",
            request=request,
        )

    async def search_safety(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        return await self._search(
            f"{request.city} safety index travel insurance solo female traveler tips",
            request=request,
        )

    async def search_raw_query(self, request: TravelPlanRequest) -> list[dict[str, Any]]:
        variants = _query_variants(request, request.query)
        return await self.search_query_variants(request, variants)

    async def search_query_variants(
        self,
        request: TravelPlanRequest,
        queries: list[str],
    ) -> list[dict[str, Any]]:
        variants = [query.strip() for query in queries if query and query.strip()]
        results: list[dict[str, Any]] = []
        for query in variants[:4]:
            places_payload = _localized_payload(request, query)
            places_response = await self._post("/places", places_payload)
            for item in _list_from(places_response, "places", "localResults", "organic"):
                item = dict(item)
                item.setdefault("query_variant", query)
                item.setdefault("serper_endpoint", "places")
                results.append(item)
        for query in variants[:4]:
            search_results = await self._search(query, request=request)
            for item in search_results:
                item = dict(item)
                item.setdefault("query_variant", query)
                item.setdefault("serper_endpoint", "search")
                results.append(item)
        return _dedupe_results(results)[:12]

    async def search_local(
        self,
        request: TravelPlanRequest,
        category: str,
    ) -> list[dict[str, Any]]:
        response = await self._post(
            "/places",
            _localized_payload(request, f"{request.city} {category}"),
        )
        places = _list_from(response, "places", "localResults")
        if places:
            normalized_places = []
            for item in places[:8]:
                normalized = dict(item)
                normalized.setdefault("serper_endpoint", "places")
                normalized.setdefault("query_variant", f"{request.city} {category}".strip())
                normalized_places.append(normalized)
            return normalized_places
        search_results = await self._search(f"{request.city} {category} best local reviews", request=request)
        normalized_results = []
        for item in search_results[:8]:
            normalized = dict(item)
            normalized.setdefault("serper_endpoint", "search")
            normalized.setdefault("query_variant", f"{request.city} {category} best local reviews".strip())
            normalized_results.append(normalized)
        return normalized_results

    async def search_images(self, request: TravelPlanRequest, query: str) -> list[dict[str, Any]]:
        response = await self._post(
            "/images",
            _localized_payload(request, query, num=8),
        )
        return _list_from(response, "images", "organic", "imageResults")[:8]

    async def _search(
        self,
        query: str,
        *,
        request: TravelPlanRequest | None = None,
    ) -> list[dict[str, Any]]:
        response = await self._post(
            "/search",
            _localized_payload(request, query) if request else _default_payload(query),
        )
        return _list_from(response, "organic", "places", "localResults")[:8]

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.http_client.post(
            f"{self.base_url}{path}",
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}


def _list_from(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _default_payload(query: str) -> dict[str, Any]:
    return {
        "q": query,
        "gl": "jp",
        "hl": "zh-cn",
        "location": "Japan",
        "num": 10,
        "autocorrect": True,
    }


def _localized_payload(
    request: TravelPlanRequest | None,
    query: str,
    *,
    num: int = 10,
) -> dict[str, Any]:
    payload = _default_payload(query)
    payload["num"] = num
    if request is not None:
        payload["hl"] = _hl_for_request(request)
        payload["location"] = _location_for_city(request.city)
    return payload


def _hl_for_request(request: TravelPlanRequest) -> str:
    text = f"{request.query} {request.city}"
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh-cn"
    return "en"


def _location_for_city(city: str) -> str:
    aliases = {
        "fukuoka": "Fukuoka, Japan",
        "福冈": "Fukuoka, Japan",
        "福岡": "Fukuoka, Japan",
        "kyoto": "Kyoto, Japan",
        "京都": "Kyoto, Japan",
        "osaka": "Osaka, Japan",
        "大阪": "Osaka, Japan",
        "beppu": "Beppu, Japan",
        "别府": "Beppu, Japan",
        "別府": "Beppu, Japan",
        "miyajima": "Miyajima, Hiroshima, Japan",
        "宫岛": "Miyajima, Hiroshima, Japan",
        "宮島": "Miyajima, Hiroshima, Japan",
        "hiroshima": "Hiroshima, Japan",
        "广岛": "Hiroshima, Japan",
        "広島": "Hiroshima, Japan",
    }
    normalized = city.strip().lower()
    return aliases.get(normalized) or aliases.get(city.strip()) or f"{city}, Japan"


def _query_variants(request: TravelPlanRequest, seed_query: str) -> list[str]:
    variants = [seed_query.strip()]
    city_aliases = _city_aliases(request.city)
    lowered = seed_query.lower()
    is_fragrance_query = any(
        token in lowered or token in seed_query
        for token in ["香水", "perfume", "fragrance", "parfum", "パルファム"]
    )
    explicit_bergmann = "bergmann" in lowered or "バーグマン" in seed_query
    if "nicolai" in lowered or "ニコライ" in seed_query:
        if is_fragrance_query and not explicit_bergmann:
            variants.extend(
                [
                    "Nicolai Parfumeur 福岡",
                    "ニコライ 香水 福岡",
                    "NOSE SHOP Nicolai 福岡",
                ]
            )
        else:
            variants.extend(
                [
                    "Nicolai Bergmann 福岡",
                    "ニコライ・バーグマン 福岡",
                    "ニコライバーグマン 福岡",
                ]
            )
    if city_aliases:
        for alias in city_aliases:
            variants.append(f"{seed_query} {alias}".strip())
    return [item for item in dict.fromkeys(variants) if item]


def _city_aliases(city: str) -> list[str]:
    normalized = city.lower().strip()
    if normalized in {"fukuoka", "福冈", "福岡"}:
        return ["Fukuoka", "福岡", "ふくおか"]
    if normalized in {"kyoto", "京都"}:
        return ["Kyoto", "京都"]
    if normalized in {"osaka", "大阪"}:
        return ["Osaka", "大阪"]
    if normalized in {"beppu", "别府", "別府"}:
        return ["Beppu", "別府"]
    return [city] if city else []


def _dedupe_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for item in items:
        title = str(item.get("title") or item.get("name") or "").strip().lower()
        link = str(item.get("link") or item.get("website") or "").strip().lower()
        address = str(item.get("address") or "").strip().lower()
        key = title or "|".join(part for part in [link, address] if part)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
