# First-Timer Recommendation Fast Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make obvious first-time city recommendation requests return concise structured cards and a ready map without calling the GPT orchestrator/final synthesis.

**Architecture:** Reuse the existing deterministic card-summary pipeline. Add a narrow request classifier and deterministic `place_cards` contract for first-timer discovery prompts, then let existing Serper/place-card rendering and concise sections produce the public response.

**Tech Stack:** Python, pytest, existing `TravelRecommendationSupervisor`, existing `travel_workflow_graph.py` orchestration graph.

---

### Task 1: Lock the slow first-timer path with a failing test

**Files:**
- Modify: `backend/tests/test_travel_orchestrator_workflow.py`
- Test: `backend/tests/test_travel_orchestrator_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_obvious_fukuoka_first_timer_recommendation_uses_fast_path_without_gpt():
    class NoModelFirstTimerAgentClient(OrchestratorAgentClient):
        async def run_agent(self, *, agent_name: str, model: str, prompt: str, payload: dict) -> dict:
            if agent_name == "travel_orchestrator":
                raise AssertionError("obvious first-timer recommendation should not call GPT orchestrator or final synthesis")
            return await super().run_agent(agent_name=agent_name, model=model, prompt=prompt, payload=payload)

    agent_client = NoModelFirstTimerAgentClient()
    serper = FukuokaFirstTimerSerperClient()
    response = await _supervisor(agent_client, serper).plan(
        TravelPlanRequest(city="Fukuoka", query="福冈第一次去，有哪些地方值得去？给我几个适合新手的点。", allow_web_search=True)
    )

    assert response.answer_mode == "place_cards"
    assert response.raw_provider_refs["travel_orchestrator"]["finalization"] == "deterministic_structured_cards"
    assert agent_client.calls == []
    assert serper.calls == ["serper_places:本地体验"]
    assert response.display_cards
    assert response.map_view["status"] == "ready"
    assert len(response.map_view["pins"]) >= 3
    assert "第一次" in response.formatted_markdown
    assert "交通" in response.formatted_markdown or "顺路" in response.formatted_markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_travel_orchestrator_workflow.py::test_obvious_fukuoka_first_timer_recommendation_uses_fast_path_without_gpt -q`

Expected: FAIL because `_orchestrate` still calls the GPT orchestrator for this prompt.

### Task 2: Implement the minimal deterministic contract

**Files:**
- Modify: `backend/app/services/travel_workflow_graph.py`
- Test: `backend/tests/test_travel_orchestrator_workflow.py`

- [ ] **Step 1: Add `_is_obvious_first_timer_recommendation_request`**

The predicate should reject inventory/weather/visa/route/itinerary prompts, require a place-discovery marker, and require a first-timer marker such as `第一次`, `初访`, `新手`, or `first time`.

- [ ] **Step 2: Add `_obvious_first_timer_recommendation_contract`**

Return `answer_mode="place_cards"` with one required `serper_places` call using category `本地体验`, query from `_place_discovery_query`, no image/search tools, and empty `data_gaps`.

- [ ] **Step 3: Route before GPT orchestration**

In `_orchestrate`, check first-timer recommendation after the itinerary fast path and before `_call_travel_orchestrator`.

- [ ] **Step 4: Keep deterministic summary**

Do not change the final summary pipeline unless the new fast path fails to produce concise first-timer sections from existing display cards.

### Task 3: Verify, commit, push, and deploy

**Files:**
- Modify: `.codex/project-summary.md`

- [ ] **Step 1: Run targeted and regression tests**

Run:
`python -m pytest backend/tests/test_travel_orchestrator_workflow.py -q`
`python -m pytest evals/tests backend/tests/test_config.py backend/tests/test_openai_compatible_llm.py -q`
`python -m compileall -q backend/app evals/mira_eval`
`git diff --check`

- [ ] **Step 2: Commit and push**

Commit with a focused message and push branch `codex/llm-eval-harness`.

- [ ] **Step 3: Sync remote and smoke test**

Deploy to `/opt/photo-agent-visual` on `root@87.99.146.185`, restart PM2 services, then smoke the recommendation prompt and require cards plus ready map.
