"""Deterministic, fictional development providers. No external services are contacted."""
from base64 import b64encode
from app.schemas.features import (
    ChatRequest, ChatResponse, CropHealthRequest, CropHealthResponse, CropRecommendation,
    CropRequest, CropResponse, ExpectedYield, FarmTodayRequest, FarmTodayResponse,
    ForecastDay, MarketPriceRequest, MarketPriceResponse, SpeechToTextRequest,
    SpeechToTextResponse, TextToSpeechRequest, TextToSpeechResponse,
)
from app.schemas.voice import FeatureDestination, GroundedAnswerRequest, GroundedAnswerResponse, IntentRequest, IntentResult, VoiceIntent
from app.services.language import locale_key, text as localized

MOCK_NOTICE = "Fictional development sample only. Do not use this information to make farming decisions."


class MockWeatherProvider:
    def get_forecast(self, request: FarmTodayRequest) -> FarmTodayResponse:
        return FarmTodayResponse(
            location=request.location or ", ".join(value for value in (request.district, request.state) if value) or "Unselected farm",
            observed_at=None,
            forecast=[
                ForecastDay(date="2030-06-01", summary="Mock sample: partly cloudy", temperature_c=29, precipitation_mm=1.5),
                ForecastDay(date="2030-06-02", summary="Mock sample: light rain", temperature_c=27, precipitation_mm=4.0),
            ],
            advice=[],
            alerts=[],
            source="Fictional local development sample",
            is_mock=True,
            notice=MOCK_NOTICE,
        )


class MockCropRecommendationProvider:
    def recommend(self, request: CropRequest) -> CropResponse:
        water = request.water_availability or "limited"
        if water == "assured":
            crop, reason = "Sample crop A", "Selected only to exercise the assured-water path."
        elif water == "rainfed":
            crop, reason = "Sample crop B", "Selected only to exercise the rainfed path."
        else:
            crop, reason = "Sample crop C", "Selected only to exercise the limited-water path."
        recommendation = CropRecommendation(
            crop=crop,
            reasons=[reason, f"Submitted district: {request.district} (echoed for UI testing only)."],
            duration_days=90,
            water_requirement="Fictional sample value; not an agronomic recommendation.",
            cultivation_notes=["Mock note: this record is fabricated for interface testing."],
            expected_yield=ExpectedYield(value=1.0, unit="fictional sample units per acre", source="Fabricated test fixture"),
            confidence="low",
        )
        return CropResponse(
            recommendations=[recommendation],
            disclaimer=MOCK_NOTICE,
            source="Fictional deterministic development sample",
            is_mock=True,
        )


class MockCropDiseaseProvider:
    def analyze(self, request: CropHealthRequest, image: bytes = b"") -> CropHealthResponse:
        return CropHealthResponse(
            possible_conditions=[],
            guidance=[],
            needs_expert=True,
            uncertainty="No image was analyzed. This mock cannot identify crop conditions; ask a local agricultural expert.",
            source="Development mock (image analysis unavailable)",
            is_mock=True,
        )


class MockMarketDataProvider:
    def lookup(self, request: MarketPriceRequest) -> list[MarketPriceResponse]:
        return [
            MarketPriceResponse(
                crop=request.crop,
                market=request.market,
                variety=request.variety or "Fictional sample variety",
                price=1234.0,
                unit="fictional currency units per quintal",
                observed_at="2030-06-01T09:00:00Z",
                source="Fabricated test fixture — not a market quote",
                is_mock=True,
            )
        ]


class MockLanguageModelProvider:
    def respond(self, request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        suggested = "my-farm-today" if any(word in text.lower() for word in ("weather", "rain", "forecast")) else None
        return ChatResponse(
            conversation_id=request.conversation_id or "mock-conversation",
            language=request.language,
            response="Mock reply for conversation-flow testing only. No farming advice was generated.",
            suggested_feature=suggested,
            is_mock=True,
            source="Deterministic local development mock",
        )


class DeterministicGroundedAnswerProvider:
    """Non-LLM development formatter; returns tool evidence or its safe limitation."""

    def generate(self, request: GroundedAnswerRequest) -> GroundedAnswerResponse:
        tool_result = request.tool_result
        answer = tool_result.get("answer") or localized("general", request.language)
        return GroundedAnswerResponse(
            answer=str(answer), language=request.language,
            supported_by_evidence=bool(tool_result.get("supported")),
            clarification_required=bool(tool_result.get("clarification_required")),
            adapter_name="deterministic-grounded-template", is_mock=True,
        )


class MockSpeechToTextProvider:
    def transcribe(self, request: SpeechToTextRequest, audio: bytes) -> SpeechToTextResponse:
        return SpeechToTextResponse(
            text="",
            language=request.language,
            is_mock=True,
            source="Deterministic local development mock",
            notice="No audio was transcribed. This development provider ignores submitted audio bytes.",
        )


class PrismaFixtureSpeechToTextProvider:
    """Fixture adapter shaped like Prisma REST; never reads audio or uses network."""

    def transcribe(self, request: SpeechToTextRequest, audio: bytes) -> SpeechToTextResponse:
        del audio
        return SpeechToTextResponse(text="FIXTURE ONLY — no audio was transcribed", language=request.language,
            is_mock=True, source="Prisma-compatible local fixture", notice="Fixture response only; audio was not processed and no provider was contacted.")


class DeterministicIntentProvider:
    """Small on-device keyword router; not a general language model."""
    SEASONAL_CROP_CUES = {
        "en": ("plant this season", "which crops suit", "what crops suit"),
        "te": ("ఈ సీజన్‌లో ఏ పంట", "ఖరీఫ్ పంట", "రబీ పంట"),
        "hi": ("इस मौसम में कौन सी फसल", "खरीफ फसल", "रबी फसल"),
        "ta": ("இந்த பருவத்தில் எந்த பயிர்", "காரீஃப் பயிர்", "ரபி பயிர்"),
        "kn": ("ಈ ಋತುವಿನಲ್ಲಿ ಯಾವ ಬೆಳೆ", "ಖರೀಫ್ ಬೆಳೆ", "ರಬಿ ಬೆಳೆ"),
        "ml": ("ഈ സീസണിൽ ഏത് വിള", "ഖാരിഫ് വിള", "റാബി വിള"),
        "mr": ("या हंगामात कोणते पीक", "खरीप पीक", "रब्बी पीक"),
    }
    GENERAL_PHRASES = {
        "en": ("soil health", "soil test", "soil card", "fertilizer", "fertiliser", "urea", "irrigation", "watering schedule", "prepare the soil", "soil preparation", "pest prevention", "pest control", "prevent pests", "prevent pest", "growth stage", "crop growth"),
        "te": ("నేల ఆరోగ్య", "నేల పరీక్ష", "ఎరువు", "నీటి షెడ్యూల్", "పురుగు నివారణ", "నేల తయారీ", "పెరుగుదల దశ"),
        "hi": ("मृदा स्वास्थ्य", "मिट्टी स्वास्थ्य", "खाद", "उर्वरक", "सिंचाई", "कीट से बचाव", "कीट नियंत्रण", "मिट्टी तैयार", "वृद्धि अवस्था"),
        "ta": ("மண் சுகாதார", "மண் பரிசோதனை", "உரம்", "நீர்ப்பாசனம்", "பூச்சி தடுப்பு", "மண் தயாரிப்பு", "வளர்ச்சி நிலை"),
        "kn": ("ಮಣ್ಣಿನ ಆರೋಗ್ಯ", "ಮಣ್ಣಿನ ಪರೀಕ್ಷೆ", "ಗೊಬ್ಬರ", "ನೀರಾವರಿ", "ಕೀಟ ನಿಯಂತ್ರಣ", "ಮಣ್ಣಿನ ಸಿದ್ಧತೆ", "ಬೆಳವಣಿಗೆಯ ಹಂತ"),
        "ml": ("മണ്ണിന്റെ ആരോഗ്യ", "മണ്ണ് പരിശോധന", "വളം", "ജലസേചനം", "കീട നിയന്ത്രണം", "മണ്ണൊരുക്കം", "വളർച്ചാഘട്ടം"),
        "mr": ("मृदा आरोग्य", "मातीची तपासणी", "खत", "सिंचन", "कीड नियंत्रण", "मशागत", "वाढीची अवस्था"),
    }
    RULES = {
        "en": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("weather", "rain", "forecast", "water my field", "water today", "spray pesticide", "spray pesticides", "safe to spray", "should i spray", "spray today", "heavy rain")),
               (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("which crop", "what crop", "cultivate", "grow", "crop should", "plant this season", "which crops suit", "what crops suit")),
               (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("yellow", "spots", "eating my plants", "disease", "crop leaves", "pest")),
               (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("price", "market", "mandi", "sell my", "compare market"))),
        "te": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("వాతావరణ", "వర్ష")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("ఏ పంట", "పంట వేయ", "పంట పండ", "ఈ సీజన్‌లో పంట", "ఖరీఫ్ పంట", "రబీ పంట")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("ఆకుల", "మచ్చ", "పురుగు", "తెగులు")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("ధర", "మార్కెట్"))),
        "hi": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("मौसम", "बारिश", "वर्षा")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("कौन सी फसल", "कौनसा फसल", "फसल उग", "बोना", "इस मौसम में कौन सी फसल", "खरीफ फसल", "रबी फसल")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("पत्ते", "पीले", "रोग", "कीड़ा")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("भाव", "मंडी", "बाजार भाव"))),
        "ta": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("வானிலை", "மழை")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("எந்தப் பயிர்", "என்ன பயிர்", "பயிரிட", "இந்த பருவத்தில் எந்த பயிர்", "காரீஃப் பயிர்", "ரபி பயிர்")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("இலை", "நோய்", "பூச்சி")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("விலை", "சந்தை"))),
        "kn": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("ಹವಾಮಾನ", "ಮಳೆ")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("ಯಾವ ಬೆಳೆ", "ಬೆಳೆ ಬೆಳೆಯ", "ಈ ಋತುವಿನಲ್ಲಿ ಯಾವ ಬೆಳೆ", "ಖರೀಫ್ ಬೆಳೆ", "ರಬಿ ಬೆಳೆ")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("ಎಲೆ", "ರೋಗ", "ಕೀಟ")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("ಬೆಲೆ", "ಮಾರುಕಟ್ಟೆ"))),
        "ml": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("കാലാവസ്ഥ", "മഴ")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("ഏത് വിള", "വിള കൃഷി", "ഈ സീസണിൽ ഏത് വിള", "ഖാരിഫ് വിള", "റാബി വിള")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("ഇല", "രോഗം", "കീടം")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("വില", "വിപണി"))),
        "mr": ((VoiceIntent.MY_FARM_TODAY, FeatureDestination.MY_FARM_TODAY, ("हवामान", "पाऊस")), (VoiceIntent.CHOOSE_MY_CROP, FeatureDestination.CHOOSE_MY_CROP, ("कोणते पीक", "पीक घ्यावे", "लागवड", "या हंगामात कोणते पीक", "खरीप पीक", "रब्बी पीक")), (VoiceIntent.CHECK_MY_CROP, FeatureDestination.CHECK_MY_CROP, ("पान", "रोग", "कीड")), (VoiceIntent.MARKET_PRICES, FeatureDestination.MARKET_PRICES, ("भाव", "बाजारभाव"))),
    }

    def understand(self, request: IntentRequest) -> IntentResult:
        text = request.message.strip().lower()
        language = locale_key(request.language)
        if any(cue in text for cue in self.SEASONAL_CROP_CUES[language]):
            return IntentResult(intent=VoiceIntent.CHOOSE_MY_CROP, destination=FeatureDestination.CHOOSE_MY_CROP,
                entities={"request_text": request.message}, confidence=0.82,
                clarification_required=False, response=localized("general", language),
                language=request.language, response_language=request.language,
                language_notice=localized("voice_unavailable", language) if language != "en" else None)
        if any(phrase in text for phrase in self.GENERAL_PHRASES[language]):
            return IntentResult(intent=VoiceIntent.ASK_KISAN_HITA, destination=FeatureDestination.ASK_KISAN_HITA,
                confidence=0.74, entities={"request_text": request.message}, clarification_required=False,
                response=localized("general", language), language=request.language, response_language=request.language,
                language_notice=localized("voice_unavailable", language) if language != "en" else None)
        for intent, destination, phrases in self.RULES[language]:
            if any(phrase in text for phrase in phrases):
                confidence = 0.82 if len(text) > 12 else 0.68
                return IntentResult(intent=intent, destination=destination, confidence=confidence,
                    entities={"request_text": request.message},
                    clarification_required=False,
                    response=("I’ll use weather for your saved farm location." if destination == FeatureDestination.MY_FARM_TODAY else localized("general", language)),
                    language=request.language, response_language=request.language,
                    language_notice=localized("voice_unavailable", language) if language != "en" else None)
        previous = request.context.get("last_intent") or request.context.get("active_feature")
        followups = {"en": ("then", "today", "that", "it", "what about", "how about", "day after tomorrow", "after tomorrow"), "te": ("అయితే", "రేపు", "మరి", "ఎల్లుండి"), "hi": ("तो", "कल", "फिर", "परसों"), "ta": ("அப்படியெனில்", "நாளை", "நாளை மறுநாள்"), "kn": ("ಹಾಗಾದರೆ", "ನಾಳೆ", "ನಾಡಿದ್ದು"), "ml": ("അപ്പോൾ", "നാളെ", "മറ്റന്നാൾ"), "mr": ("मग", "उद्या", "परवा")}
        if previous in {VoiceIntent.MY_FARM_TODAY.value, FeatureDestination.MY_FARM_TODAY.value} and any(word in text for word in followups[language]):
            return IntentResult(intent=VoiceIntent.MY_FARM_TODAY, destination=FeatureDestination.MY_FARM_TODAY,
                entities={"request_text": request.message, "follow_up": True}, confidence=0.62,
                clarification_required=True, response="I’m keeping this with your earlier farm weather question. What would you like to know about it?",
                language=request.language, response_language=request.language,
                language_notice=localized("voice_unavailable", language) if language != "en" else None)
        if len(text) < 3:
            response = localized("general", language)
            clarification = True
        else:
            response = localized("general", language)
            clarification = True
        return IntentResult(intent=VoiceIntent.ASK_KISAN_HITA, destination=FeatureDestination.ASK_KISAN_HITA,
            entities={"request_text": request.message}, confidence=0.2, clarification_required=clarification,
            response=response, language=request.language, response_language=request.language,
            language_notice=localized("voice_unavailable", language) if language != "en" else None)


class MockTextToSpeechProvider:
    def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResponse:
        return TextToSpeechResponse(
            available=False,
            language=request.language,
            is_mock=True,
            source="Local development mock",
            notice="Audio generation is unavailable in the mock implementation.",
        )


class TimbreFixtureTextToSpeechProvider:
    """Fixture adapter with the backend contract; no synthesis service is contacted."""

    def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResponse:
        # A tiny syntactically bounded base64 fixture for contract tests only.
        return TextToSpeechResponse(available=False, language=request.language, audio_base64=b64encode(b"fixture-audio-not-playable").decode("ascii"),
            is_mock=True, source="Timbre-compatible local fixture", notice="Fixture only; this is not synthesized or playable speech.")
