# Photo Agent Backend

FastAPI backend for the P0 visual exploration flow.

## Design

- `app.services.agent.VisualExploreAgent` is the explicit lightweight workflow.
- `app.services.ranking.RecommendationRanker` scores recommendations without ads.
- `app.services.importer.EvidenceImporter` imports curated evidence into a repository.
- `app.services.travel_planner.LightweightTravelPlanner` ranks travel decisions with
  transparent evidence and deterministic scoring.
- `app.services.exa_search.EvidenceSearchService` performs on-demand Exa evidence
  search when local MySQL evidence is insufficient or an admin forces refresh.
- `app.services.travel_api_sources.TrustedTravelSuggestionService` uses Tabiji/API
  candidates for generic category suggestions and filters commercial sources.
- `app.services.travel_recommendation_supervisor.TravelRecommendationSupervisor`
  now defaults to a GPT-level Travel Orchestrator that owns intent, tool choice,
  and final answer style. Specialist reasoning remains available as bounded
  tools for complex routes, inventory checks, visual context, and verification.
- `app.services.serper_travel.SerperTravelClient` adapts Serper.dev Search/Places
  APIs to the supervisor. Serper is preferred when `SERPER_API_KEY` is set, and
  it now supplies budget, transport, and optional visa/weather/safety searches.
- `app.services.ad_filter` scores booking, affiliate, sponsored, and SEO-like
  sources so they can be excluded or demoted before ranking.
- `app.services.routing.RouteEstimator` uses OSRM when configured and falls back
  to deterministic distance estimates.
- `app.db.models` and Alembic define the MySQL 8 schema, including CJK ngram
  full-text indexes for aliases and evidence text.
- Admin endpoints require `X-Admin-Token`, matching `ADMIN_TOKEN`.

## Local Run

```powershell
pip install -e ".[dev]"
docker compose up -d mysql
alembic upgrade head
uvicorn app.main:app --reload
```

Set a local admin token for the web companion and import endpoints:

```powershell
$env:ADMIN_TOKEN='photo-agent-local-admin'
```

Optional travel suggestion, evidence, and routing integrations:

```powershell
$env:TABIJI_ENABLED='true'
$env:EXA_API_KEY='your-exa-token'
$env:SERPER_API_KEY='your-serper-token'
$env:SERPER_BASE_URL='https://google.serper.dev'
$env:OSRM_BASE_URL='http://127.0.0.1:5000'
```

Serper supplies live Search/Places candidates for the AI recommendation
supervisor. Budget and local transport are always queried when Serper is
available; visa, weather, and safety are queried only when the user asks for
those topics. Tabiji remains available for older generic category suggestions.
Exa is only called for travel evidence gaps or manual admin search. The default
test suite mocks or disables external calls.

## Local OSS Runtime

Runtime services are configured at the workspace root:

```powershell
docker compose up -d redis litellm
docker compose up -d langfuse-postgres langfuse-clickhouse langfuse-minio langfuse-redis langfuse-worker langfuse-web
```

`backend/.env` should keep the production token surface small:

- `SERPER_API_KEY` for Google Search/Places/Images style travel data.
- `TRAVEL_MAIN_API_KEY` for the travel main model through the OpenAI-compatible API.
- `DEEPINFRA_API_KEY` for visual model calls and non-main travel compatibility paths.
- `REDIS_URL` for cache.

Default travel orchestration:

- `TRAVEL_ORCHESTRATION_MODE=orchestrator`
- `TRAVEL_MAIN_BASE_URL=https://zzshu.cc/v1`
- `TRAVEL_MODEL_ORCHESTRATOR=gpt-5.5`
- `TRAVEL_MODEL_COMPLEX_ROUTE=openai/gpt-oss-120b`
- `DEEPINFRA_VISION_MODEL=google/gemini-3.1-pro`
- `TRAVEL_ORCHESTRATOR_MAX_TOOL_ROUNDS=6`
- `TRAVEL_COMPLEX_MAX_TOOL_ROUNDS=10`

LiteLLM, direct Google Places, and SerpAPI are legacy/local compatibility paths
and are ignored by default for travel unless explicitly enabled with
`TRAVEL_ALLOW_LITELLM_FALLBACK=true`, `TRAVEL_ALLOW_DIRECT_GOOGLE_PLACES=true`,
or `TRAVEL_ALLOW_SERPAPI_FALLBACK=true`.

## Chainlit Web UI

The first P0 Web surface is Chainlit, not the old Next.js companion:

```powershell
$env:PHOTO_AGENT_API_BASE_URL='http://127.0.0.1:8768'
python -m chainlit run ..\chainlit_app\app.py --host 127.0.0.1 --port 3101
```

The UI calls `POST /v1/travel/plan`, streams the final Markdown answer, and
shows visible steps for the GPT orchestrator plus Serper/DeepInfra bounded tool
calls. It does not expose hidden chain-of-thought.

## DeepInfra Vision + Narrative

```powershell
$env:VLM_PROVIDER='deepinfra'
$env:DEEPINFRA_API_KEY='your-token'
$env:DEEPINFRA_VISION_MODEL='mistralai/Mistral-Small-3.2-24B-Instruct-2506'
$env:DEEPINFRA_NARRATIVE_MODEL='google/gemma-4-26B-A4B-it'
$env:TRAVEL_DECISION_TIMEOUT_SECONDS='20'
uvicorn app.main:app --reload
```

The DeepInfra client uses OpenAI-compatible chat completions. The vision call
can send multiple base64 images as `image_url` content blocks, then the
narrative call turns visible clues, evidence, support, and counter-evidence into
a Chinese story-style answer. OCR is only optional context now; it no longer
short-circuits the visual reasoning flow.

## Test

```powershell
$env:PYTHONPATH='.'
python -m pytest -q
```

Run the live DeepInfra smoke test only when you explicitly want to spend API
credits:

```powershell
$env:RUN_DEEPINFRA_LIVE='1'
$env:DEEPINFRA_API_KEY='your-token'
python -m pytest tests/test_deepinfra_live.py -q
```
