from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from app.schemas.features import (
    ChatRequest, ChatResponse, CropHealthRequest, CropHealthResponse, CropRequest,
    CropResponse, FarmTodayRequest, FarmTodayResponse, MarketPriceRequest,
    MarketLookupResponse,
)
from app.providers.open_meteo import WeatherLocationNotFoundError, WeatherUnavailableError
from app.services.language import locale_key, text as localized, weather_answer
from app.schemas.voice import FeatureDestination
from app.services.crop_evidence import attach_regional_context
from app.providers.interfaces import CropDiseaseProviderUnavailable

router = APIRouter(tags=["features"])


@router.post("/farm/today", response_model=FarmTodayResponse, tags=["My Farm Today"])
def farm_today(payload: FarmTodayRequest, request: Request):
    try:
        result = request.app.state.services.weather.get_today(payload)
    except WeatherLocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeatherUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.question and any(word in payload.question.lower() for word in ("spray", "pesticide", "pesticides", "spraying")) and not (payload.crop and payload.growth_stage and payload.spray_product):
        result.clarification_required = True
        result.follow_up_question = "Which crop, growth stage, and spray product are you asking about?"
    return result


@router.post("/crops/recommendations", response_model=CropResponse, tags=["Choose My Crop"])
def crop_recommendations(payload: CropRequest, request: Request):
    try:
        provider_result = request.app.state.providers.crops.recommend(payload)
    except Exception:
        provider_result = None
    verified = (provider_result is not None and not provider_result.is_mock
                and provider_result.outcome == "verified_recommendation"
                and provider_result.recommendation_ready and provider_result.recommendations
                and any(item.evidence_type == "current_recommendation" for item in provider_result.evidence))
    if not verified:
        if provider_result is None or provider_result.is_mock:
            provider_result = CropResponse(
                recommendations=[], is_mock=False,
                source="No current crop guidance is available.",
                disclaimer=localized("crop_no_evidence", payload.language),
                outcome="no_applicable_evidence", recommendation_ready=False,
            )
        elif provider_result.outcome == "verified_recommendation":
            provider_result.outcome = "no_applicable_evidence"
            provider_result.disclaimer = localized("crop_no_evidence", payload.language)
        provider_result.recommendations = []
        provider_result.recommendation_ready = False
    return attach_regional_context(provider_result, payload)


@router.post("/crop-health/analyze", response_model=CropHealthResponse, tags=["Check My Crop"])
async def crop_health(request: Request, filename: str, crop: str | None = None, symptoms: str | None = None, language: str = "en", conversation_id: str | None = None):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Choose a JPG, PNG or WebP image.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > request.app.state.settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="This image is too large. Choose a smaller image.")
    if not body:
        raise HTTPException(status_code=422, detail="Choose a crop photo first.")
    if content_type == "image/png" and not body.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="This file doesn’t look like a PNG image.")
    if content_type == "image/jpeg" and not body.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=422, detail="This file doesn’t look like a JPG image.")
    if content_type == "image/webp" and not (body.startswith(b"RIFF") and body[8:12] == b"WEBP"):
        raise HTTPException(status_code=422, detail="This file doesn’t look like a WebP image.")
    if len(body) > request.app.state.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="This image is too large. Choose a smaller image.")
    image_request = CropHealthRequest(filename=filename, content_type=content_type, size_bytes=len(body), crop=crop, symptoms=symptoms)
    try:
        result, evidence = request.app.state.services.voice.agent.assess_crop_image(image_request, bytes(body), language)
    except CropDiseaseProviderUnavailable:
        raise HTTPException(status_code=503, detail=localized("image_provider_unavailable", language)) from None
    except Exception:
        raise HTTPException(status_code=500, detail=localized("image_processing_failed", language)) from None
    if conversation_id:
        answer = request.app.state.services.voice.record_tool_result(
            conversation_id,
            f"I sent a crop photo. Crop: {crop or 'not given'}. Notes: {symptoms or 'not given'}.",
            FeatureDestination.CHECK_MY_CROP, evidence,
        )
        if answer is None:
            raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
        result.agent_answer = answer.response
    return result


@router.post("/market/prices", response_model=MarketLookupResponse, tags=["Market Prices"])
def market_prices(payload: MarketPriceRequest, request: Request):
    records = request.app.state.providers.market.lookup(payload)
    verified = [record for record in records if not record.is_mock]
    for record in verified:
        observed = record.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        record.is_stale = observed < datetime.now(timezone.utc) - timedelta(days=7)
    if verified:
        is_stale = all(record.is_stale for record in verified)
        message = localized("market_stale", payload.language) if is_stale else localized("market_available", payload.language)
        return MarketLookupResponse(prices=verified, available=not is_stale, message=message,
            source="; ".join(sorted({record.source for record in verified})))
    return MarketLookupResponse(
        prices=[], available=False,
        message=localized("market_unavailable", payload.language),
        source="No authorized live AGMARKNET/eNAM feed is configured.",
    )


@router.post("/assistant/messages", response_model=ChatResponse, tags=["Ask Kisan Hita"])
def assistant_message(payload: ChatRequest, request: Request):
    service = request.app.state.services.voice
    conversation_id = payload.conversation_id
    if conversation_id is None:
        conversation_id = service.create_conversation(payload.language).conversation_id
    if payload.context.get("continue_pending") is True:
        arguments = payload.context.get("tool_arguments")
        turn = service.continue_pending(conversation_id, arguments if isinstance(arguments, dict) else None)
        if turn is None:
            raise HTTPException(status_code=409, detail="There is no pending question to continue.")
    else:
        turn = service.understand(conversation_id, payload.message)
    if turn is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    return ChatResponse(conversation_id=conversation_id, language=payload.language,
        response_language=turn.result.response_language or turn.result.language,
        response=turn.result.response, suggested_feature=turn.result.destination.value,
        is_mock=turn.result.answer_mode.startswith("deterministic"),
        source=turn.result.source, clarification_required=turn.result.clarification_required,
        tool_name=turn.result.tool_name.value if turn.result.tool_name else None,
        tool_result=turn.result.tool_result, answer_supported=turn.result.answer_supported,
        answer_mode=turn.result.answer_mode)
