from datetime import date, datetime, timezone
from io import BytesIO
import wave

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.features import CropRecommendation, CropRequest, CropResponse, FarmTodayResponse, ForecastDay
from app.services.container import build_container
from app.services.crop_evidence import (CropEvidenceCatalog, CropRecommendationEvidence,
    EvidenceCatalogCropRecommendationProvider, PRODUCTION_CROP_EVIDENCE_CATALOG, evaluate_crop_evidence)


class VerifiedWeatherFixture:
    def get_forecast(self, request):
        return FarmTodayResponse(
            location=f"{request.district}, {request.state}", state=request.state, district=request.district,
            observed_at=None,
            forecast=[
                ForecastDay(date="2030-06-01", summary="Clear sky", temperature_c=31, precipitation_mm=0, precipitation_probability=4),
                ForecastDay(date="2030-06-02", summary="Rain showers", temperature_c=27, precipitation_mm=4, precipitation_probability=78),
                ForecastDay(date="2030-06-03", summary="Cloudy", temperature_c=29, precipitation_mm=0, precipitation_probability=20),
            ],
            advice=[], alerts=[], source="Verified weather fixture", is_mock=False, notice="Fixture-backed test only.",
            fetched_at=datetime.now(timezone.utc), geographic_resolution="Test grid location",
        )


def crop_evidence(**overrides):
    values = {
        "evidence_id": "pjtau-test-kharif-001",
        "crop_id": "sample-crop",
        "crop_names": {"en": "Sample crop", "te": "నమూనా పంట"},
        "explanations": {"en": "The reviewed source lists this crop for these conditions.", "te": "ఈ పరిస్థితులకు ఈ పంటను మూలంలో సూచించారు."},
        "state": "Telangana", "geography": "Warangal district", "geography_level": "district",
        "districts": ("Warangal",), "season": "Kharif",
        "source_title": "PJTSAU current crop guide", "publisher": "PJTSAU",
        "source_url": "https://pjtau.example.test/crop-guide.pdf", "publication_year": 2025,
        "evidence_type": "current_recommendation", "decision": "recommend",
        "required_soil_types": ("red",), "required_water_availability": ("limited",),
        "conditions_by_language": {
            "en": ("Red soil", "Limited water"), "te": ("ఎర్ర నేల", "పరిమిత నీరు"),
        },
        "reviewed_on": date(2026, 6, 1), "valid_from": date(2025, 1, 1),
    }
    values.update(overrides)
    return CropRecommendationEvidence(**values)


def crop_request(**overrides):
    values = {
        "state": "Telangana", "district": "Warangal", "soil_type": "red",
        "water_availability": "limited", "season": "Vanakalam", "language": "te",
    }
    values.update(overrides)
    return CropRequest(**values)


def test_crop_catalog_returns_only_matching_recommendation_with_full_attribution():
    record = crop_evidence()
    response = evaluate_crop_evidence(crop_request(), CropEvidenceCatalog("test-1", (record,)), today=date(2026, 11, 4))
    assert response.outcome == "verified_recommendation"
    assert response.recommendation_ready is True
    assert len(response.recommendations) == 1
    assert response.recommendations[0].crop == "నమూనా పంట"
    assert response.recommendations[0].confidence is None
    assert response.recommendations[0].expected_yield is None
    evidence = response.evidence[0]
    assert evidence.source_title == "PJTSAU current crop guide"
    assert evidence.publication_year == 2025
    assert evidence.reviewed_on == date(2026, 6, 1)
    assert evidence.geography == "Warangal district"
    assert evidence.season == "Kharif"
    assert evidence.conditions == ["ఎర్ర నేల", "పరిమిత నీరు"]


def test_crop_catalog_does_not_invent_an_expiry_date():
    record = crop_evidence(publication_year=2023, reviewed_on=None, valid_until=None)
    response = evaluate_crop_evidence(crop_request(), CropEvidenceCatalog("test-1", (record,)), today=date(2026, 11, 4))
    assert response.outcome == "verified_recommendation"
    assert response.evidence[0].reviewed_on is None


def test_crop_catalog_rejects_unsupported_geography():
    response = evaluate_crop_evidence(
        crop_request(district="Pune"), CropEvidenceCatalog("test-1", (crop_evidence(),)), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.recommendations == []
    assert response.evidence == []
    assert "ఊహించి చెప్పను" in response.disclaimer


def test_crop_catalog_requires_only_conditions_named_by_the_source():
    record = crop_evidence(required_soil_types=None, required_water_availability=None, conditions_by_language={})
    response = evaluate_crop_evidence(
        crop_request(soil_type=None, water_availability=None), CropEvidenceCatalog("test-1", (record,)), today=date(2026, 11, 4),
    )
    assert response.outcome == "verified_recommendation"
    assert response.missing_conditions == []


def test_crop_catalog_explains_missing_required_soil_and_water_in_selected_language():
    response = evaluate_crop_evidence(
        crop_request(soil_type=None, water_availability=None),
        CropEvidenceCatalog("test-1", (crop_evidence(),)), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.recommendations == []
    assert set(response.missing_conditions) == {"soil_type", "water_availability"}
    assert "నేల రకం, నీటి లభ్యతపై ఆధారపడి ఉంది" in response.disclaimer
    assert response.evidence[0].publication_year == 2025


def test_crop_catalog_rejects_expired_and_historical_evidence():
    expired = crop_evidence(valid_until=date(2026, 1, 1))
    historical = crop_evidence(evidence_id="historical-study", evidence_type="historical_research", valid_until=None)
    for record in (expired, historical):
        response = evaluate_crop_evidence(
            crop_request(), CropEvidenceCatalog("test-1", (record,)), today=date(2026, 11, 4),
        )
        assert response.outcome == "no_applicable_evidence"
        assert response.evidence_issue == "stale"
        assert response.recommendations == []
        assert "పాతది" in response.disclaimer


def test_crop_catalog_fails_closed_on_conflicting_applicable_evidence():
    support = crop_evidence(crop_names={"en": "Sample crop", "te": "నమూనా పంట"})
    conflict = crop_evidence(evidence_id="pjtau-test-kharif-002", crop_names={"en": "Sample crop", "te": "వేరే స్థానిక పేరు"}, decision="do_not_recommend")
    response = evaluate_crop_evidence(
        crop_request(), CropEvidenceCatalog("test-1", (support, conflict)), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.evidence_issue == "conflict"
    assert response.recommendations == []
    assert len(response.evidence) == 2
    assert "వేర్వేరు సలహాలు" in response.disclaimer


def test_crop_catalog_does_not_rank_or_truncate_many_matching_crops():
    records = tuple(crop_evidence(
        evidence_id=f"test-evidence-{index}", crop_id=f"test-crop-{index}",
        crop_names={"en": f"Test crop {index}", "te": f"పరీక్ష పంట {index}"},
    ) for index in range(4))
    response = evaluate_crop_evidence(
        crop_request(), CropEvidenceCatalog("test-1", records), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.evidence_issue == "multiple_matches"
    assert response.recommendations == []
    assert len(response.evidence) == 4
    assert "పంటలు చాలా ఉన్నాయి" in response.disclaimer


def test_crop_catalog_does_not_guess_hyphenated_district_aliases():
    response = evaluate_crop_evidence(
        crop_request(district="Warangal-Urban"), CropEvidenceCatalog("test-1", (crop_evidence(),)), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.recommendations == []
    assert response.evidence == []


def test_crop_catalog_does_not_show_unreviewed_translation_as_advice():
    record = crop_evidence(crop_names={"en": "Sample crop"}, explanations={"en": "English only."})
    response = evaluate_crop_evidence(
        crop_request(language="mr"), CropEvidenceCatalog("test-1", (record,)), today=date(2026, 11, 4),
    )
    assert response.outcome == "no_applicable_evidence"
    assert response.missing_conditions == ["language_review"]
    assert "निवडलेल्या भाषेत नाही" in response.disclaimer


def test_weather_question_runs_backend_tool_and_returns_grounded_localized_answer():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    agent = client.app.state.services.voice.agent
    agent.weather = VerifiedWeatherFixture()
    conversation = client.post("/api/v1/voice/conversations", json={"language": "te"}).json()
    identifier = conversation["conversation_id"]
    client.put(f"/api/v1/voice/conversations/{identifier}/farm-location", json={"state": "Telangana", "district": "Warangal"})
    response = client.post(f"/api/v1/voice/conversations/{identifier}/messages", json={
        "message": "రేపు వర్షం పడుతుందా?", "client_turn_id": "weather-turn-0001",
    })
    assert response.status_code == 200
    body = response.json()
    assert "78%" in body["result"]["response"]
    assert body["language"] == body["result"]["response_language"] == "te"
    assert body["result"]["answer_supported"] is True
    assert body["result"]["tool_name"] == "my-farm-today"
    assert body["result"]["tool_result"]["source"] == "Verified weather fixture"
    assert body["result"]["tool_result"]["forecast_data"]["district"] == "Warangal"
    client.close()


def test_agent_returns_day_after_tomorrow_forecast_from_saved_weather_context():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    client.app.state.services.voice.agent.weather = VerifiedWeatherFixture()
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    identifier = conversation["conversation_id"]
    client.put(f"/api/v1/voice/conversations/{identifier}/farm-location", json={"state": "Telangana", "district": "Warangal"})
    first = client.post(f"/api/v1/voice/conversations/{identifier}/messages", json={"message": "Will it rain tomorrow?"}).json()
    follow = client.post(f"/api/v1/voice/conversations/{identifier}/messages", json={"message": "What about the day after tomorrow?"}).json()
    assert first["result"]["tool_result"]["day"]["precipitation_probability"] == 78
    assert follow["result"]["destination"] == "my-farm-today"
    assert follow["result"]["tool_result"]["day"]["precipitation_probability"] == 20
    assert "20%" in follow["result"]["response"]
    client.close()


def test_spray_follow_up_collects_and_remembers_details_without_unsafe_advice():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    client.app.state.services.voice.agent.weather = VerifiedWeatherFixture()
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    identifier = conversation["conversation_id"]
    client.put(f"/api/v1/voice/conversations/{identifier}/farm-location", json={"state": "Telangana", "district": "Warangal"})
    url = f"/api/v1/voice/conversations/{identifier}/messages"
    initial = client.post(url, json={"message": "Should I spray today?"}).json()
    assert initial["result"]["clarification_required"] is True
    assert "crop" in initial["result"]["response"]
    follow = client.post(f"/api/v1/assistant/messages", json={
        "conversation_id": identifier, "language": "en", "message": "Should I spray today?",
        "context": {"continue_pending": True, "tool_arguments": {"crop": "cotton", "growth_stage": "flowering", "spray_product": "product X"}},
    }).json()
    assert "Weather alone cannot confirm spray safety" in follow["response"]
    assert follow["answer_supported"] is True
    stored = client.app.state.services.voice._get(identifier)
    assert stored["farm_details"]["crop"] == "cotton"
    assert stored["farm_details"]["spray_product"] == "product X"
    next_turn = client.post(url, json={"message": "Could I spray then?"}).json()
    assert next_turn["result"]["clarification_required"] is False
    assert "Weather alone cannot confirm spray safety" in next_turn["result"]["response"]
    client.close()


def test_general_farmer_topics_use_grounded_templates_or_ask_for_missing_details():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    prompts = [
        ("What is a soil health card?", "soil-health-reference", True),
        ("How much urea should I apply?", "soil-test-based-fertilizer-caution", True),
        ("How should I prepare the soil?", "needs-topic-details", False),
        ("When should I irrigate my crop?", "needs-topic-details", False),
        ("How can I prevent pests?", "needs-topic-details", False),
        ("What should I do at this crop growth stage?", "needs-topic-details", False),
        ("How do I improve soil health?", "soil-health-reference", True),
        ("Can I use fertilizer safely?", "soil-test-based-fertilizer-caution", True),
        ("What is the right watering schedule?", "needs-topic-details", False),
        ("How do I prevent pest damage?", "needs-topic-details", False),
    ]
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    url = f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages"
    for index, (prompt, status, supported) in enumerate(prompts):
        response = client.post(url, json={"message": prompt, "client_turn_id": f"general-topic-{index:04d}"})
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["tool_result"]["status"] == status
        assert result["answer_supported"] is supported
        assert result["tool_name"] == "ask-kisan-hita"
        assert result["response"]
        if supported:
            assert "soilhealth.dac.gov.in" in result["source"]
        else:
            assert result["clarification_required"] is True
    client.close()


def test_general_soil_health_answer_is_localized_for_all_seven_languages():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    samples = {
        "en": "What is a soil health card?", "te": "నేల ఆరోగ్య కార్డు అంటే ఏమిటి?",
        "hi": "मृदा स्वास्थ्य कार्ड क्या है?", "ta": "மண் சுகாதார அட்டை என்றால் என்ன?",
        "kn": "ಮಣ್ಣಿನ ಆರೋಗ್ಯ ಕಾರ್ಡ್ ಎಂದರೇನು?", "ml": "മണ്ണിന്റെ ആരോഗ്യ കാർഡ് എന്താണ്?",
        "mr": "मृदा आरोग्य पत्रिका म्हणजे काय?",
    }
    for language, prompt in samples.items():
        conversation = client.post("/api/v1/voice/conversations", json={"language": language}).json()
        response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={"message": prompt})
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["response_language"] == language
        assert body["result"]["answer_supported"] is True
        assert body["result"]["tool_result"]["status"] == "soil-health-reference"
        assert body["result"]["response"]
    client.close()


def test_seasonal_crop_questions_reach_crop_advisor_in_all_seven_languages():
    samples = {
        "en": "What should I plant this season?",
        "te": "ఈ సీజన్‌లో ఏ పంట వేయాలి?",
        "hi": "इस मौसम में कौन सी फसल बोनी चाहिए?",
        "ta": "இந்த பருவத்தில் எந்த பயிரை பயிரிட வேண்டும்?",
        "kn": "ಈ ಋತುವಿನಲ್ಲಿ ಯಾವ ಬೆಳೆ ಬೆಳೆಯಬೇಕು?",
        "ml": "ഈ സീസണിൽ ഏത് വിള കൃഷി ചെയ്യണം?",
        "mr": "या हंगामात कोणते पीक घ्यावे?",
    }
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    for language, prompt in samples.items():
        conversation = client.post("/api/v1/voice/conversations", json={"language": language}).json()
        response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={"message": prompt})
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["destination"] == "choose-my-crop"
        assert result["tool_result"]["status"] == "needs_details"
        assert result["clarification_required"] is True
        assert result["response_language"] == language
    client.close()


def test_unsupported_profit_guarantee_question_stays_unverified_and_requests_clarification():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={
        "message": "Can you guarantee a profit from my field?",
    })
    result = response.json()["result"]
    assert result["destination"] == "ask-kisan-hita"
    assert result["tool_result"]["supported"] is False
    assert result["clarification_required"] is True
    assert "guarantee" not in result["response"].lower()
    client.close()


def test_crop_flow_asks_only_for_missing_required_details_in_selected_language():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    conversation = client.post("/api/v1/voice/conversations", json={"language": "te"}).json()
    response = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={
        "message": "ఏ పంట వేయాలి?", "tool_arguments": {"state": "Telangana", "district": "Warangal"},
    })
    body = response.json()["result"]
    assert body["clarification_required"] is True
    assert "పంట కాలం" in body["response"]
    assert "నేల" not in body["response"] and "నీటి" not in body["response"]
    assert "అందుబాటులో ఉన్న సమాచారంతో" in response.json()["feature_notice"]

    invalid = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={
        "message": "ఏ పంట వేయాలి?", "tool_arguments": {
            "state": "Telangana", "district": "Warangal", "season": "monsoon", "farm_size_acres": 0,
        },
    }).json()["result"]
    assert invalid["clarification_required"] is True
    assert "సంఖ్యలను సరిచూడండి" in invalid["response"]
    assert "farm_size_acres" not in str(invalid)
    client.close()


def test_crop_flow_uses_regional_context_without_recommending_and_persists_details(tmp_path):
    database = tmp_path / "crop-sessions.sqlite"
    url = f"sqlite:///{database}"
    first = TestClient(create_app(Settings(database_url=url)))
    conversation = first.post("/api/v1/voice/conversations", json={"language": "te"}).json()
    identifier = conversation["conversation_id"]
    payload = {"message": "ఏ పంట వేయాలి?", "tool_arguments": {
        "state": "Telangana", "district": "Warangal", "season": "monsoon",
        "soil_type": "red", "water_availability": "limited", "farm_size_acres": 2,
    }}
    first_result = first.post(f"/api/v1/voice/conversations/{identifier}/messages", json=payload).json()["result"]
    assert first_result["tool_result"]["status"] == "regional_context_only"
    assert first_result["tool_result"]["recommendations"] == []
    assert first_result["tool_result"]["outcome"] == "regional_context_only"
    assert first_result["tool_result"]["evidence"][0]["evidence_type"] == "regional_context"
    assert first_result["tool_result"]["evidence"][0]["publication_year"] == 2021
    assert "పత్తి" in first_result["response"] and "వరి" in first_result["response"]
    assert "cotton" not in first_result["response"] and "rice" not in first_result["response"]
    assert first_result["answer_supported"] is False
    first.close()

    second = TestClient(create_app(Settings(database_url=url)))
    resumed = second.post(f"/api/v1/voice/conversations/{identifier}/messages", json={
        "message": "ఏ పంట వేయాలి?",
    }).json()["result"]
    assert resumed["tool_result"]["status"] == "regional_context_only"
    assert resumed["tool_result"]["regional_context"]["region"] == "Central Telangana Zone"
    assert resumed["answer_supported"] is False
    second.close()


def test_default_crop_provider_has_no_production_recommendation_records():
    assert PRODUCTION_CROP_EVIDENCE_CATALOG.recommendations == ()
    result = EvidenceCatalogCropRecommendationProvider().recommend(crop_request())
    assert result.outcome == "no_applicable_evidence"
    assert result.recommendations == []
    assert result.catalog_version == PRODUCTION_CROP_EVIDENCE_CATALOG.version


def test_assistant_rejects_verified_crop_claim_without_current_source():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    ungrounded = CropResponse(
        recommendations=[CropRecommendation(crop="Unsupported", reasons=["No source."], cultivation_notes=[])],
        disclaimer="An unverified suggestion.", source="Unknown", is_mock=False,
        outcome="verified_recommendation", recommendation_ready=True,
    )
    client.app.state.services.voice.agent.crops.recommend = lambda _request: ungrounded
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    result = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={
        "message": "Which crop should I grow?", "tool_arguments": {
            "state": "Telangana", "district": "Warangal", "season": "monsoon",
        },
    }).json()["result"]
    assert result["tool_result"]["outcome"] == "regional_context_only"
    assert result["tool_result"]["recommendations"] == []
    assert result["answer_supported"] is False
    client.close()


def test_crop_provider_failure_is_reported_without_internal_details():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))

    def fail(_request):
        raise RuntimeError("private provider host and token")

    client.app.state.services.voice.agent.crops.recommend = fail
    conversation = client.post("/api/v1/voice/conversations", json={"language": "hi"}).json()
    result = client.post(f"/api/v1/voice/conversations/{conversation['conversation_id']}/messages", json={
        "message": "मुझे कौन सी फसल उगानी चाहिए?", "tool_arguments": {
            "state": "Maharashtra", "district": "Pune", "season": "monsoon",
        },
    }).json()["result"]
    assert result["tool_result"]["status"] == "no_verified_data"
    assert result["tool_result"]["recommendations"] == []
    assert "अंदाज़ा नहीं लगाऊँगा" in result["response"]
    assert "private provider" not in str(result)
    client.close()


def test_duplicate_client_turn_id_returns_the_saved_response_without_duplicate_history():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    conversation = client.post("/api/v1/voice/conversations", json={"language": "en"}).json()
    identifier = conversation["conversation_id"]
    url = f"/api/v1/voice/conversations/{identifier}/messages"
    payload = {"message": "Will it rain tomorrow?", "client_turn_id": "duplicate-turn-01"}
    first = client.post(url, json=payload).json()
    second = client.post(url, json=payload).json()
    assert first == second
    assert len(client.app.state.services.voice._get(identifier)["history"]) == 2
    client.close()


def test_assistant_reports_the_local_grounded_formatter_as_deterministic_mock():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    response = client.post("/api/v1/assistant/messages", json={"language": "en", "message": "Can you help me?"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is True
    assert body["answer_mode"] == "deterministic-grounded-template"
    client.close()


def test_language_capabilities_separate_ui_text_and_voice_support():
    client = TestClient(create_app(Settings(database_url="sqlite:///:memory:")))
    body = client.get("/api/v1/voice/capabilities").json()
    assert {row["language"] for row in body["languages"]} == {"te", "en", "hi", "ta", "kn", "ml", "mr"}
    assert all(row["interface_translation"] == "partial" for row in body["languages"])
    assert all("unavailable" in row["backend_stt"] and "unavailable" in row["backend_tts"] for row in body["languages"])
    assert "only when the backend master switch" in body["note"].lower()
    client.close()


def test_prisma_and_timbre_fixture_adapters_are_explicit_and_never_contact_providers():
    providers = build_container(Settings(speech_to_text_provider="prisma-fixture", text_to_speech_provider="timbre-fixture"))
    from app.schemas.features import SpeechToTextRequest, TextToSpeechRequest

    stt = providers.speech_to_text.transcribe(
        SpeechToTextRequest(filename="recording.wav", content_type="audio/wav", size_bytes=64, language="te"),
        b"arbitrary fixture audio bytes",
    )
    tts = providers.text_to_speech.synthesize(TextToSpeechRequest(text="నమస్కారం", language="te"))
    assert stt.is_mock and stt.language == "te" and "no provider was contacted" in stt.notice
    assert tts.is_mock and not tts.available and tts.language == "te" and "not synthesized" in tts.notice.lower() and "playable speech" in tts.notice.lower()


def test_fixture_stt_cannot_submit_its_placeholder_text_as_a_user_turn():
    client = TestClient(create_app(Settings(
        database_url="sqlite:///:memory:", speech_to_text_provider="prisma-fixture",
    )))
    conversation = client.post("/api/v1/voice/conversations", json={"language": "te"}).json()
    identifier = conversation["conversation_id"]
    wav = BytesIO()
    with wave.open(wav, "wb") as recording:
        recording.setnchannels(1); recording.setsampwidth(2); recording.setframerate(16000); recording.writeframes(b"\x00\x00" * 160)
    response = client.post(f"/api/v1/voice/conversations/{identifier}/audio",
        content=wav.getvalue(), headers={"Content-Type": "audio/wav"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is True
    assert body["transcribed"] is False
    assert body["text"] == ""
    assert body["turn"] is None
    assert "no provider was contacted" in body["notice"]
    client.close()
