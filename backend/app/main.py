from __future__ import annotations

import base64
from binascii import Error as Base64Error

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db.mysql_repository import MySqlEvidenceRepository
from app.db.session import SessionLocal, get_session
from app.schemas.travel import (
    EvidenceSearchRequest,
    TravelPlanJobCreateResponse,
    TravelPlanJobStatusResponse,
    TravelPlanRequest,
    TravelPlanResponse,
)
from app.schemas.visual import (
    ClientOcr,
    FollowupRequest,
    FollowupResponse,
    VisualExploreApiRequest,
    VisualExploreInput,
    VisualExploreResponse,
    VisualFollowupApiRequest,
    VisualFollowupInput,
    VisualFollowupResponse,
)
from app.schemas.imports import EvidenceImportItem, EvidenceImportSummary
from app.services.agent import VisualExploreAgent, build_visual_agent
from app.services.importer import EvidenceImporter
from app.services.exa_search import EvidenceSearchService, ExaSearchClient
from app.services.open_source_stack import attach_visual_metadata
from app.services.place_catalog import MySqlPlaceCatalog, SeedPlaceCatalog
from app.services.travel_planner import LightweightTravelPlanner, build_travel_planner
from app.services.travel_query_understanding import TravelModelCallError
from app.services.travel_jobs import TravelJobManager


def create_app(
    agent: VisualExploreAgent | object | None = None,
    evidence_importer: EvidenceImporter | None = None,
    app_settings: Settings = settings,
    place_catalog: SeedPlaceCatalog | None = None,
    travel_planner: LightweightTravelPlanner | None = None,
    evidence_search: object | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Photo Agent API",
        version="0.1.0",
        description="P0 visual exploration API with MySQL-ready lightweight orchestration.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "http://localhost:3101",
            "http://127.0.0.1:3101",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    visual_agent = agent or build_visual_agent()
    catalog = place_catalog or SeedPlaceCatalog()
    search_service = evidence_search or EvidenceSearchService(
        ExaSearchClient(
            api_key=app_settings.exa_api_key,
            base_url=app_settings.exa_base_url,
            timeout_seconds=app_settings.exa_timeout_seconds,
        )
    )
    planner_search = (
        search_service if evidence_search is not None or app_settings.exa_api_key else None
    )
    planner = travel_planner or build_travel_planner(
        app_settings=app_settings,
        place_catalog=catalog,
        evidence_search=planner_search,
    )
    travel_jobs = TravelJobManager()

    async def require_admin_token(
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> None:
        if x_admin_token == app_settings.admin_token:
            return
        raise HTTPException(status_code=401, detail="Invalid admin token")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def run_visual_explore(
        payload: VisualExploreApiRequest,
    ) -> VisualExploreResponse:
        encoded_images = []
        if payload.image_base64:
            encoded_images.append(payload.image_base64)
        encoded_images.extend(payload.images_base64)
        if not encoded_images and not payload.image_url:
            raise HTTPException(
                status_code=400,
                detail="At least one image or image_url is required",
            )

        try:
            images_bytes = [
                base64.b64decode(image_base64, validate=True)
                for image_base64 in encoded_images
            ]
        except (Base64Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid image_base64") from exc

        request = VisualExploreInput(
            image_url=payload.image_url,
            image_bytes=images_bytes[0] if images_bytes else b"",
            images_bytes=images_bytes,
            gps_lat=payload.gps_lat,
            gps_lng=payload.gps_lng,
            heading_degrees=payload.heading_degrees,
            captured_at=payload.captured_at,
            client_ocr=ClientOcr(
                text=payload.client_ocr_text,
                translated_text=payload.client_ocr_translated_text,
                language=payload.client_ocr_language,
            ),
            interest_tags=payload.interest_tags,
            user_context_text=payload.user_context_text,
            exploration_focus=payload.exploration_focus,
        )
        response = await visual_agent.explore(request)
        return attach_visual_metadata(response, request, cache_key=payload.image_url or "api")

    def visual_images_from_payload(
        image_base64: str | None,
        images_base64: list[str],
    ) -> list[bytes]:
        encoded_images = []
        if image_base64:
            encoded_images.append(image_base64)
        encoded_images.extend(images_base64)
        try:
            return [
                base64.b64decode(value, validate=True)
                for value in encoded_images
            ]
        except (Base64Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid image_base64") from exc

    @app.post("/v1/visual/explore", response_model=VisualExploreResponse)
    async def visual_explore(payload: VisualExploreApiRequest) -> VisualExploreResponse:
        return await run_visual_explore(payload)

    @app.post("/v1/visual/discover", response_model=VisualExploreResponse)
    async def visual_discover(payload: VisualExploreApiRequest) -> VisualExploreResponse:
        return await run_visual_explore(payload)

    @app.post("/v1/visual/followup", response_model=VisualFollowupResponse)
    async def visual_followup(payload: VisualFollowupApiRequest) -> VisualFollowupResponse:
        if not payload.question.strip():
            raise HTTPException(status_code=400, detail="question is required")
        images_bytes = visual_images_from_payload(payload.image_base64, payload.images_base64)
        request = VisualFollowupInput(
            session_id=payload.session_id,
            question=payload.question,
            image_url=payload.image_url,
            image_bytes=images_bytes[0] if images_bytes else b"",
            images_bytes=images_bytes,
            previous_result=payload.previous_result,
            interest_tags=payload.interest_tags,
            user_context_text=payload.user_context_text,
            exploration_focus=payload.exploration_focus,
        )
        followup = getattr(visual_agent, "followup", None)
        if not callable(followup):
            raise HTTPException(status_code=501, detail="visual follow-up is not available")
        return await followup(request)

    @app.get("/v1/visual/discover")
    async def visual_discover_info() -> dict[str, object]:
        return {
            "status": "ready",
            "method": "POST",
            "web_ui": "http://127.0.0.1:3101/visual",
            "required": "image_base64, images_base64, or image_url",
        }

    @app.post("/v1/chat/followup", response_model=FollowupResponse)
    async def chat_followup(payload: FollowupRequest) -> FollowupResponse:
        return FollowupResponse(
            session_id=payload.session_id,
            answer="P0 follow-up uses the saved snap session context; connect MySQL repositories to enable persisted evidence recall.",
            evidence_cards=[],
        )

    @app.get("/v1/places/{place_id}")
    async def get_place(place_id: int) -> dict[str, object]:
        place = await catalog.get_place(place_id)
        if place is None:
            raise HTTPException(status_code=404, detail="Place not found")
        return {
            "place": place,
            "evidence_cards": await catalog.evidence_for(place.place_id),
        }

    @app.get("/v1/admin/places", dependencies=[Depends(require_admin_token)])
    async def admin_places(q: str | None = None) -> dict[str, object]:
        return {"places": await catalog.list_places(query=q)}

    @app.get("/v1/admin/places/{place_id}", dependencies=[Depends(require_admin_token)])
    async def admin_place_detail(place_id: int) -> dict[str, object]:
        place = await catalog.get_place(place_id)
        if place is None:
            raise HTTPException(status_code=404, detail="Place not found")
        return {
            "place": place,
            "evidence_cards": await catalog.evidence_for(place.place_id),
        }

    @app.get("/v1/admin/search", dependencies=[Depends(require_admin_token)])
    async def admin_search(q: str = "", city: str | None = None) -> dict[str, object]:
        return {"places": await catalog.search(query=q, city=city)}

    async def run_travel_plan(
        payload: TravelPlanRequest,
        session: Session | None = None,
    ) -> TravelPlanResponse:
        if travel_planner is not None:
            return await planner.plan(payload)
        should_close_session = session is None
        runtime_session = session or SessionLocal()
        try:
            runtime_catalog = (
                catalog
                if place_catalog is not None
                else MySqlPlaceCatalog(session=runtime_session, fallback=catalog)
            )
            runtime_planner = build_travel_planner(
                app_settings=app_settings,
                place_catalog=runtime_catalog,
                evidence_search=planner_search,
            )
            return await runtime_planner.plan(payload)
        finally:
            if should_close_session:
                runtime_session.close()

    @app.post("/v1/travel/plan", response_model=TravelPlanResponse)
    async def travel_plan(
        payload: TravelPlanRequest,
        session: Session = Depends(get_session),
    ) -> TravelPlanResponse:
        try:
            return await run_travel_plan(payload, session=session)
        except TravelModelCallError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "error_type": "travel_model_call_failed",
                    "failed_stage": exc.stage,
                    "model": exc.model,
                    "message": exc.message,
                },
            ) from exc

    @app.post(
        "/v1/travel/jobs",
        response_model=TravelPlanJobCreateResponse,
        status_code=202,
    )
    async def create_travel_job(payload: TravelPlanRequest) -> TravelPlanJobCreateResponse:
        record = travel_jobs.start(lambda: run_travel_plan(payload))
        return TravelPlanJobCreateResponse(
            job_id=record.job_id,
            status=record.status,
            poll_url=f"/v1/travel/jobs/{record.job_id}",
            created_at=record.created_at,
        )

    @app.get("/v1/travel/jobs/{job_id}", response_model=TravelPlanJobStatusResponse)
    async def travel_job_status(job_id: str) -> TravelPlanJobStatusResponse:
        record = travel_jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Travel job not found")
        return TravelPlanJobStatusResponse(
            job_id=record.job_id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            response=record.response,
            error=record.error,
        )

    @app.post("/v1/admin/evidence/search-exa", dependencies=[Depends(require_admin_token)])
    async def admin_search_exa(payload: EvidenceSearchRequest) -> dict[str, object]:
        return await search_service.search(payload, trigger_reason=payload.trigger_reason)

    @app.get("/v1/admin/evidence/search-runs", dependencies=[Depends(require_admin_token)])
    async def admin_search_runs() -> dict[str, object]:
        runs = []
        if hasattr(search_service, "list_runs"):
            runs = await search_service.list_runs()
        return {"runs": runs}

    @app.get(
        "/v1/admin/places/{place_id}/evidence",
        dependencies=[Depends(require_admin_token)],
    )
    async def admin_place_evidence(place_id: int) -> dict[str, object]:
        place = await catalog.get_place(place_id)
        if place is None:
            raise HTTPException(status_code=404, detail="Place not found")
        return {
            "place": place,
            "evidence_cards": await catalog.evidence_for(place.place_id),
        }

    @app.post("/v1/admin/import-evidence", response_model=EvidenceImportSummary)
    async def import_evidence(
        items: list[EvidenceImportItem],
        _: None = Depends(require_admin_token),
        session: Session = Depends(get_session),
    ) -> EvidenceImportSummary:
        if evidence_importer is not None:
            return await evidence_importer.import_items(items)
        importer = EvidenceImporter(MySqlEvidenceRepository(session))
        return await importer.import_items(items)

    return app


app = create_app()
