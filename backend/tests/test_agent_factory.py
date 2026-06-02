from app.config import Settings
from app.services.agent import build_visual_agent
from app.services.vlm import (
    DeepInfraNarrativeClient,
    DeepInfraVlmClient,
    GeminiVlmClient,
    HeuristicNarrativeClient,
    HeuristicVlmClient,
)


def test_build_visual_agent_uses_deepinfra_when_configured():
    agent = build_visual_agent(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key="test-token",
            deepinfra_vision_model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            deepinfra_narrative_model="google/gemma-4-26B-A4B-it",
        )
    )

    assert isinstance(agent.dependencies.vlm, DeepInfraVlmClient)
    assert isinstance(agent.dependencies.narrative_client, DeepInfraNarrativeClient)


def test_build_visual_agent_uses_deepinfra_gemini_proxy_models():
    agent = build_visual_agent(
        Settings(
            vlm_provider="deepinfra",
            deepinfra_api_key="test-token",
            deepinfra_base_url="https://api.deepinfra.com/v1/openai",
            deepinfra_vision_model="google/gemini-3.1-pro",
            deepinfra_narrative_model="google/gemini-3.1-flash-lite",
            litellm_base_url="http://127.0.0.1:4000/v1",
            litellm_api_key="litellm-local-key",
            google_api_key=None,
        )
    )

    assert isinstance(agent.dependencies.vlm, DeepInfraVlmClient)
    assert agent.dependencies.vlm.model == "google/gemini-3.1-pro"
    assert agent.dependencies.vlm.base_url == "https://api.deepinfra.com/v1/openai"
    assert agent.dependencies.vlm.api_key == "test-token"
    assert isinstance(agent.dependencies.narrative_client, DeepInfraNarrativeClient)
    assert agent.dependencies.narrative_client.model == "google/gemini-3.1-flash-lite"
    assert agent.dependencies.narrative_client.base_url == "https://api.deepinfra.com/v1/openai"
    assert agent.dependencies.narrative_client.api_key == "test-token"


def test_build_visual_agent_uses_gemini_when_primary_provider_configured():
    agent = build_visual_agent(
        Settings(
            visual_primary_provider="gemini",
            google_api_key="test-gemini-key",
            gemini_vision_model="gemini-3.1-pro-preview",
            gemini_thinking_level="HIGH",
            gemini_media_resolution="HIGH",
        )
    )

    assert isinstance(agent.dependencies.vlm, GeminiVlmClient)
    assert agent.dependencies.vlm.model == "gemini-3.1-pro-preview"
    assert isinstance(agent.dependencies.narrative_client, HeuristicNarrativeClient)


def test_build_visual_agent_falls_back_without_key():
    agent = build_visual_agent(Settings(vlm_provider="deepinfra", deepinfra_api_key=None))

    assert isinstance(agent.dependencies.vlm, HeuristicVlmClient)
    assert isinstance(agent.dependencies.narrative_client, HeuristicNarrativeClient)
