from copy import deepcopy
from fastapi.testclient import TestClient
from io import BytesIO
import wave
import pytest
from app.core.config import Settings, get_settings
from app.main import create_app
from app.providers.mock import (
    MOCK_NOTICE, DeterministicIntentProvider, MockCropDiseaseProvider, MockCropRecommendationProvider,
    MockLanguageModelProvider, MockMarketDataProvider, MockSpeechToTextProvider,
    MockTextToSpeechProvider, MockWeatherProvider,
)
from app.schemas.features import (ChatRequest, CropEvidenceAttribution, CropHealthRequest, CropRecommendation, CropRequest, CropResponse, FarmTodayRequest, FarmTodayResponse, MarketPriceRequest, SpeechToTextRequest, TextToSpeechRequest)
from app.services.container import DEFAULT_PROVIDER_FACTORIES, ProviderContainer, build_container
from app.services.weather import WeatherService
from app.core.database import create_database_engine
from sqlalchemy import text
from time import monotonic
import httpx
from app.providers.open_meteo import OpenMeteoWeatherProvider, WeatherUnavailableError
from app.providers.interfaces import CropDiseaseProviderUnavailable


@pytest.fixture
def client():
    return TestClient(create_app(Settings(database_url="sqlite:///:memory:")))


def test_api_root_and_health_endpoint(client):
    assert client.get("/").json()["service"] == "Kisan Hita API"
    assert client.get("/api/v1").json()["health"] == "/api/v1/health"
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["providers"] == {
        "weather": "mock", "crops": "evidence-catalog", "disease": "mock", "market": "mock",
        "language_model": "mock", "speech_to_text": "mock", "text_to_speech": "mock",
        "intent_understanding": "mock",
    }
    assert response.json()["gnani_live_api_enabled"] is False
    assert response.json()["prisma_input_enabled"] is False
    assert response.json()["timbre_output_enabled"] is False
    capabilities = client.get("/api/v1/voice/capabilities").json()
    assert capabilities["gnani_live_api_enabled"] is False
    assert capabilities["prisma_input_enabled"] is False
    assert capabilities["timbre_output_enabled"] is False


def test_configurable_prefix_applies_to_every_route():
    client = TestClient(create_app(Settings(api_v1_prefix="/v2/farm", database_url="sqlite:///:memory:")))
    assert client.get("/v2/farm").status_code == 200
    assert client.get("/v2/farm/health").status_code == 200
    assert client.get("/v2/farm/contracts").json()[0]["path"] == "/v2/farm/farm/today"
    assert client.post("/v2/farm/farm/today", json={"location": "Test"}).status_code == 200


def test_openapi_registers_feature_request_and_response_models(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/farm/today" in schema["paths"]
    operation = schema["paths"]["/api/v1/farm/today"]["post"]
    assert "FarmTodayRequest" in str(operation["requestBody"])
    assert "FarmTodayResponse" in str(operation["responses"]["200"])
    assert "/api/v1/market/prices" in schema["paths"]


def test_weather_endpoint_uses_service_and_structured_fictional_mock(client):
    response = client.post("/api/v1/farm/today", json={"location": "Demo district", "language": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Demo district"
    assert len(body["forecast"]) == 2
    assert body["is_mock"] is True
    assert "Fictional" in body["source"]
    assert body["notice"] == MOCK_NOTICE


def test_request_validation_returns_consistent_422(client):
    response = client.post("/api/v1/farm/today", json={"location": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]


def test_invalid_routes_return_consistent_json(client):
    response = client.get("/api/v1/no-such-route")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_error", "message": "Not Found"}}


def test_unhandled_errors_return_sanitized_consistent_json():
    app = create_app(Settings(database_url="sqlite:///:memory:"))

    @app.get("/test-error")
    def raise_error():
        raise RuntimeError("private internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/test-error")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "Something went wrong. Please try again."}}


def test_crop_recommendation_route_refuses_unverified_advice(client):
    response = client.post("/api/v1/crops/recommendations", json={"district": "Demo", "season": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert body["recommendation_ready"] is False
    assert body["missing_details"] == []
    assert body["follow_up_question"] is None
    assert body["outcome"] == "no_applicable_evidence"
    assert "don’t want to guess" in body["disclaimer"]
    assert body["is_mock"] is False


def test_crop_recommendation_provider_failure_returns_localized_safe_result(client, monkeypatch):
    def fail(_request):
        raise RuntimeError("private provider endpoint and credentials")

    monkeypatch.setattr(client.app.state.providers.crops, "recommend", fail)
    response = client.post("/api/v1/crops/recommendations", json={
        "state": "Telangana", "district": "Warangal", "season": "monsoon", "language": "te",
    })
    body = response.json()
    assert response.status_code == 200
    assert body["recommendations"] == []
    assert body["recommendation_ready"] is False
    assert body["follow_up_question"] is None
    assert "నమ్మకమైన సమాచారం" in body["disclaimer"]
    assert "private provider" not in str(body)


def test_crop_api_returns_attributed_verified_test_fixture_only(client, monkeypatch):
    fixture = CropResponse(
        recommendations=[CropRecommendation(
            crop="Test-only crop", reasons=["Test source condition."], cultivation_notes=[],
        )],
        disclaimer="Verified test fixture.", source="Test institution", is_mock=False,
        outcome="verified_recommendation", recommendation_ready=True,
        evidence=[CropEvidenceAttribution(
            evidence_id="test-only-record", source_title="Test crop guide", publisher="Test institution",
            source_url="https://example.test/test-guide", evidence_type="current_recommendation",
            publication_year=2025, publication_date="2025-05-01", reviewed_on="2026-06-01",
            valid_from="2025-06-01", valid_until="2026-12-31", geography="Warangal district",
            season="Kharif", conditions=["Red soil", "Limited water"],
        )],
    )
    monkeypatch.setattr(client.app.state.providers.crops, "recommend", lambda _request: fixture)
    response = client.post("/api/v1/crops/recommendations", json={
        "state": "Telangana", "district": "Warangal", "soil_type": "red",
        "water_availability": "limited", "season": "monsoon", "language": "en",
    })
    body = response.json()
    assert response.status_code == 200
    assert body["outcome"] == "verified_recommendation"
    assert body["recommendation_ready"] is True
    assert body["recommendations"][0]["crop"] == "Test-only crop"
    assert body["evidence"][0]["source_title"] == "Test crop guide"
    assert body["evidence"][0]["publication_date"] == "2025-05-01"
    assert body["evidence"][0]["valid_until"] == "2026-12-31"
    assert body["recommendations"][0]["expected_yield"] is None
    assert body["recommendations"][0]["confidence"] is None


def test_crop_api_rejects_verified_provider_result_without_current_source(client, monkeypatch):
    ungrounded = CropResponse(
        recommendations=[CropRecommendation(crop="Unsupported", reasons=["No cited source."], cultivation_notes=[])],
        disclaimer="A recommendation without evidence.", source="Unknown", is_mock=False,
        outcome="verified_recommendation", recommendation_ready=True,
    )
    monkeypatch.setattr(client.app.state.providers.crops, "recommend", lambda _request: ungrounded)
    response = client.post("/api/v1/crops/recommendations", json={
        "state": "Telangana", "district": "Warangal", "season": "monsoon", "language": "en",
    })
    body = response.json()
    assert response.status_code == 200
    assert body["outcome"] == "regional_context_only"
    assert body["recommendations"] == []
    assert body["recommendation_ready"] is False


@pytest.mark.parametrize("payload", [
    {"district": "Warangal", "season": "   "},
    {"district": "Warangal", "season": "monsoon", "farm_size_acres": 0},
    {"district": "Warangal", "season": "monsoon", "water_availability": "unknown-value"},
])
def test_crop_recommendation_rejects_invalid_details(client, payload):
    response = client.post("/api/v1/crops/recommendations", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_crop_recommendation_with_details_still_refuses_to_invent_suitability(client):
    response = client.post("/api/v1/crops/recommendations", json={"district": "Warangal", "soil_type": "red", "water_availability": "limited", "season": "monsoon", "language": "te"})
    body = response.json()
    assert response.status_code == 200
    assert body["recommendations"] == []
    assert body["recommendation_ready"] is False
    assert body["outcome"] == "no_applicable_evidence"
    assert "ఊహించి చెప్పను" in body["disclaimer"]


def test_warangal_crop_profile_is_context_only_and_not_a_recommendation(client):
    response = client.post("/api/v1/crops/recommendations", json={"state": "Telangana", "district": "Warangal", "soil_type": "red", "water_availability": "limited", "season": "Vanakalam"})
    body = response.json()
    assert response.status_code == 200
    assert body["recommendations"] == [] and body["recommendation_ready"] is False
    assert body["outcome"] == "regional_context_only"
    assert body["regional_context"]["region"] == "Central Telangana Zone"
    assert body["regional_context"]["publication_year"] == 2021
    assert body["evidence"][0]["evidence_type"] == "regional_context"
    assert body["evidence"][0]["source_title"] == "Telangana Statistical Abstract 2021"
    assert body["evidence"][0]["geography"] == "Central Telangana Zone"
    assert "cotton" in body["regional_context"]["crops_reported"]
    assert "suitability for this farm" in body["regional_context"]["limitation"]
    assert "yield" in body["regional_context"]["limitation"] and "profit" in body["regional_context"]["limitation"]


def test_warangal_regional_context_requires_explicit_state(client):
    response = client.post("/api/v1/crops/recommendations", json={
        "district": "Warangal", "season": "monsoon", "language": "en",
    })
    body = response.json()
    assert response.status_code == 200
    assert body["recommendations"] == []
    assert body["regional_context"] is None
    assert "don’t want to guess" in body["disclaimer"]


def test_market_lookup_returns_no_fabricated_prices(client):
    response = client.post("/api/v1/market/prices", json={"crop": "tomato", "market": "Warangal", "language": "hi"})
    body = response.json()
    assert response.status_code == 200
    assert body["prices"] == []
    assert body["available"] is False
    assert "अंदाज़ा" in body["message"]


def test_crop_image_upload_validates_real_image_and_never_claims_diagnosis(client):
    url = "/api/v1/crop-health/analyze?filename=leaf.png&crop=tomato&symptoms=spots&language=te"
    missing = client.post(url, content=b"", headers={"Content-Type": "image/png"})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "http_error"
    assert missing.json()["error"]["message"] == "Choose a crop photo first."
    bad = client.post(url, content=b"not an image", headers={"Content-Type": "image/png"})
    assert bad.status_code == 422
    assert bad.json()["error"]["message"] == "This file doesn’t look like a PNG image."
    valid = client.post(url, content=b"\x89PNG\r\n\x1a\nfixture-bytes", headers={"Content-Type": "image/png"})
    body = valid.json()
    assert valid.status_code == 200
    assert body["possible_conditions"] == []
    assert body["needs_expert"] is True
    assert body["is_mock"] is False
    assert "గుర్తించలేదు" in body["uncertainty"]


def test_crop_image_upload_returns_specific_format_and_size_errors(client):
    unsupported = client.post("/api/v1/crop-health/analyze?filename=leaf.gif", content=b"GIF89a", headers={"Content-Type": "image/gif"})
    assert unsupported.status_code == 415
    assert "JPG, PNG or WebP" in unsupported.json()["error"]["message"]
    oversized = client.post("/api/v1/crop-health/analyze?filename=leaf.png", content=b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024), headers={"Content-Type": "image/png"})
    assert oversized.status_code == 413
    assert "too large" in oversized.json()["error"]["message"]


def test_crop_image_provider_unavailable_is_reported_without_fabricating_diagnosis(client, monkeypatch):
    def fail(*_args, **_kwargs):
        raise CropDiseaseProviderUnavailable("private model failure")
    monkeypatch.setattr(client.app.state.services.voice.agent, "assess_crop_image", fail)
    response = client.post("/api/v1/crop-health/analyze?filename=leaf.png&language=te", content=b"\x89PNG\r\n\x1a\nfixture-bytes", headers={"Content-Type": "image/png"})
    assert response.status_code == 503
    assert "అందుబాటులో లేదు" in response.json()["error"]["message"]
    assert "private model failure" not in response.text


def test_crop_image_processing_failure_is_distinct_and_sanitized(client, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private model failure")
    monkeypatch.setattr(client.app.state.services.voice.agent, "assess_crop_image", fail)
    response = client.post("/api/v1/crop-health/analyze?filename=leaf.png&language=te", content=b"\x89PNG\r\n\x1a\nfixture-bytes", headers={"Content-Type": "image/png"})
    assert response.status_code == 500
    assert "పరిశీలించలేకపోయాం" in response.json()["error"]["message"]
    assert "private model failure" not in response.text


def test_assistant_does_not_trust_weather_evidence_supplied_by_the_browser(client):
    response = client.post("/api/v1/assistant/messages", json={"language": "te", "message": "రేపు వర్షం పడుతుందా?", "context": {"weather": {"district": "Warangal", "forecast": [{"summary": "Clear sky", "precipitation_probability": 4, "temperature_c": 31}, {"summary": "Rain showers", "precipitation_probability": 78, "temperature_c": 27}]}}})
    assert response.status_code == 200
    assert "78%" not in response.json()["response"]
    assert "రాష్ట్రం" in response.json()["response"]
    assert response.json()["response_language"] == "te"
    assert response.json()["answer_supported"] is False


def test_language_change_keeps_session_history_and_farm_location(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    identifier = conversation["conversation_id"]
    client.put(f"/api/v1/voice/conversations/{identifier}/farm-location", json={"state": "Telangana", "district": "Warangal"})
    client.post(f"/api/v1/voice/conversations/{identifier}/messages", json={"message": "Will it rain tomorrow?"})
    changed = client.put(f"/api/v1/voice/conversations/{identifier}/language", json={"language": "te"}).json()
    assert changed["language"] == "te"
    assert changed["farm_location"] == {"state": "Telangana", "district": "Warangal"}
    assert changed["history"][0] == {"role": "farmer", "text": "Will it rain tomorrow?"}


def test_conversation_context_survives_backend_recreation(tmp_path):
    database = tmp_path / "sessions.sqlite"
    url = f"sqlite:///{database}"
    first = TestClient(create_app(Settings(database_url=url)))
    conversation = first.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    identifier = conversation["conversation_id"]
    first.post(f"/api/v1/voice/conversations/{identifier}/messages", json={"message": "Will it rain tomorrow?"})
    first.close()

    second = TestClient(create_app(Settings(database_url=url)))
    follow_up = second.post(f"/api/v1/voice/conversations/{identifier}/messages", json={"message": "Then what about that?"}).json()
    assert follow_up["result"]["destination"] == "my-farm-today"
    assert follow_up["result"]["entities"]["follow_up"] is True
    second.close()


def test_cors_allows_only_configured_frontend_origins():
    settings = Settings(database_url="sqlite:///:memory:")
    client = TestClient(create_app(settings))
    allowed = client.options("/api/v1/health", headers={"Origin": "http://127.0.0.1:5175", "Access-Control-Request-Method": "GET"})
    rejected = client.options("/api/v1/health", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "GET"})
    assert "http://127.0.0.1:5175" in settings.frontend_origins
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5175"
    assert "access-control-allow-origin" not in rejected.headers


def test_independent_provider_configuration_and_bad_names_fail_clearly():
    settings = Settings(weather_provider="mock", crop_provider="mock", disease_provider="mock", market_provider="mock", llm_provider="mock", speech_to_text_provider="mock", text_to_speech_provider="mock")
    container = build_container(settings)
    assert isinstance(container, ProviderContainer)
    with pytest.raises(ValueError, match="Unsupported weather provider 'unknown'. Available providers: mock"):
        build_container(Settings(weather_provider="unknown"))


def test_provider_can_switch_via_configuration_with_local_test_adapter():
    class LocalTestWeather:
        def get_forecast(self, request):
            return MockWeatherProvider().get_forecast(request)

    factories = deepcopy(DEFAULT_PROVIDER_FACTORIES)
    factories["weather"]["local-test"] = LocalTestWeather
    selected = build_container(Settings(weather_provider="local-test"), provider_factories=factories)
    result = WeatherService(selected.weather).get_today(FarmTodayRequest(location="Test"))
    assert isinstance(selected.weather, LocalTestWeather)
    assert result.location == "Test"
    assert result.is_mock


def test_intent_provider_can_be_switched_and_invalid_choice_fails_clearly():
    class LocalIntent:
        def understand(self, request):
            return DeterministicIntentProvider().understand(request)

    factories = deepcopy(DEFAULT_PROVIDER_FACTORIES)
    factories["intent_understanding"]["local-test"] = LocalIntent
    selected = build_container(Settings(intent_provider="local-test"), provider_factories=factories)
    assert isinstance(selected.intent_understanding, LocalIntent)
    with pytest.raises(ValueError, match="Unsupported intent_understanding provider 'missing'"):
        build_container(Settings(intent_provider="missing"))


def test_provider_override_is_used_without_recursive_resolution():
    class OverrideWeather:
        def get_forecast(self, request):
            return FarmTodayResponse(location=request.location, observed_at=None, forecast=[], advice=[], alerts=[], source="Override fixture", is_mock=True, notice=MOCK_NOTICE)

    container = build_container(overrides={"weather": OverrideWeather()})
    result = container.weather.get_forecast(FarmTodayRequest(location="Test"))
    assert result.source == "Override fixture"


def test_mock_domains_return_explicit_safe_development_payloads():
    crop_request = CropRequest(district="Demo", season="test", water_availability="rainfed")
    crop = MockCropRecommendationProvider().recommend(crop_request)
    disease = MockCropDiseaseProvider().analyze(CropHealthRequest(filename="leaf.png", content_type="image/png", size_bytes=100), b"fixture image")
    market = MockMarketDataProvider().lookup(MarketPriceRequest(crop="Sample crop", market="Sample mandi"))
    llm = MockLanguageModelProvider().respond(ChatRequest(message="weather", language="en"))
    stt = MockSpeechToTextProvider().transcribe(SpeechToTextRequest(filename="audio.wav", content_type="audio/wav", size_bytes=100, language="en"), b"fixture audio")
    tts = MockTextToSpeechProvider().synthesize(TextToSpeechRequest(text="hello", language="en"))
    assert crop.is_mock and "Fictional" in crop.source and "not use" in crop.disclaimer
    assert disease.is_mock and disease.needs_expert and not disease.possible_conditions
    assert len(market) == 1 and market[0].is_mock and "Fabricated" in market[0].source
    assert llm.is_mock and llm.suggested_feature == "my-farm-today"
    assert stt.is_mock and stt.text == "" and "No audio was transcribed" in stt.notice
    assert tts.is_mock and not tts.available and "unavailable" in tts.notice


def test_provider_settings_load_independently_from_environment(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "mock")
    monkeypatch.setenv("CROP_PROVIDER", "local-crop")
    monkeypatch.setenv("DISEASE_PROVIDER", "mock")
    monkeypatch.setenv("MARKET_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("INTENT_PROVIDER", "mock")
    monkeypatch.setenv("SPEECH_TO_TEXT_PROVIDER", "mock")
    monkeypatch.setenv("TEXT_TO_SPEECH_PROVIDER", "mock")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.weather_provider == "mock" and settings.crop_provider == "local-crop"
    assert settings.disease_provider == settings.market_provider == "mock"
    assert settings.llm_provider == settings.speech_to_text_provider == settings.text_to_speech_provider == "mock"
    assert settings.intent_provider == "mock"
    get_settings.cache_clear()


def test_voice_sessions_route_all_five_destinations_without_fabricating_answers(client):
    created = client.post("/api/v1/voice/conversations", json={"language": "en"})
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["language_status"] == "unverified"
    cases = [
        ("Will it rain tomorrow?", "MY_FARM_TODAY", "my-farm-today"),
        ("Which crop should I grow?", "CHOOSE_MY_CROP", "choose-my-crop"),
        ("My crop leaves are turning yellow", "CHECK_MY_CROP", "check-my-crop"),
        ("What is today's tomato price?", "MARKET_PRICES", "market-prices"),
        ("Tell me about compost", "ASK_KISAN_HITA", "ask-kisan-hita"),
    ]
    for message, intent, destination in cases:
        response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={"message": message})
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["intent"] == intent
        assert body["result"]["destination"] == destination
        assert body["feature_implemented"] is True
        assert body["result"]["tool_name"] == destination
        assert body["result"]["answer_mode"] == "deterministic-grounded-template"
        assert body["result"]["answer_supported"] is False


def test_voice_language_is_preserved_and_ambiguous_request_asks_clarification(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "te-IN"}).json()
    result = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={"message": "Will it rain tomorrow? రేపు"}).json()
    assert result["language"] == "te-IN"
    assert result["result"]["language"] == "te-IN"
    assert result["result"]["response_language"] == "te-IN"
    assert "వాయిస్" in result["result"]["language_notice"]
    assert result["result"]["intent"] == "ASK_KISAN_HITA"
    assert result["result"]["confidence"] < 0.5
    assert result["result"]["clarification_required"] is True


def test_voice_context_routes_follow_up_to_previous_feature(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages"
    client.post(url, json={"message": "Will it rain tomorrow?"})
    follow_up = client.post(url, json={"message": "Then what about that?"}).json()["result"]
    assert follow_up["destination"] == "my-farm-today"
    assert follow_up["entities"]["follow_up"] is True
    assert follow_up["clarification_required"] is True


def test_complete_weather_question_in_existing_session_is_not_misclassified_as_vague_follow_up(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages"
    client.post(url, json={"message": "Will it rain tomorrow?"})
    turn = client.post(url, json={"message": "Is it safe to spray pesticides today?"}).json()
    assert turn["result"]["destination"] == "my-farm-today"
    assert turn["result"]["clarification_required"] is True
    assert "crop" in turn["result"]["response"]


def test_audio_endpoint_never_fabricates_transcription_and_validates_input(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/audio"
    empty = client.post(url, content=b"", headers={"Content-Type": "audio/wav"})
    assert empty.status_code == 422
    wav = BytesIO()
    with wave.open(wav, "wb") as recording:
        recording.setnchannels(1); recording.setsampwidth(2); recording.setframerate(16000); recording.writeframes(b"\x00\x00" * 160)
    response = client.post(url, content=wav.getvalue(), headers={"Content-Type": "audio/wav"})
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["transcribed"] is False
    assert response.json()["text"] == ""
    assert response.json()["turn"] is None
    assert "No audio was transcribed" in response.json()["notice"]
    assert client.post(url, content=b"x", headers={"Content-Type": "text/plain"}).status_code == 415


def test_audio_endpoint_rejects_recordings_longer_than_thirty_seconds(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/audio"
    wav = BytesIO()
    with wave.open(wav, "wb") as recording:
        recording.setnchannels(1); recording.setsampwidth(2); recording.setframerate(16000); recording.writeframes(b"\x00\x00" * (31 * 16000))
    response = client.post(url, content=wav.getvalue(), headers={"Content-Type": "audio/wav"})
    assert response.status_code == 413


def test_voice_session_not_found_is_clear(client):
    response = client.post("/api/v1/voice/conversations/missing/messages", json={"message": "weather"})
    assert response.status_code == 404
    assert "Start a new conversation" in response.json()["error"]["message"]


def test_voice_speech_endpoint_uses_session_language_and_honest_unavailable_mock(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "ta-IN"}).json()
    response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/speech", json={"message": "Test response"})
    assert response.status_code == 200
    assert response.json()["language"] == "ta-IN"
    assert response.json()["available"] is False
    assert response.json()["audio_base64"] is None


def test_audio_endpoint_enforces_configured_maximum_size():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:", max_upload_bytes=2)))
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/audio", content=b"123", headers={"Content-Type": "audio/wav"})
    assert response.status_code == 413
    assert "upload limit" in response.json()["error"]["message"]


def test_sqlite_database_engine_is_local_and_usable():
    engine = create_database_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("select 1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_open_meteo_parses_forecast_and_identifies_source_timestamps_and_resolution():
    payload = {
        "current": {"time": "2026-11-03T12:00", "temperature_2m": 28.5, "relative_humidity_2m": 62,
                    "precipitation": 0.2, "wind_speed_10m": 11.4},
        "daily": {"time": ["2026-11-03", "2026-11-04"], "temperature_2m_max": [31, 30],
                  "temperature_2m_min": [22, 21], "precipitation_probability_max": [15, 70],
                  "precipitation_sum": [0, 8.2], "weather_code": [1, 61]},
    }
    result = OpenMeteoWeatherProvider()._parse_forecast(payload, FarmTodayRequest(state="Telangana", district="Warangal"), "Warangal, Hanamkonda, Telangana, India")
    assert result.source.startswith("Open-Meteo") and result.is_mock is False
    assert result.current.temperature_c == 28.5 and result.current.time.isoformat().startswith("2026-11-03T12:00")
    assert result.forecast[1].precipitation_probability == 70 and result.forecast[1].precipitation_mm == 8.2
    assert "model grid point" in result.geographic_resolution
    assert result.observed_at is None and result.fetched_at is not None
    assert result.warnings_available is False and result.alerts == []


def test_open_meteo_rejects_missing_or_malformed_required_data():
    provider = OpenMeteoWeatherProvider()
    request = FarmTodayRequest(state="Telangana", district="Warangal")
    with pytest.raises((ValueError, TypeError)):
        provider._parse_forecast({"current": {}, "daily": {"time": ["2026-11-03"]}}, request, "Warangal")
    with pytest.raises((ValueError, TypeError)):
        provider._parse_forecast({"current": {"temperature_2m": "not-a-number"}, "daily": {"time": ["2026-11-03"], "temperature_2m_max": [30]}}, request, "Warangal")


def test_open_meteo_provider_timeout_has_no_mock_fallback():
    class TimeoutClient:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def get(self, *_args, **_kwargs): raise httpx.ConnectTimeout("offline")
    provider = OpenMeteoWeatherProvider(client_factory=lambda **_kwargs: TimeoutClient())
    with pytest.raises(WeatherUnavailableError):
        provider.get_forecast(FarmTodayRequest(state="Telangana", district="Warangal"))


def test_open_meteo_serves_stale_cache_with_explicit_stale_flag():
    provider = OpenMeteoWeatherProvider()
    request = FarmTodayRequest(state="Telangana", district="Warangal", latitude=17.4, longitude=78.5)
    base = provider._parse_forecast({
        "current": {"time": "2026-11-03T12:00", "temperature_2m": 28},
        "daily": {"time": ["2026-11-03"], "temperature_2m_max": [30], "temperature_2m_min": [20],
                  "precipitation_probability_max": [10], "precipitation_sum": [0], "weather_code": [0]},
    }, request, "selected location")
    provider._resolve_location = lambda _request: (17.4, 78.5, "selected location")
    provider._cache[(17.4, 78.5)] = (monotonic() - provider.cache_ttl_seconds - 1, base)
    provider._fetch_forecast = lambda *_args: (_ for _ in ()).throw(WeatherUnavailableError("offline"))
    result = provider.get_forecast(request)
    assert result.is_stale is True
    assert "cached forecast" in result.notice


def test_voice_farm_location_is_saved_and_changeable_in_session(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/farm-location"
    first = client.put(url, json={"state": "Telangana", "district": "Warangal"})
    assert first.status_code == 200
    assert first.json()["farm_location"] == {"state": "Telangana", "district": "Warangal"}
    changed = client.put(url, json={"state": "Andhra Pradesh", "district": "Guntur"})
    assert changed.json()["farm_location"] == {"state": "Andhra Pradesh", "district": "Guntur"}


def test_spray_question_routes_to_weather_and_returns_focused_follow_up(client):
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    turn = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={"message": "Is it safe to spray pesticides today?"}).json()
    assert turn["result"]["destination"] == "my-farm-today"
    assert turn["feature_implemented"] is True
    forecast = client.post("/api/v1/farm/today", json={"state": "Telangana", "district": "Warangal", "question": "Is it safe to spray pesticides today?"})
    assert forecast.status_code == 200
    assert forecast.json()["clarification_required"] is True
    assert "crop, growth stage, and spray product" in forecast.json()["follow_up_question"]
    assert forecast.json()["is_mock"] is True
    assert "Fictional" in forecast.json()["source"]


def test_open_meteo_location_resolution_rejects_wrong_state():
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"name": "A place", "latitude": 18, "longitude": 79, "admin1": "Other State"}]}
    class Client:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def get(self, *_args, **_kwargs): return Response()
    provider = OpenMeteoWeatherProvider(client_factory=lambda **_kwargs: Client())
    from app.providers.open_meteo import WeatherLocationNotFoundError
    with pytest.raises(WeatherLocationNotFoundError, match="selected state"):
        provider._resolve_location(FarmTodayRequest(state="Telangana", district="Warangal"))
