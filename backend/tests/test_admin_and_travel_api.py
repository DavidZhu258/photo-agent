from fastapi.testclient import TestClient
import asyncio
import time

from app.config import Settings
from app.main import create_app
from app.schemas.imports import EvidenceImportSummary
from app.schemas.travel import TravelPlanResponse
from app.services.travel_planner import LightweightTravelPlanner


class FakeImporter:
    async def import_items(self, items):
        assert items[0].place_name == "Shoren-in Monzeki"
        return EvidenceImportSummary(
            places_upserted=1,
            aliases_created=2,
            evidence_created=len(items),
        )


class SlowTravelPlanner:
    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, payload):
        self.calls += 1
        await asyncio.sleep(0.05)
        return TravelPlanResponse(
            summary=f"后台完成：{payload.question or payload.query}",
            needs_user_confirmation=False,
        )


def test_admin_import_requires_local_admin_token():
    app = create_app(
        evidence_importer=FakeImporter(),
        app_settings=Settings(admin_token="local-secret"),
    )
    client = TestClient(app)
    payload = [
        {
            "place_name": "Shoren-in Monzeki",
            "place_name_ja": "青蓮院門跡",
            "city": "Kyoto",
            "category": "temple",
            "source_type": "reddit",
            "source_name": "r/JapanTravel",
            "title": "Quiet temple",
            "snippet": "Calm garden stop near Higashiyama.",
        }
    ]

    missing = client.post("/v1/admin/import-evidence", json=payload)
    wrong = client.post(
        "/v1/admin/import-evidence",
        json=payload,
        headers={"X-Admin-Token": "wrong"},
    )
    ok = client.post(
        "/v1/admin/import-evidence",
        json=payload,
        headers={"X-Admin-Token": "local-secret"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["evidence_created"] == 1


def test_admin_places_returns_seeded_places_and_evidence():
    app = create_app(app_settings=Settings(admin_token="local-secret"))
    client = TestClient(app)

    response = client.get(
        "/v1/admin/places",
        headers={"X-Admin-Token": "local-secret"},
    )
    detail = client.get(
        "/v1/admin/places/1",
        headers={"X-Admin-Token": "local-secret"},
    )

    assert response.status_code == 200
    assert response.json()["places"][0]["name_ja"] == "青蓮院門跡"
    assert detail.status_code == 200
    assert detail.json()["place"]["place_id"] == 1
    assert detail.json()["evidence_cards"][0]["source_type"] == "official"


def test_travel_plan_returns_ranked_recommendations_with_evidence():
    app = create_app(travel_planner=LightweightTravelPlanner())
    client = TestClient(app)

    response = client.post(
        "/v1/travel/plan",
        json={
            "city": "Kyoto",
            "arrive_at": "2026-05-15T12:00:00+09:00",
            "question": "我下午到京都，想避开游客，有没有值得深入看的地方？",
            "interest_tags": ["quiet", "garden", "history"],
            "constraints": ["avoid crowds"],
            "fixed_itinerary": ["next day Osaka"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "透明推荐" in body["summary"]
    assert body["recommendations"][0]["place"]["name_ja"] == "青蓮院門跡"
    assert body["recommendations"][0]["evidence_cards"][0]["source_type"] == "official"
    assert body["recommendations"][0]["ad_risk_label"] == "低"
    assert body["needs_user_confirmation"] is False


def test_travel_plan_allows_local_web_companion_cors_preflight():
    app = create_app()
    client = TestClient(app)

    response = client.options(
        "/v1/travel/plan",
        headers={
            "Origin": "http://127.0.0.1:3101",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3101"


def test_travel_job_can_be_polled_after_original_client_disconnects():
    planner = SlowTravelPlanner()
    app = create_app(travel_planner=planner)
    with TestClient(app) as client:
        created = client.post(
            "/v1/travel/jobs",
            json={
                "city": "Fukuoka",
                "question": "福冈有什么好玩的？",
                "allow_web_search": True,
            },
        )

        assert created.status_code == 202
        job = created.json()
        assert job["status"] in {"queued", "running"}
        assert job["job_id"]

        deadline = time.monotonic() + 2
        status = None
        while time.monotonic() < deadline:
            polled = client.get(f"/v1/travel/jobs/{job['job_id']}")
            assert polled.status_code == 200
            status = polled.json()
            if status["status"] == "completed":
                break
            time.sleep(0.05)

    assert status is not None
    assert status["status"] == "completed"
    assert status["response"]["summary"] == "后台完成：福冈有什么好玩的？"
    assert planner.calls == 1
