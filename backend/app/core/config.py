from functools import lru_cache
import os
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    app_name: str = "Kisan Hita API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./kisan_hita.db"
    frontend_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5175", "http://127.0.0.1:5175"])
    weather_provider: str = "mock"
    crop_provider: str = "evidence-catalog"
    disease_provider: str = "mock"
    market_provider: str = "mock"
    llm_provider: str = "mock"
    intent_provider: str = "mock"
    speech_to_text_provider: str = "mock"
    text_to_speech_provider: str = "mock"
    gnani_live_api_enabled: bool = False
    max_upload_bytes: int = 5 * 1024 * 1024
    conversation_retention_days: int = Field(default=30, ge=1, le=365)

    @field_validator(
        "weather_provider", "crop_provider", "disease_provider", "market_provider",
        "llm_provider", "intent_provider", "speech_to_text_provider", "text_to_speech_provider",
    )
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        value = value.lower().strip()
        if not value or not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Provider names must be non-empty letters, numbers, hyphens, or underscores.")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("/") or value == "/" or "//" in value:
            raise ValueError("API_V1_PREFIX must be an absolute path such as /api/v1.")
        return value

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175")
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./kisan_hita.db"),
        frontend_origins=origins,
        weather_provider=os.getenv("WEATHER_PROVIDER", "open-meteo"),
        crop_provider=os.getenv("CROP_PROVIDER", "evidence-catalog"),
        disease_provider=os.getenv("DISEASE_PROVIDER", "mock"),
        market_provider=os.getenv("MARKET_PROVIDER", "mock"),
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
        intent_provider=os.getenv("INTENT_PROVIDER", "mock"),
        speech_to_text_provider=os.getenv("SPEECH_TO_TEXT_PROVIDER", "mock"),
        text_to_speech_provider=os.getenv("TEXT_TO_SPEECH_PROVIDER", "mock"),
        gnani_live_api_enabled=os.getenv("GNANI_LIVE_API_ENABLED", "false").strip().lower() == "true",
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        conversation_retention_days=int(os.getenv("CONVERSATION_RETENTION_DAYS", "30")),
    )
