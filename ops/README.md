# Local OSS Services

This folder contains local-only configuration for the open-source runtime stack.
Files ending in `.local.env` contain local secrets and are ignored by git.

## Services

- Redis app cache: `127.0.0.1:6379`
- LiteLLM proxy: `http://127.0.0.1:4000/v1`
- Langfuse UI: `http://127.0.0.1:3300`
- Langfuse MinIO console: `http://127.0.0.1:9091`
- Langfuse Postgres: `127.0.0.1:5432`

MySQL is still defined in the root compose file, but do not start it if local
port `3306` is already occupied.

## Start

```powershell
docker compose up -d redis litellm
docker compose up -d langfuse-postgres langfuse-clickhouse langfuse-minio langfuse-redis langfuse-worker langfuse-web
```

## Verify

```powershell
docker exec photo-agent-redis redis-cli ping
Invoke-RestMethod http://127.0.0.1:4000/health/liveliness
Invoke-WebRequest http://127.0.0.1:3300
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"
```

## Deployment Smoke

The self-hosted deployment is expected to run through Nginx, with Next.js and
FastAPI private to the host. Keep concrete deployment addresses out of the
open-source docs and pass them as command-line parameters.

Run the reliability smoke from Windows PowerShell:

```powershell
.\ops\server-smoke.ps1 -BaseUrl "https://your-domain.example" -SshTarget "user@host.example"
```

The smoke checks:

- PM2 has `photo-agent-backend` and `photo-agent-web` online.
- Docker runtime services include LiteLLM, Redis, Langfuse, and ClickHouse.
- Public `GET /`, `GET /visual`, backend health, and visual discovery contract are healthy.
- `POST /api/travel/chat` works for answer-only knowledge and place-card recommendation.
- `POST /api-backend/v1/visual/discover` returns the visual contract with one-line answer and three deep cards.

For a faster route-only check while debugging:

```powershell
.\ops\server-smoke.ps1 -SkipVisualPost
```

## Backend Runtime

The backend reads `backend/.env`. The default travel runtime uses a small set of
external token surfaces:

```text
VLM_PROVIDER=deepinfra
TRAVEL_MAIN_API_KEY=...
TRAVEL_MAIN_BASE_URL=https://zzshu.cc/v1
DEEPINFRA_API_KEY=...
SERPER_API_KEY=...
REDIS_URL=redis://127.0.0.1:6379/0
LANGFUSE_HOST=http://127.0.0.1:3300
```

Travel's main answer model calls the OpenAI-compatible main gateway directly.
The default travel path is `TRAVEL_ORCHESTRATION_MODE=orchestrator`: one
GPT-level manager model owns the answer and calls bounded Serper/map/route
tools only when needed. Google-style travel data defaults to Serper.dev
Search/Places/Images. LiteLLM, direct Google Places, and SerpAPI remain legacy/local compatibility paths and
are ignored unless explicitly enabled with `TRAVEL_ALLOW_LITELLM_FALLBACK=true`,
`TRAVEL_ALLOW_DIRECT_GOOGLE_PLACES=true`, or `TRAVEL_ALLOW_SERPAPI_FALLBACK=true`.

Default model settings:

- `TRAVEL_MODEL_ORCHESTRATOR=gpt-5.5`
- `TRAVEL_MODEL_COMPLEX_ROUTE=openai/gpt-oss-120b`
- `TRAVEL_MODEL_FAST=deepseek-ai/DeepSeek-V4-Flash`
- `DEEPINFRA_VISION_MODEL=google/gemini-3.1-pro`

LiteLLM still keeps compatible local aliases for experiments:

- `mistralai/Mistral-Small-3.2-24B-Instruct-2506`
- `google/gemma-4-26B-A4B-it`
- `travel-orchestrator` / `travel-complex-route` -> `deepinfra/openai/gpt-oss-120b`
- `travel-router` / `travel-router-fast` -> `deepinfra/deepseek-ai/DeepSeek-V4-Flash`
- `travel-fast` -> `deepinfra/deepseek-ai/DeepSeek-V4-Flash`
- `travel-reasoning` / `travel-formatter` -> `deepinfra/openai/gpt-oss-120b`
- `travel-critic` -> `deepinfra/openai/gpt-oss-120b`

LiteLLM is also configured with Langfuse success/failure callbacks for local
experiments.

## Resource Notes

This machine has about 8 GB RAM available to Docker. The compose file keeps
model inference on DeepInfra API and only runs orchestration/cache/trace
services locally. If Langfuse becomes too heavy, stop the local Langfuse stack
and point `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` to
Langfuse Cloud/API instead.
