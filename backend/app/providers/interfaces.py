from typing import Protocol
from app.schemas.features import (ChatRequest, ChatResponse, CropHealthRequest, CropHealthResponse, CropRequest, CropResponse, FarmTodayRequest, FarmTodayResponse, MarketPriceRequest, MarketPriceResponse, SpeechToTextRequest, SpeechToTextResponse, TextToSpeechRequest, TextToSpeechResponse)
from app.schemas.voice import GroundedAnswerRequest, GroundedAnswerResponse, IntentRequest, IntentResult


class CropDiseaseProviderUnavailable(RuntimeError):
    """Raised when an image-analysis adapter cannot be reached or is disabled."""


class WeatherProvider(Protocol):
    def get_forecast(self, request: FarmTodayRequest) -> FarmTodayResponse: ...


class CropRecommendationProvider(Protocol):
    def recommend(self, request: CropRequest) -> CropResponse: ...


class CropDiseaseProvider(Protocol):
    def analyze(self, request: CropHealthRequest, image: bytes) -> CropHealthResponse: ...


class MarketDataProvider(Protocol):
    def lookup(self, request: MarketPriceRequest) -> list[MarketPriceResponse]: ...


class LanguageModelProvider(Protocol):
    def respond(self, request: ChatRequest) -> ChatResponse: ...


class SpeechToTextProvider(Protocol):
    def transcribe(self, request: SpeechToTextRequest, audio: bytes) -> SpeechToTextResponse: ...


class TextToSpeechProvider(Protocol):
    def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResponse: ...


class IntentUnderstandingProvider(Protocol):
    def understand(self, request: IntentRequest) -> IntentResult: ...


class GroundedAnswerProvider(Protocol):
    """Provider-independent answer generation contract; mocks must disclose themselves."""
    def generate(self, request: GroundedAnswerRequest) -> GroundedAnswerResponse: ...
