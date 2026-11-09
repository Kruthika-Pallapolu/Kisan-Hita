from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator

SUPPORTED_LANGUAGES = {"te", "en", "hi", "ta", "kn", "ml", "mr"}


def validate_language(value: str) -> str:
    base = value.replace("_", "-").split("-", 1)[0].lower()
    if base not in SUPPORTED_LANGUAGES:
        raise ValueError("Choose Telugu, English, Hindi, Tamil, Kannada, Malayalam, or Marathi.")
    return value


class ForecastDay(BaseModel):
    date: date
    summary: str
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    temperature_min_c: float | None = None
    precipitation_probability: int | None = Field(default=None, ge=0, le=100)


class CurrentConditions(BaseModel):
    time: datetime | None = None
    temperature_c: float | None = None
    relative_humidity_percent: int | None = Field(default=None, ge=0, le=100)
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None


class FarmTodayRequest(BaseModel):
    location: str | None = Field(default=None, min_length=1, max_length=160)
    state: str | None = Field(default=None, min_length=2, max_length=100)
    district: str | None = Field(default=None, min_length=2, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    question: str | None = Field(default=None, max_length=1000)
    crop: str | None = Field(default=None, max_length=100)
    growth_stage: str | None = Field(default=None, max_length=100)
    spray_product: str | None = Field(default=None, max_length=160)
    language: str = Field(default="en", min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)

    @model_validator(mode="after")
    def validate_location(self):
        if not self.location and not (self.state and self.district):
            raise ValueError("Choose a farm state and district, or provide a location.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together.")
        return self


class FarmTodayResponse(BaseModel):
    location: str
    observed_at: datetime | None
    forecast: list[ForecastDay]
    advice: list[str]
    alerts: list[str]
    source: str
    is_mock: bool
    notice: str
    state: str | None = None
    district: str | None = None
    resolved_place: str | None = None
    geographic_resolution: str | None = None
    current: CurrentConditions | None = None
    fetched_at: datetime | None = None
    forecast_period: str | None = None
    warnings_available: bool = False
    warnings_notice: str | None = None
    clarification_required: bool = False
    follow_up_question: str | None = None
    is_stale: bool = False


class CropRequest(BaseModel):
    state: str | None = Field(default=None, max_length=100)
    district: str = Field(min_length=1, max_length=160)
    soil_type: str | None = Field(default=None, max_length=80)
    water_availability: Literal["rainfed", "limited", "assured"] | None = None
    farm_size_acres: float | None = Field(default=None, gt=0, le=100_000)
    season: str = Field(min_length=1, max_length=80)
    language: str = Field(default="en", min_length=2, max_length=16)
    priority: str | None = Field(default=None, max_length=100)

    _validate_language = field_validator("language")(validate_language)

    @field_validator("district", "season", mode="before")
    @classmethod
    def strip_required_crop_details(cls, value):
        return value.strip() if isinstance(value, str) else value


class ExpectedYield(BaseModel):
    value: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=300)


class CropRecommendation(BaseModel):
    crop: str
    reasons: list[str]
    duration_days: int | None = Field(default=None, gt=0)
    water_requirement: str | None = None
    cultivation_notes: list[str]
    expected_yield: ExpectedYield | None = None
    confidence: Literal["low", "medium", "high"] | None = None


class CropEvidenceAttribution(BaseModel):
    evidence_id: str
    source_title: str
    publisher: str
    source_url: str
    evidence_type: Literal["current_recommendation", "historical_research", "regional_context"]
    publication_year: int | None = None
    publication_date: date | None = None
    reviewed_on: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    geography: str
    season: str | None = None
    reference_period: str | None = None
    conditions: list[str] = Field(default_factory=list)


class CropResponse(BaseModel):
    recommendations: list[CropRecommendation] = Field(max_length=3)
    disclaimer: str
    source: str
    is_mock: bool
    outcome: Literal["verified_recommendation", "regional_context_only", "no_applicable_evidence"] = "no_applicable_evidence"
    follow_up_question: str | None = None
    missing_details: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    evidence_issue: Literal["stale", "conflict", "conditions_not_matched", "multiple_matches"] | None = None
    evidence: list[CropEvidenceAttribution] = Field(default_factory=list)
    catalog_version: str | None = None
    recommendation_ready: bool = False
    regional_context: dict[str, object] | None = None


class CropHealthRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0)
    crop: str | None = Field(default=None, max_length=100)
    symptoms: str | None = Field(default=None, max_length=1000)


class PossibleCondition(BaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)
    symptoms: list[str]


class CropHealthResponse(BaseModel):
    possible_conditions: list[PossibleCondition]
    guidance: list[str]
    needs_expert: bool
    uncertainty: str
    source: str
    is_mock: bool
    agent_answer: str | None = None


class MarketPriceRequest(BaseModel):
    crop: str = Field(min_length=1, max_length=100)
    market: str = Field(min_length=1, max_length=160)
    variety: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=160)
    language: str = Field(default="en", min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)


class MarketPriceResponse(BaseModel):
    crop: str
    market: str
    variety: str | None = None
    price: float = Field(gt=0)
    minimum_price: float | None = Field(default=None, gt=0)
    maximum_price: float | None = Field(default=None, gt=0)
    modal_price: float | None = Field(default=None, gt=0)
    unit: str
    observed_at: datetime
    source: str
    is_mock: bool
    is_stale: bool = False


class MarketLookupResponse(BaseModel):
    prices: list[MarketPriceResponse] = Field(default_factory=list)
    available: bool = False
    message: str
    source: str


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=100)
    language: str = Field(min_length=2, max_length=16)
    message: str = Field(min_length=1, max_length=4000)
    context: dict[str, object] = Field(default_factory=dict)

    _validate_language = field_validator("language")(validate_language)


class ChatResponse(BaseModel):
    conversation_id: str
    language: str
    response_language: str | None = None
    response: str
    suggested_feature: Literal["my-farm-today", "choose-my-crop", "check-my-crop", "market-prices", "ask-kisan-hita"] | None = None
    is_mock: bool
    source: str
    clarification_required: bool = False
    tool_name: str | None = None
    tool_result: dict[str, object] | None = None
    answer_supported: bool = False
    answer_mode: str = "deterministic"


class SpeechToTextResponse(BaseModel):
    text: str
    language: str
    confidence: float | None = None
    is_mock: bool
    source: str
    notice: str


class TextToSpeechResponse(BaseModel):
    available: bool
    language: str
    audio_base64: str | None = None
    is_mock: bool
    source: str
    notice: str


class SpeechToTextRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=80)
    size_bytes: int = Field(gt=0)
    language: str = Field(min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)


class TextToSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = Field(min_length=2, max_length=16)

    _validate_language = field_validator("language")(validate_language)


class ContractInfo(BaseModel):
    feature: str
    method: str
    path: str
    request_schema: str
    response_schema: str
    implemented: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str
    providers: dict[str, str]
    gnani_live_api_enabled: bool = False
    prisma_input_enabled: bool = False
    timbre_output_enabled: bool = False


class ApiInfo(BaseModel):
    service: str
    api_prefix: str
    health: str
    docs: str
