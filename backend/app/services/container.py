from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from typing import Any
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import Settings
from app.providers.interfaces import (CropDiseaseProvider, CropRecommendationProvider, GroundedAnswerProvider, IntentUnderstandingProvider, LanguageModelProvider, MarketDataProvider, SpeechToTextProvider, TextToSpeechProvider, WeatherProvider)
from app.providers.mock import (DeterministicGroundedAnswerProvider, DeterministicIntentProvider, MockCropDiseaseProvider, MockCropRecommendationProvider, MockLanguageModelProvider, MockMarketDataProvider, MockSpeechToTextProvider, MockTextToSpeechProvider, MockWeatherProvider, PrismaFixtureSpeechToTextProvider, TimbreFixtureTextToSpeechProvider)
from app.providers.open_meteo import OpenMeteoWeatherProvider
from app.providers.gnani_speech import GnaniPrismaV3Provider, GnaniTimbreV3Provider
from app.providers.data_gov_market import DataGovMarketProvider
from app.services.weather import WeatherService
from app.services.voice import VoiceService
from app.services.agent import AgentOrchestrator
from app.services.crop_evidence import EvidenceCatalogCropRecommendationProvider


@dataclass(frozen=True)
class ProviderContainer:
    weather: WeatherProvider
    crops: CropRecommendationProvider
    disease: CropDiseaseProvider
    market: MarketDataProvider
    language_model: LanguageModelProvider
    intent_understanding: IntentUnderstandingProvider
    speech_to_text: SpeechToTextProvider
    text_to_speech: TextToSpeechProvider
    answer_generation: GroundedAnswerProvider


@dataclass(frozen=True)
class ServiceContainer:
    weather: WeatherService
    voice: VoiceService


ProviderFactory = Callable[[], Any]
DEFAULT_PROVIDER_FACTORIES: dict[str, dict[str, ProviderFactory]] = {
    "weather": {"mock": MockWeatherProvider, "open-meteo": OpenMeteoWeatherProvider},
    "crops": {"mock": MockCropRecommendationProvider, "evidence-catalog": EvidenceCatalogCropRecommendationProvider},
    "disease": {"mock": MockCropDiseaseProvider},
    "market": {"mock": MockMarketDataProvider},
    "language_model": {"mock": MockLanguageModelProvider},
    "intent_understanding": {"mock": DeterministicIntentProvider},
    "speech_to_text": {"mock": MockSpeechToTextProvider, "prisma-fixture": PrismaFixtureSpeechToTextProvider},
    "text_to_speech": {"mock": MockTextToSpeechProvider, "timbre-fixture": TimbreFixtureTextToSpeechProvider},
    "answer_generation": {"mock": DeterministicGroundedAnswerProvider},
}

SETTING_BY_CATEGORY = {
    "weather": "weather_provider",
    "crops": "crop_provider",
    "disease": "disease_provider",
    "market": "market_provider",
    "language_model": "llm_provider",
    "intent_understanding": "intent_provider",
    "speech_to_text": "speech_to_text_provider",
    "text_to_speech": "text_to_speech_provider",
    "answer_generation": "llm_provider",
}


def build_container(
    settings: Settings | None = None,
    *,
    overrides: Mapping[str, object] | None = None,
    provider_factories: Mapping[str, Mapping[str, ProviderFactory]] | None = None,
) -> ProviderContainer:
    """Build all providers once. Test factories can be injected without network access."""
    settings = settings or Settings()
    if settings.gnani_live_api_enabled and (
        settings.speech_to_text_provider != "prisma-live" or settings.text_to_speech_provider != "timbre-live"
    ):
        raise ValueError(
            "GNANI_LIVE_API_ENABLED=true requires SPEECH_TO_TEXT_PROVIDER=prisma-live "
            "and TEXT_TO_SPEECH_PROVIDER=timbre-live; mock providers will not be substituted."
        )
    factories = provider_factories if provider_factories is not None else DEFAULT_PROVIDER_FACTORIES
    overrides = overrides or {}
    categories = set(SETTING_BY_CATEGORY)
    unknown_overrides = set(overrides) - categories
    if unknown_overrides:
        raise ValueError(f"Unknown provider override category: {', '.join(sorted(unknown_overrides))}")

    selected: dict[str, object] = {}
    for category, setting_name in SETTING_BY_CATEGORY.items():
        name = getattr(settings, setting_name)
        if category in overrides:
            selected[category] = overrides[category]
            continue
        available = factories.get(category, {})
        factory = available.get(name)
        if factory is None and category == "market" and name == "datagov":
            api_key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
            if not api_key:
                raise ValueError("DATA_GOV_IN_API_KEY is required when MARKET_PROVIDER=datagov.")
            factory = lambda key=api_key: DataGovMarketProvider(key)
        if factory is None and ((category == "speech_to_text" and name == "prisma-live") or
                                (category == "text_to_speech" and name == "timbre-live")):
            if not settings.gnani_live_api_enabled:
                raise ValueError("Gnani providers are disabled. Explicitly set GNANI_LIVE_API_ENABLED=true and select the provider to enable live use.")
            api_key = os.getenv("GNANI_API_KEY", "").strip()
            if not api_key:
                raise ValueError("GNANI_API_KEY is required in the backend environment when a live provider is explicitly enabled.")
            if name == "prisma-live" and category == "speech_to_text":
                factory = lambda key=api_key: GnaniPrismaV3Provider(key)
            elif name == "timbre-live" and category == "text_to_speech":
                factory = lambda key=api_key: GnaniTimbreV3Provider(key)
        if factory is None:
            choices = ", ".join(sorted(available)) or "none registered"
            raise ValueError(f"Unsupported {category} provider '{name}'. Available providers: {choices}.")
        selected[category] = factory()
    return ProviderContainer(**selected)


def build_services(providers: ProviderContainer, session_factory: sessionmaker[Session] | None = None,
                   retention_days: int = 30) -> ServiceContainer:
    agent = AgentOrchestrator(intent=providers.intent_understanding, weather=providers.weather,
        crops=providers.crops, disease=providers.disease, market=providers.market,
        answer_generator=providers.answer_generation)
    return ServiceContainer(weather=WeatherService(providers.weather),
        voice=VoiceService(agent, session_factory, retention_days=retention_days))
