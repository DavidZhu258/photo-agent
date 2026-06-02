from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse


COMMERCIAL_DOMAINS = {
    "booking.com",
    "agoda.com",
    "airbnb.com",
    "expedia.com",
    "getyourguide.com",
    "hotels.com",
    "klook.com",
    "tripadvisor.com",
    "viator.com",
    "yelp.com",
}

LOW_RISK_DOMAINS = {
    "reddit.com",
    "tabiji.ai",
    "wikivoyage.org",
    "wikimedia.org",
    "wikidata.org",
    "openstreetmap.org",
    "opentripmap.org",
}

COMMERCIAL_TERMS = {
    "affiliate",
    "book now",
    "booking link",
    "discount code",
    "limited deal",
    "promo",
    "private tour",
    "sponsored",
    "tickets from",
}

SEO_TERMS = {"best ", "top ", "2026", "must-visit", "bucket list"}


def ad_risk_score(
    *,
    url: str = "",
    title: str = "",
    snippet: str = "",
    provenance: Iterable[str] | None = None,
    base_risk: float = 0.18,
) -> float:
    """Score source-level commercial risk without claiming proof of an ad."""

    domain = urlparse(url).netloc.lower()
    text = f"{title} {snippet}".lower()
    provenance_text = " ".join(str(item).lower() for item in provenance or [])
    risk = base_risk
    if any(domain.endswith(item) or item in domain for item in LOW_RISK_DOMAINS):
        risk = min(risk, 0.08)
    if any(domain.endswith(item) or item in domain for item in COMMERCIAL_DOMAINS):
        risk = max(risk, 0.72)
    if any(term in provenance_text for term in ["affiliate", "booking", "sponsor"]):
        risk = max(risk, 0.72)
    if any(term in text for term in COMMERCIAL_TERMS):
        risk = max(risk, 0.65)
    if any(term in text for term in SEO_TERMS):
        risk = max(risk, 0.32)
    return round(min(risk, 0.95), 3)


def is_commercially_risky(
    *,
    url: str = "",
    title: str = "",
    snippet: str = "",
    provenance: Iterable[str] | None = None,
    threshold: float = 0.65,
) -> bool:
    return (
        ad_risk_score(
            url=url,
            title=title,
            snippet=snippet,
            provenance=provenance,
        )
        >= threshold
    )
