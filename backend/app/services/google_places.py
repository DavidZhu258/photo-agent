from __future__ import annotations

import math
import re
from typing import Any

import httpx

from app.schemas.travel import TravelPlanRequest


GOOGLE_PLACE_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.rating,"
    "places.userRatingCount,"
    "places.googleMapsUri,"
    "places.photos,"
    "places.types,"
    "places.priceLevel"
)


class GooglePlacesClient:
    """Small adapter for Google Places Text Search (New) and Place Photos."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://places.googleapis.com/v1",
        timeout_seconds: float = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def resolve_place(
        self,
        *,
        request: TravelPlanRequest,
        title: str,
        address: str,
        lat: float | None,
        lng: float | None,
    ) -> dict[str, Any] | None:
        text_query = _place_text_query(title=title, address=address, city=request.city)
        if not text_query:
            return None
        response = await self.http_client.post(
            f"{self.base_url}/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": GOOGLE_PLACE_FIELD_MASK,
            },
            json={
                "textQuery": text_query,
                "languageCode": _language_code(request),
                "regionCode": "JP",
                "maxResultCount": 3,
            },
        )
        response.raise_for_status()
        payload = response.json()
        places = payload.get("places") if isinstance(payload, dict) else []
        if not isinstance(places, list):
            return None
        place = _best_matching_place(places, title=title, address=address, lat=lat, lng=lng)
        if place is None:
            return None
        photo_urls, attributions = await self._photo_urls(place)
        return {
            "place_id": str(place.get("id") or ""),
            "title": _display_name(place) or title,
            "address": str(place.get("formattedAddress") or address or ""),
            "lat": _place_lat(place) if _place_lat(place) is not None else lat,
            "lng": _place_lng(place) if _place_lng(place) is not None else lng,
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "google_maps_uri": str(place.get("googleMapsUri") or ""),
            "image_urls": photo_urls,
            "photo_attributions": attributions,
        }

    async def _photo_urls(self, place: dict[str, Any]) -> tuple[list[str], list[str]]:
        urls: list[str] = []
        attributions: list[str] = []
        photos = place.get("photos")
        if not isinstance(photos, list):
            return urls, attributions
        for photo in photos[:4]:
            if not isinstance(photo, dict):
                continue
            photo_name = str(photo.get("name") or "").strip()
            if not photo_name:
                continue
            attributions.extend(_photo_attributions(photo))
            response = await self.http_client.get(
                f"{self.base_url}/{photo_name}/media",
                headers={"X-Goog-Api-Key": self.api_key},
                params={
                    "maxWidthPx": 1200,
                    "maxHeightPx": 900,
                    "skipHttpRedirect": "true",
                },
            )
            response.raise_for_status()
            payload = response.json()
            photo_uri = str(payload.get("photoUri") or "").strip() if isinstance(payload, dict) else ""
            if photo_uri.startswith("http"):
                urls.append(photo_uri)
        return _unique(urls), _unique(attributions)


def _place_text_query(*, title: str, address: str, city: str) -> str:
    return " ".join(part.strip() for part in [title, address, city] if part and part.strip())


def _language_code(request: TravelPlanRequest) -> str:
    text = f"{request.query} {request.city}"
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh-CN"
    return "en"


def _best_matching_place(
    places: list[Any],
    *,
    title: str,
    address: str,
    lat: float | None,
    lng: float | None,
) -> dict[str, Any] | None:
    candidates = [place for place in places if isinstance(place, dict)]
    scored = [(_match_score(place, title=title, address=address, lat=lat, lng=lng), place) for place in candidates]
    scored = [(score, place) for score, place in scored if score >= 3.0]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _match_score(
    place: dict[str, Any],
    *,
    title: str,
    address: str,
    lat: float | None,
    lng: float | None,
) -> float:
    score = 0.0
    display = _display_name(place)
    normalized_title = _normalize_text(title)
    normalized_display = _normalize_text(display)
    if normalized_title and normalized_display:
        if normalized_title in normalized_display or normalized_display in normalized_title:
            score += 4.0
        score += min(3.0, len(_tokens(normalized_title) & _tokens(normalized_display)))
    normalized_address = _normalize_text(address)
    normalized_place_address = _normalize_text(str(place.get("formattedAddress") or ""))
    if normalized_address and normalized_place_address:
        score += min(2.0, len(_tokens(normalized_address) & _tokens(normalized_place_address)))
    distance = _distance_meters(lat, lng, _place_lat(place), _place_lng(place))
    if distance is not None:
        if distance <= 600:
            score += 5.0
        elif distance <= 1200:
            score += 3.0
    return score


def _display_name(place: dict[str, Any]) -> str:
    display = place.get("displayName")
    if isinstance(display, dict):
        return str(display.get("text") or "").strip()
    return str(display or "").strip()


def _place_lat(place: dict[str, Any]) -> float | None:
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    return _float_or_none(location.get("latitude"))


def _place_lng(place: dict[str, Any]) -> float | None:
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    return _float_or_none(location.get("longitude"))


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _distance_meters(
    lat1: float | None,
    lng1: float | None,
    lat2: float | None,
    lng2: float | None,
) -> float | None:
    if None in {lat1, lng1, lat2, lng2}:
        return None
    radius = 6371000.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _photo_attributions(photo: dict[str, Any]) -> list[str]:
    values: list[str] = []
    attributions = photo.get("authorAttributions")
    if isinstance(attributions, list):
        for attribution in attributions:
            if isinstance(attribution, dict):
                text = str(
                    attribution.get("displayName")
                    or attribution.get("uri")
                    or ""
                ).strip()
                if text:
                    values.append(text)
    return values


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]+", value) if token}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if value]))
