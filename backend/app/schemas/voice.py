from enum import Enum
from pydantic import BaseModel, Field, field_validator
from app.schemas.features import validate_language


class VoiceIntent(str, Enum):
    MY_FARM_TODAY = "MY_FARM_TODAY"
    CHOOSE_MY_CROP = "CHOOSE_MY_CROP"
    CHECK_MY_CROP = "CHECK_MY_CROP"
    MARKET_PRICES = "MARKET_PRICES"
    ASK_KISAN_HITA = "ASK_KISAN_HITA"


class FeatureDestination(str, Enum):
    MY_FARM_TODAY = "my-farm-today"
    CHOOSE_MY_CROP = "choose-my-crop"
    CHECK_MY_CROP = "check-my-crop"
    MARKET_PRICES = "market-prices"
    ASK_KISAN_HITA = "ask-kisan-hita"


class IntentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", min_length=2, max_length=16)
    context: dict[str, object] = Field(default_factory=dict)

    _validate_language = field_validator("language")(validate_language)


class IntentResult(BaseModel):
    intent: VoiceIntent
    destination: FeatureDestination
    entities: dict[str, object] = Field(default_factory=dict)
    required_parameters: list[str] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    clarification_required: bool = False
    response: str
    language: str
    response_language: str = "en"
    language_notice: str | None = None
    is_mock: bool = True
    source: str = "Deterministic local English keyword rules"
    tool_name: FeatureDestination | None = None
    tool_result: dict[str, object] | None = None
    answer_supported: bool = False
    answer_mode: str = "deterministic"


class ConversationCreate(BaseModel):
    language: str = Field(default="en", min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)


class ConversationResponse(BaseModel):
    conversation_id: str
    language: str
    language_status: str = "unverified"
    language_notice: str
    farm_location: dict[str, str] | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


class ConversationLanguage(BaseModel):
    language: str = Field(min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)


class FarmLocationSelection(BaseModel):
    state: str = Field(min_length=2, max_length=100)
    district: str = Field(min_length=2, max_length=120)


class VoiceMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    client_turn_id: str | None = Field(default=None, min_length=8, max_length=100)
    tool_arguments: dict[str, object] = Field(default_factory=dict)


class GroundedAnswerRequest(BaseModel):
    original_question: str = Field(min_length=1, max_length=4000)
    language: str = Field(min_length=2, max_length=16)
    conversation_context: list[dict[str, str]] = Field(default_factory=list, max_length=16)
    active_feature: str | None = None
    tool_name: FeatureDestination
    tool_result: dict[str, object] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    timestamp: str | None = None
    provenance: str | None = None
    instructions: str = Field(default=(
        "Answer the farmer's original question naturally in the selected language. Use only validated tool results "
        "and recent conversation context. Never invent weather, warnings, crop suitability, diagnoses, prices, doses, "
        "yield, or profit. If evidence is missing, stale, uncertain, or unsafe, state that clearly and ask only for "
        "the required missing details."
    ))

    _validate_language = field_validator("language")(validate_language)


class GroundedAnswerResponse(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    language: str
    supported_by_evidence: bool
    clarification_required: bool = False
    adapter_name: str
    is_mock: bool


class LanguageCapability(BaseModel):
    language: str
    interface_translation: str
    text_input_and_response: str
    backend_stt: str
    backend_tts: str
    browser_speech: str


class LanguageCapabilitiesResponse(BaseModel):
    gnani_live_api_enabled: bool
    prisma_input_enabled: bool
    timbre_output_enabled: bool
    languages: list[LanguageCapability]
    note: str


class VoiceTurnResponse(BaseModel):
    conversation_id: str
    language: str
    result: IntentResult
    feature_implemented: bool = False
    feature_notice: str


class AudioInputResponse(BaseModel):
    accepted: bool
    transcribed: bool = False
    text: str = ""
    language: str
    confidence: float | None = None
    is_mock: bool = True
    notice: str
    turn: VoiceTurnResponse | None = None
