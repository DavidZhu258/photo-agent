from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas.visual import PlaceCandidate


@dataclass(frozen=True)
class RouteEstimate:
    used: bool
    minutes: float | None = None
    source: str = "none"
    warning: str | None = None


class RouteEstimator:
    """OSRM-first route estimator with a deterministic distance fallback."""

    def __init__(
        self,
        osrm_base_url: str | None = None,
        timeout_seconds: float = 1.5,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.osrm_base_url = osrm_base_url.rstrip("/") if osrm_base_url else None
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def estimate(
        self,
        origin: dict[str, float] | None,
        place: PlaceCandidate,
        transport_mode: str = "walking",
    ) -> RouteEstimate:
        if (
            not origin
            or "lat" not in origin
            or "lng" not in origin
            or place.lat is None
            or place.lng is None
        ):
            return RouteEstimate(used=False)
        if self.osrm_base_url:
            estimate = await self._estimate_osrm(origin, place, transport_mode)
            if estimate.used:
                return estimate
        minutes = _fallback_minutes(origin, place, transport_mode)
        return RouteEstimate(used=True, minutes=minutes, source="haversine")

    async def _estimate_osrm(
        self,
        origin: dict[str, float],
        place: PlaceCandidate,
        transport_mode: str,
    ) -> RouteEstimate:
        profile = "walking" if transport_mode == "walking" else "driving"
        url = (
            f"{self.osrm_base_url}/route/v1/{profile}/"
            f"{origin['lng']},{origin['lat']};{place.lng},{place.lat}"
        )
        try:
            response = await self.http_client.get(url, params={"overview": "false"})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            routes = payload.get("routes")
            if not isinstance(routes, list) or not routes:
                return RouteEstimate(used=False)
            duration = routes[0].get("duration")
            if not isinstance(duration, int | float):
                return RouteEstimate(used=False)
            return RouteEstimate(
                used=True,
                minutes=round(float(duration) / 60, 1),
                source="osrm",
            )
        except Exception as exc:
            return RouteEstimate(
                used=False,
                warning=f"OSRM 路线估算失败：{exc.__class__.__name__}",
            )


def _fallback_minutes(
    origin: dict[str, float],
    place: PlaceCandidate,
    transport_mode: str,
) -> float:
    km = _haversine_km(
        origin["lat"],
        origin["lng"],
        float(place.lat),
        float(place.lng),
    )
    speed_kmh = 4.5 if transport_mode == "walking" else 24.0
    return round((km / speed_kmh) * 60, 1)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
