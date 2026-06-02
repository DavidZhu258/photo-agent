# Gemini Visual-First Lens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `photo_agent` visual discovery into a Gemini 3.1 Pro visual-first, Chance AI-style Web experience focused on one-photo exploration, expert perspectives, visual memory, and landmark validation in Fukuoka/Kyushu and Kansai.

**Architecture:** Keep the existing FastAPI `/v1/visual/discover` and Next.js `/visual` entrypoints. Use DeepInfra's OpenAI-compatible Gemini proxy for primary visual reasoning, then run selected expert perspectives, narrative, and memory rendering. Keep direct Google Gemini and heuristic clients as optional fallbacks.

**Tech Stack:** FastAPI, Pydantic, httpx or `google-genai`, Redis cache, LiteLLM fallback, Next.js, TypeScript, Tailwind, Playwright, pytest.

---

## Current State

- Backend already has `VisualExploreAgent`, `VisualExploreInput`, `VisualExploreResponse`, `/v1/visual/discover`, Redis cache, DeepInfra VLM, heuristic fallback, seeded evidence, and Web `/visual`.
- Current output already includes `story_title`, `narrative`, `visible_clues`, `cultural_hypotheses`, `meaning_layers`, `knowledge_cards`, `thinking_steps`, and `cache`.
- Missing pieces for the requested target: Gemini 3.1 Pro client, expert perspective cards, explicit visual workflow trace, visual memory contract, audio script, and Japan-focused golden landmark tests.

## Model and API Decision

- Primary visual model: `google/gemini-3.1-pro` through DeepInfra.
- Primary integration: DeepInfra OpenAI-compatible endpoint `https://api.deepinfra.com/v1/openai`.
- Required config:
  - `VLM_PROVIDER=deepinfra`
  - `DEEPINFRA_BASE_URL=https://api.deepinfra.com/v1/openai`
  - `DEEPINFRA_VISION_MODEL=google/gemini-3.1-pro`
  - `DEEPINFRA_NARRATIVE_MODEL=google/gemini-3.1-flash-lite`
- Fallback:
  - Direct Google Gemini remains available through `VISUAL_PRIMARY_PROVIDER=gemini` plus `GOOGLE_API_KEY` if needed later.
  - `HeuristicVlmClient` remains the no-key local fallback.
- Rationale:
  - DeepInfra's Gemini family page lists `google/gemini-3.1-pro` and documents OpenAI-compatible access using the DeepInfra token and base URL.
  - This avoids adding a separate Google API key or Vertex setup while still using Gemini for visual-first reasoning.
  - Direct Google Gemini is kept as an optional adapter for cases that require Google-specific parameters such as `thinking_level` or `media_resolution`.

## Response Contract Additions

Extend `VisualExploreResponse` without removing current fields:

```python
class PerspectiveCard(BaseModel):
    perspective: str  # guide | history | culture | art_critic | style | map_linker
    title: str
    summary: str
    reasons: list[str]
    confidence: float
    followup_prompt: str | None = None

class VisualMemoryItem(BaseModel):
    memory_id: str
    title: str
    entity_type: str
    region_hint: str | None = None
    thumbnail_sha256: str | None = None
    status: str = "discovered"  # discovered | saved | rejected | planned

class VisualWorkflowSummary(BaseModel):
    provider: str
    model: str
    selected_perspectives: list[str]
    knowledge_used: bool
    confidence: float
    uncertainty: list[str]
```

New response fields:

```python
perspective_cards: list[PerspectiveCard]
visual_memory_item: VisualMemoryItem | None
audio_script: str
visual_workflow_summary: VisualWorkflowSummary
```

Frontend must never display hidden chain-of-thought or debug logs. It may display visible clues, selected perspectives, sources, uncertainty, and workflow summary.

## Visual Workflow

Implement a bounded workflow; do not build an autonomous open-ended agent loop.

1. `image_ingest`
   - Accept one image by default; allow up to four images.
   - Compute image hash and cache key using existing image/context cache behavior.
2. `gemini_visual_reasoning`
   - Ask Gemini for strict JSON: subject, canonical landmark name if applicable, place candidates, visible clues, cultural hypotheses, meaning layers, confidence, uncertainty, and suggested perspectives.
   - Use `thinking_level=HIGH` and high media resolution for Japan landmark and architecture cases.
3. `perspective_router`
   - Select 2-4 perspectives from: guide, history, culture, art_critic, style, map_linker.
   - Default for landmarks: guide + history + culture + style.
   - Default for objects/crafts: guide + culture + art_critic + style.
4. `expert_perspectives`
   - Generate compact user-visible cards from the structured visual result.
   - No free hallucination; each card must reference visible clues or source cards.
5. `knowledge_enrichment`
   - Use existing evidence/knowledge cards first.
   - Later may call Exa/Wikipedia/Wikidata/OpenTripMap, but only when needed for background or low-confidence cases.
6. `narrative`
   - Compose a warm Chinese story and a shorter `audio_script`.
   - Preserve uncertainty and avoid pretending a low-confidence guess is confirmed.
7. `visual_memory`
   - Create a lightweight memory item with discovered/saved/planned status.
   - P0 memory is session/local backend only; no login or cross-device sync.
8. `render_contract`
   - Return current-compatible response plus the new perspective, memory, audio, and workflow fields.

## Implementation Tasks

### Task 1: Add Gemini configuration

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`

- [ ] Add settings for `visual_primary_provider`, `gemini_vision_model`, `gemini_thinking_level`, `gemini_media_resolution`, `google_cloud_project`, `google_cloud_location`, and `google_genai_use_vertexai`.
- [ ] Default `deepinfra_vision_model` to `google/gemini-3.1-pro` for the project `.env` and example config.
- [ ] Keep existing DeepInfra settings unchanged.
- [ ] Add `.env.example` comments that Gemini is optional and DeepInfra fallback still works.

### Task 2: Extend visual schemas

**Files:**
- Modify: `backend/app/schemas/visual.py`
- Modify: `web/src/lib/api.ts`

- [ ] Add `PerspectiveCard`, `VisualMemoryItem`, and `VisualWorkflowSummary` Pydantic models.
- [ ] Add matching TypeScript types.
- [ ] Keep all current fields backward compatible so existing `/visual` rendering and tests keep passing.

### Task 3: Add Gemini visual client

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/services/vlm.py`
- Test: `backend/tests/test_gemini_vlm.py`

- [ ] Add `google-genai` dependency if using the SDK; otherwise implement direct REST with `httpx`.
- [ ] Add `GeminiVlmClient.identify(request)` returning the same normalized dict shape as `DeepInfraVlmClient`.
- [ ] Include all uploaded images as multimodal parts.
- [ ] Request strict JSON only.
- [ ] Set `thinking_level` and `media_resolution` from config.
- [ ] On API errors, return heuristic fallback with `provider_error`.
- [ ] Unit test with mocked Gemini response containing `Kushida Shrine`, `Fukuoka`, visible clues, hypotheses, and uncertainty.

### Task 4: Add visual workflow and expert perspectives

**Files:**
- Create: `backend/app/services/visual_workflow.py`
- Modify: `backend/app/services/agent.py`
- Test: `backend/tests/test_visual_workflow.py`

- [ ] Implement workflow stages listed above as ordinary async functions.
- [ ] Keep the graph bounded; no while-loop autonomous agent behavior.
- [ ] Generate perspective cards from the visual reasoning JSON and selected perspectives.
- [ ] Add deterministic fallback cards when narrative/expert generation fails.
- [ ] Ensure cache hit returns the enriched response with `cache.hit=true`.

### Task 5: Wire provider factory

**Files:**
- Modify: `backend/app/services/agent.py`
- Test: `backend/tests/test_agent_factory.py`

- [ ] If `VISUAL_PRIMARY_PROVIDER=gemini` and Gemini credentials/config exist, use `GeminiVlmClient`.
- [ ] Else if DeepInfra is configured, use `DeepInfraVlmClient`.
- [ ] Else use `HeuristicVlmClient`.
- [ ] Include selected provider/model in `visual_workflow_summary`.

### Task 6: Upgrade Web `/visual`

**Files:**
- Modify: `web/src/app/visual/page.tsx`
- Test: `web/tests/companion.spec.ts`

- [ ] Keep one-photo upload as the primary interaction.
- [ ] Make text/context optional and visually secondary.
- [ ] Add perspective tabs/cards: Guide, History, Culture, Art, Style.
- [ ] Add visual memory block with Save/Reject/Plan states in local UI state.
- [ ] Add audio play button using browser `SpeechSynthesis` reading `audio_script`.
- [ ] Show uncertainty as “我不确定的地方”，not as error text.

### Task 7: Japan golden landmark matrix

**Files:**
- Create: `backend/tests/test_gemini_visual_landmarks.py`
- Create: `docs/visual-test-matrix-japan.md`

- [ ] Add mocked tests for Fukuoka/Kyushu and Kansai canonical names.
- [ ] Add optional live test guarded by `RUN_GEMINI_VISUAL_LIVE=1`.
- [ ] Live tests must skip unless Gemini credentials are configured.
- [ ] Record each case with expected canonical terms, region, visual clue expectations, and acceptable uncertainty.

## Japan Test Matrix

### Fukuoka / Kyushu

| Area | Case | Expected recognition | Expected perspective emphasis |
| --- | --- | --- | --- |
| Fukuoka | Fukuoka Tower | `Fukuoka Tower`, `福岡タワー` | Guide, style, photo |
| Fukuoka | Dazaifu Tenmangu | `Dazaifu Tenmangu`, `太宰府天満宮` | History, culture, guide |
| Fukuoka | Kushida Shrine | `Kushida Shrine`, `櫛田神社` | History, culture |
| Fukuoka | Hakata Gion Yamakasa float/sign | `博多祇園山笠` when visible | Culture, history |
| Fukuoka | Momochi Seaside Park | `Momochi Seaside Park` / beach candidate | Guide, style, photo |
| Kitakyushu | Mojiko Retro | `門司港レトロ` | History, style |
| Oita | Beppu Jigoku | `別府地獄` / specific hell if visible | Guide, culture |
| Oita | Yufuin street/lake | `由布院` / `金鱗湖` if visible | Guide, style |
| Kumamoto | Kumamoto Castle | `熊本城` | History, architecture |
| Kagoshima | Sakurajima | `桜島` | Guide, geography |

### Kansai

| Area | Case | Expected recognition | Expected perspective emphasis |
| --- | --- | --- | --- |
| Kyoto | Kiyomizu-dera | `清水寺`, `Kiyomizu-dera` | History, culture, style |
| Kyoto | Fushimi Inari Taisha | `伏見稲荷大社` | Culture, guide |
| Kyoto | Kinkaku-ji | `金閣寺` | History, art critic |
| Kyoto | Shoren-in | `青蓮院` | History, style, calm/hidden gem |
| Kyoto | Nijo Castle | `二条城` | History, architecture |
| Osaka | Osaka Castle | `大阪城` | History, guide |
| Osaka | Dotonbori / Glico sign | `道頓堀`, `グリコサイン` | Culture, guide |
| Nara | Todai-ji | `東大寺` | History, culture |
| Uji | Byodo-in | `平等院` | History, art critic |
| Hyogo | Himeji Castle | `姫路城` | History, architecture |

## Acceptance Criteria

- A user can upload one image with no text and receive a complete visual story.
- Famous landmarks in the Japan matrix return a correct canonical name or an explicit low-confidence candidate list.
- The response includes at least two perspective cards for every successful Gemini/DeepInfra result.
- The page supports audio playback from `audio_script`.
- Debug labels, hidden reasoning, raw model traces, and provider errors are not displayed as user-facing recommendations.
- Existing backend and Web tests continue passing.

## Verification Commands

```powershell
cd backend
python -m pytest tests/test_gemini_vlm.py tests/test_visual_workflow.py tests/test_agent_factory.py -q
python -m pytest -q
python -m compileall app
```

```powershell
cd web
npm test -- --reporter=list --workers=2
npm run lint
npm run build
```

Optional live test:

```powershell
cd backend
$env:RUN_GEMINI_VISUAL_LIVE='1'
python -m pytest tests/test_gemini_visual_landmarks.py -q
```

## References

- Google DeepMind Gemini 3.1 Pro model card: https://deepmind.google/models/model-cards/gemini-3-1-pro/
- Vertex AI Gemini 3 getting started / `thinking_level` / OpenAI compatibility: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/get-started-with-gemini-3
- Gemini API media resolution: https://ai.google.dev/gemini-api/docs/media-resolution
- Vertex AI thinking docs: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking
- Existing project research cache: `codex/cache/2026-05-21_chance-ai-architecture-research.md`
