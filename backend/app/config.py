from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


TRAVEL_ORCHESTRATOR_MODEL_DEFAULT = "gpt-5.5"
TRAVEL_SEMANTIC_MODEL_DEFAULT = "google/gemini-3.1-pro"
TRAVEL_FAST_MODEL_DEFAULT = "deepseek-ai/DeepSeek-V4-Flash"
TRAVEL_REASONING_MODEL_DEFAULT = "openai/gpt-oss-120b"
TRAVEL_REASONING_EFFORT_DEFAULT = "high"


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://photo_agent:photo_agent@127.0.0.1:3306/photo_agent?charset=utf8mb4",
    )
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_vision_model: str = os.getenv(
        "OLLAMA_VISION_MODEL", "qwen3-vl:4b-instruct"
    )
    vlm_provider: str = os.getenv("VLM_PROVIDER", "heuristic")
    deepinfra_api_key: str | None = os.getenv("DEEPINFRA_API_KEY")
    deepinfra_base_url: str = os.getenv(
        "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
    )
    litellm_base_url: str | None = os.getenv("LITELLM_BASE_URL")
    litellm_api_key: str | None = os.getenv("LITELLM_API_KEY")
    travel_main_api_key: str | None = os.getenv(
        "TRAVEL_MAIN_API_KEY", os.getenv("ZZSHU_API_KEY")
    )
    travel_main_base_url: str = os.getenv(
        "TRAVEL_MAIN_BASE_URL", os.getenv("ZZSHU_BASE_URL", "https://zzshu.cc/v1")
    )
    visual_primary_provider: str = os.getenv("VISUAL_PRIMARY_PROVIDER", "")
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")
    google_genai_use_vertexai: bool = os.getenv(
        "GOOGLE_GENAI_USE_VERTEXAI", "false"
    ).lower() in {"1", "true", "yes"}
    google_cloud_project: str | None = os.getenv("GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    gemini_base_url: str = os.getenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
    )
    gemini_vision_model: str = os.getenv(
        "GEMINI_VISION_MODEL", "gemini-3.1-pro-preview"
    )
    gemini_thinking_level: str = os.getenv("GEMINI_THINKING_LEVEL", "HIGH")
    gemini_media_resolution: str = os.getenv("GEMINI_MEDIA_RESOLUTION", "HIGH")
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    langfuse_public_key: str | None = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    google_maps_api_key: str | None = os.getenv("GOOGLE_MAPS_API_KEY")
    google_maps_map_id: str | None = os.getenv("GOOGLE_MAPS_MAP_ID")
    google_places_base_url: str = os.getenv(
        "GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com/v1"
    )
    serpapi_api_key: str | None = os.getenv("SERPAPI_API_KEY")
    serper_api_key: str | None = os.getenv("SERPER_API_KEY")
    serper_base_url: str = os.getenv("SERPER_BASE_URL", "https://google.serper.dev")
    travel_google_services_provider: str = os.getenv(
        "TRAVEL_GOOGLE_SERVICES_PROVIDER", "serper"
    ).lower()
    travel_allow_direct_google_places: bool = os.getenv(
        "TRAVEL_ALLOW_DIRECT_GOOGLE_PLACES", "false"
    ).lower() in {"1", "true", "yes"}
    travel_allow_serpapi_fallback: bool = os.getenv(
        "TRAVEL_ALLOW_SERPAPI_FALLBACK", "false"
    ).lower() in {"1", "true", "yes"}
    travel_allow_litellm_fallback: bool = os.getenv(
        "TRAVEL_ALLOW_LITELLM_FALLBACK", "false"
    ).lower() in {"1", "true", "yes"}
    public_image_base_url: str | None = os.getenv("PUBLIC_IMAGE_BASE_URL")
    deepinfra_vision_model: str = os.getenv(
        "DEEPINFRA_VISION_MODEL", "google/gemini-3.1-pro"
    )
    deepinfra_narrative_model: str = os.getenv(
        "DEEPINFRA_NARRATIVE_MODEL", "google/gemini-3.1-pro"
    )
    external_api_timeout_seconds: float = float(
        os.getenv("EXTERNAL_API_TIMEOUT_SECONDS", "1.5")
    )
    travel_decision_timeout_seconds: float = float(
        os.getenv("TRAVEL_DECISION_TIMEOUT_SECONDS", "120")
    )
    travel_model_semantic: str = os.getenv(
        "TRAVEL_MODEL_SEMANTIC", TRAVEL_SEMANTIC_MODEL_DEFAULT
    )
    travel_model_orchestrator: str = os.getenv(
        "TRAVEL_MODEL_ORCHESTRATOR", TRAVEL_ORCHESTRATOR_MODEL_DEFAULT
    )
    travel_model_complex_route: str = os.getenv(
        "TRAVEL_MODEL_COMPLEX_ROUTE",
        os.getenv("TRAVEL_MODEL_REASONING", TRAVEL_REASONING_MODEL_DEFAULT),
    )
    travel_model_router: str = os.getenv(
        "TRAVEL_MODEL_ROUTER",
        os.getenv("TRAVEL_MODEL_SEMANTIC", TRAVEL_SEMANTIC_MODEL_DEFAULT),
    )
    travel_model_fast: str = os.getenv(
        "TRAVEL_MODEL_FAST", TRAVEL_FAST_MODEL_DEFAULT
    )
    travel_model_reasoning: str = os.getenv(
        "TRAVEL_MODEL_REASONING", TRAVEL_REASONING_MODEL_DEFAULT
    )
    travel_model_reasoning_effort: str = os.getenv(
        "TRAVEL_MODEL_REASONING_EFFORT", TRAVEL_REASONING_EFFORT_DEFAULT
    )
    travel_model_critic: str = os.getenv(
        "TRAVEL_MODEL_CRITIC",
        os.getenv("TRAVEL_MODEL_REASONING", TRAVEL_REASONING_MODEL_DEFAULT),
    )
    travel_model_formatter: str = os.getenv(
        "TRAVEL_MODEL_FORMATTER",
        os.getenv("TRAVEL_MODEL_REASONING", TRAVEL_REASONING_MODEL_DEFAULT),
    )
    travel_decision_model: str = os.getenv(
        "TRAVEL_DECISION_MODEL",
        os.getenv("TRAVEL_MODEL_REASONING", TRAVEL_REASONING_MODEL_DEFAULT),
    )
    travel_orchestration_mode: str = os.getenv(
        "TRAVEL_ORCHESTRATION_MODE", "orchestrator"
    ).lower()
    travel_orchestrator_max_tool_rounds: int = int(
        os.getenv("TRAVEL_ORCHESTRATOR_MAX_TOOL_ROUNDS", "6")
    )
    travel_complex_max_tool_rounds: int = int(
        os.getenv("TRAVEL_COMPLEX_MAX_TOOL_ROUNDS", "10")
    )
    exa_api_key: str | None = os.getenv("EXA_API_KEY")
    exa_base_url: str = os.getenv("EXA_BASE_URL", "https://api.exa.ai")
    exa_timeout_seconds: float = float(os.getenv("EXA_TIMEOUT_SECONDS", "8"))
    tabiji_enabled: bool = os.getenv("TABIJI_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    tabiji_base_url: str = os.getenv("TABIJI_BASE_URL", "https://tabiji.ai/api/v1")
    tabiji_timeout_seconds: float = float(os.getenv("TABIJI_TIMEOUT_SECONDS", "6"))
    osrm_base_url: str | None = os.getenv("OSRM_BASE_URL")
    osrm_timeout_seconds: float = float(os.getenv("OSRM_TIMEOUT_SECONDS", "1.5"))
    admin_token: str = os.getenv("ADMIN_TOKEN", "photo-agent-local-admin")


settings = Settings()
