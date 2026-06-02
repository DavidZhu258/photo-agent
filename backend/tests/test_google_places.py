from __future__ import annotations

import json

import httpx
import pytest

from app.schemas.travel import TravelPlanRequest
from app.services.google_places import GooglePlacesClient


@pytest.mark.asyncio
async def test_google_places_client_resolves_text_search_and_photo_media():
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "field_mask": request.headers.get("X-Goog-FieldMask"),
                "body": request.content.decode("utf-8") if request.content else "",
            }
        )
        if request.url.path == "/v1/places:searchText":
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "id": "ChIJGoogleOhori",
                            "displayName": {"text": "大濠公园"},
                            "formattedAddress": "1 Ohorikoen, Chuo Ward, Fukuoka",
                            "location": {"latitude": 33.5862, "longitude": 130.3765},
                            "rating": 4.5,
                            "userRatingCount": 8000,
                            "googleMapsUri": "https://maps.google.com/?cid=ohori",
                            "photos": [
                                {
                                    "name": "places/ChIJGoogleOhori/photos/photo-one",
                                    "authorAttributions": [
                                        {"displayName": "Google Local Guide"}
                                    ],
                                }
                            ],
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/v1/places/ChIJGoogleOhori/photos/photo-one/media":
            return httpx.Response(
                200,
                json={"photoUri": "https://lh3.googleusercontent.com/ohori-photo"},
                request=request,
            )
        return httpx.Response(404, json={}, request=request)

    client = GooglePlacesClient(
        api_key="google-test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.resolve_place(
        request=TravelPlanRequest(city="Fukuoka", query="福冈有什么好玩的?"),
        title="大濠公园",
        address="Ohorikoen, Fukuoka",
        lat=33.58621,
        lng=130.37646,
    )

    assert result is not None
    assert result["place_id"] == "ChIJGoogleOhori"
    assert result["title"] == "大濠公园"
    assert result["lat"] == 33.5862
    assert result["lng"] == 130.3765
    assert result["rating"] == 4.5
    assert result["review_count"] == 8000
    assert result["google_maps_uri"] == "https://maps.google.com/?cid=ohori"
    assert result["image_urls"] == ["https://lh3.googleusercontent.com/ohori-photo"]
    assert result["photo_attributions"] == ["Google Local Guide"]
    assert calls[0]["method"] == "POST"
    assert calls[0]["field_mask"]
    assert "places.photos" in str(calls[0]["field_mask"])
    assert json.loads(str(calls[0]["body"]))["textQuery"] == "大濠公园 Ohorikoen, Fukuoka Fukuoka"
    assert calls[1]["method"] == "GET"
    assert "skipHttpRedirect=true" in str(calls[1]["url"])


@pytest.mark.asyncio
async def test_google_places_client_rejects_low_match_result():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJWrongPlace",
                        "displayName": {"text": "Completely Different Cafe"},
                        "formattedAddress": "Tokyo",
                        "location": {"latitude": 35.68, "longitude": 139.76},
                        "googleMapsUri": "https://maps.google.com/?cid=wrong",
                    }
                ]
            },
            request=request,
        )

    client = GooglePlacesClient(
        api_key="google-test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.resolve_place(
        request=TravelPlanRequest(city="Fukuoka", query="福冈有什么好玩的?"),
        title="大濠公园",
        address="Ohorikoen, Fukuoka",
        lat=33.58621,
        lng=130.37646,
    )

    assert result is None
