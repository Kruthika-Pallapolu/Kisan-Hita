from fastapi import APIRouter, Request
from app.schemas.features import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request):
    settings = request.app.state.settings
    stt_enabled = not getattr(request.app.state.providers.speech_to_text, "is_mock", True)
    tts_enabled = not getattr(request.app.state.providers.text_to_speech, "is_mock", True)
    return {
        "status": "ok",
        "environment": settings.app_env,
        "gnani_live_api_enabled": settings.gnani_live_api_enabled,
        "prisma_input_enabled": settings.gnani_live_api_enabled and stt_enabled,
        "timbre_output_enabled": settings.gnani_live_api_enabled and tts_enabled,
        "providers": {
            "weather": settings.weather_provider,
            "crops": settings.crop_provider,
            "disease": settings.disease_provider,
            "market": settings.market_provider,
            "language_model": settings.llm_provider,
            "intent_understanding": settings.intent_provider,
            "speech_to_text": settings.speech_to_text_provider,
            "text_to_speech": settings.text_to_speech_provider,
        },
    }
