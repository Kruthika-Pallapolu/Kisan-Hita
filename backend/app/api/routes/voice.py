from fastapi import APIRouter, HTTPException, Request
from io import BytesIO
import wave
from app.schemas.features import SpeechToTextRequest, TextToSpeechRequest, TextToSpeechResponse
from app.providers.gnani_speech import SpeechProviderUnavailable
from app.services.language import text as localized
from app.schemas.voice import (AudioInputResponse, ConversationCreate, ConversationLanguage, ConversationResponse,
    FarmLocationSelection, LanguageCapabilitiesResponse, VoiceMessageRequest, VoiceTurnResponse)

router = APIRouter(prefix="/voice", tags=["voice foundation"])
AUDIO_TYPES = {"audio/wav", "audio/x-wav"}
MAX_AUDIO_SECONDS = 30


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(payload: ConversationCreate, request: Request):
    return request.app.state.services.voice.create_conversation(payload.language)


@router.get("/capabilities", response_model=LanguageCapabilitiesResponse)
def language_capabilities(request: Request):
    languages = ["te", "en", "hi", "ta", "kn", "ml", "mr"]
    stt_enabled = not getattr(request.app.state.providers.speech_to_text, "is_mock", True)
    tts_enabled = not getattr(request.app.state.providers.text_to_speech, "is_mock", True)
    return LanguageCapabilitiesResponse(gnani_live_api_enabled=request.app.state.settings.gnani_live_api_enabled,
        prisma_input_enabled=request.app.state.settings.gnani_live_api_enabled and stt_enabled,
        timbre_output_enabled=request.app.state.settings.gnani_live_api_enabled and tts_enabled, languages=[{
        "language": code,
        "interface_translation": "partial",
        "text_input_and_response": "deterministic phrase rules and reviewed templates; not general language reasoning",
        "backend_stt": "Gnani Prisma v3.0 enabled" if request.app.state.settings.gnani_live_api_enabled and stt_enabled else "unavailable; type your question",
        "backend_tts": "Gnani Timbre v3.0 enabled" if request.app.state.settings.gnani_live_api_enabled and tts_enabled else "unavailable; text response remains available",
        "browser_speech": "not used; voice input is processed by the configured backend provider",
    } for code in languages], note="Audio features are available only when the backend master switch and the respective live provider are enabled.")


@router.put("/conversations/{conversation_id}/farm-location", response_model=ConversationResponse)
def set_farm_location(conversation_id: str, payload: FarmLocationSelection, request: Request):
    result = request.app.state.services.voice.set_farm_location(conversation_id, payload.state, payload.district)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    return result


@router.put("/conversations/{conversation_id}/language", response_model=ConversationResponse)
def set_language(conversation_id: str, payload: ConversationLanguage, request: Request):
    result = request.app.state.services.voice.set_language(conversation_id, payload.language)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    return result


@router.post("/conversations/{conversation_id}/messages", response_model=VoiceTurnResponse)
def understand_message(conversation_id: str, payload: VoiceMessageRequest, request: Request):
    result = request.app.state.services.voice.understand(
        conversation_id, payload.message, payload.client_turn_id, payload.tool_arguments,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    return result


@router.post("/conversations/{conversation_id}/audio", response_model=AudioInputResponse)
async def accept_audio(conversation_id: str, request: Request):
    service = request.app.state.services.voice
    session = service._get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Send a WAV audio recording.")
    limit = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and int(declared) > limit:
        raise HTTPException(status_code=413, detail="Audio exceeds the configured upload limit.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="Audio exceeds the configured upload limit.")
    if not body:
        raise HTTPException(status_code=422, detail="Audio input is empty.")
    try:
        with wave.open(BytesIO(body), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            if duration <= 0:
                raise ValueError("empty audio")
            if duration > MAX_AUDIO_SECONDS:
                raise HTTPException(status_code=413, detail="Audio recordings must be 30 seconds or shorter.")
    except (wave.Error, EOFError, ZeroDivisionError, ValueError):
        raise HTTPException(status_code=422, detail="The audio file is not a valid WAV recording.") from None
    try:
        result = request.app.state.providers.speech_to_text.transcribe(
            SpeechToTextRequest(filename="voice-input", content_type=content_type, size_bytes=len(body), language=str(session["language"])),
            bytes(body),
        )
    except SpeechProviderUnavailable:
        raise HTTPException(status_code=503, detail=localized("speech_unavailable", str(session["language"]))) from None
    transcript = result.text.strip() if not result.is_mock else ""
    # STT only: require the farmer to review/correct and explicitly submit text
    # to /messages before the orchestrator can run any feature tool.
    turn = None
    return AudioInputResponse(accepted=True, transcribed=bool(transcript), text=transcript,
        language=result.language, confidence=result.confidence, is_mock=result.is_mock, notice=result.notice, turn=turn)


@router.post("/conversations/{conversation_id}/speech", response_model=TextToSpeechResponse)
def synthesize_response(conversation_id: str, payload: VoiceMessageRequest, request: Request):
    service = request.app.state.services.voice
    session = service._get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation.")
    try:
        return request.app.state.providers.text_to_speech.synthesize(
            TextToSpeechRequest(text=payload.message, language=str(session["language"]))
        )
    except SpeechProviderUnavailable:
        raise HTTPException(status_code=503, detail=localized("speech_unavailable", str(session["language"]))) from None
