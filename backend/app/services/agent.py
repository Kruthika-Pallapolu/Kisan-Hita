"""Single, provider-independent orchestration layer for farmer turns.

The current answer adapter is deterministic: it formats validated evidence or
asks for missing information. It is deliberately not presented as an LLM.
"""
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from app.providers.interfaces import (
    CropDiseaseProvider, CropRecommendationProvider, IntentUnderstandingProvider,
    MarketDataProvider, WeatherProvider, GroundedAnswerProvider,
)
from app.schemas.features import CropHealthRequest, CropHealthResponse, CropRequest, CropResponse, FarmTodayRequest, MarketPriceRequest
from app.schemas.voice import FeatureDestination, GroundedAnswerRequest, IntentRequest, IntentResult
from app.services.language import locale_key, text as localized, weather_answer
from app.services.crop_evidence import attach_regional_context


class AgentOrchestrator:
    def __init__(self, *, intent: IntentUnderstandingProvider, weather: WeatherProvider,
                 crops: CropRecommendationProvider, disease: CropDiseaseProvider,
                 market: MarketDataProvider, answer_generator: GroundedAnswerProvider):
        self.intent = intent
        self.weather = weather
        self.crops = crops
        self.disease = disease
        self.market = market
        self.answer_generator = answer_generator

    def route(self, message: str, language: str, session: dict[str, object],
              tool_arguments: dict[str, object] | None = None) -> IntentResult:
        history = list(session.get("history", []))
        intent = self.intent.understand(IntentRequest(
            message=message, language=language,
            context={"last_intent": session.get("last_intent"), "active_feature": session.get("active_feature"),
                     "farm_location": session.get("farm_location"), "history": history[-8:],
                     "pending_question": session.get("pending_question"),
                     "last_tool_result": session.get("last_tool_result")},
        ))
        destination = intent.destination
        result: dict[str, object] = {"tool": destination.value, "status": "unavailable", "supported": False}
        saved_arguments = session.get("farm_details")
        args = {**(saved_arguments if isinstance(saved_arguments, dict) else {}), **(tool_arguments or {})}
        if destination == FeatureDestination.MY_FARM_TODAY:
            result = self._weather(message, language, session, args)
        elif destination == FeatureDestination.CHOOSE_MY_CROP:
            result = self._crop(language, args)
        elif destination == FeatureDestination.MARKET_PRICES:
            result = self._market(language, args)
        elif destination == FeatureDestination.CHECK_MY_CROP:
            result = {**result, "status": "needs_image", "answer": localized("image_help", language)}
        else:
            result = self._general(message, language)

        answer_result = self.answer_generator.generate(GroundedAnswerRequest(
            original_question=message, language=language, conversation_context=history[-16:],
            active_feature=str(session.get("active_feature")) if session.get("active_feature") else None,
            tool_name=destination, tool_result=result,
            missing_information=list(result.get("missing_information", [])),
            timestamp=str(result["timestamp"]) if result.get("timestamp") else None,
            provenance=str(result["source"]) if result.get("source") else None,
        ))
        answer = answer_result.answer
        supported = answer_result.supported_by_evidence
        clarification = answer_result.clarification_required or bool(result.get("clarification_required")) or (
            destination == FeatureDestination.ASK_KISAN_HITA and intent.confidence < 0.5 and not supported
        )
        return intent.model_copy(update={
            "response": answer,
            "response_language": language,
            "clarification_required": clarification,
            "tool_name": destination,
            "tool_result": {key: value for key, value in result.items() if key != "answer"},
            "answer_supported": supported,
            "answer_mode": answer_result.adapter_name,
            "source": str(result.get("source") or "Deterministic local language templates"),
        })

    @staticmethod
    def _general(message: str, language: str) -> dict[str, object]:
        """Answer bounded general topics from reviewed templates; do not generate farm-specific advice."""
        locale = locale_key(language)
        text = message.casefold()
        topic_terms = {
            "soil": {
                "en": ("soil health", "soil test", "soil card", "soil health card"), "te": ("నేల ఆరోగ్య", "నేల పరీక్ష"),
                "hi": ("मिट्टी स्वास्थ्य", "मृदा स्वास्थ्य", "मिट्टी की जाँच"), "ta": ("மண் சுகாதார", "மண் பரிசோதனை"),
                "kn": ("ಮಣ್ಣಿನ ಆರೋಗ್ಯ", "ಮಣ್ಣಿನ ಪರೀಕ್ಷೆ"), "ml": ("മണ്ണിന്റെ ആരോഗ്യ", "മണ്ണ് പരിശോധന"),
                "mr": ("मृदा आरोग्य", "मातीची तपासणी"),
            },
            "fertilizer": {
                "en": ("fertilizer", "fertiliser", "fertilizer", "urea", "npk", "manure"), "te": ("ఎరువు", "యూరియా"),
                "hi": ("खाद", "उर्वरक", "यूरिया"), "ta": ("உரம்", "யூரியா"), "kn": ("ಗೊಬ್ಬರ", "ಯೂರಿಯಾ"),
                "ml": ("വളം", "യൂറിയ"), "mr": ("खत", "युरिया"),
            },
            "irrigation": {
                "en": ("irrigation", "irrigate", "watering schedule", "water my crop"), "te": ("నీటి షెడ్యూల్", "నీరు ఎప్పుడు"),
                "hi": ("सिंचाई", "पानी कब"), "ta": ("நீர்ப்பாசனம்", "எப்போது நீர்"), "kn": ("ನೀರಾವರಿ", "ನೀರು ಯಾವಾಗ"),
                "ml": ("ജലസേചനം", "എപ്പോൾ വെള്ളം"), "mr": ("सिंचन", "पाणी कधी"),
            },
            "soil_prep": {
                "en": ("prepare the soil", "soil preparation", "plough", "plow", "field preparation"),
                "te": ("నేల తయారీ", "దున్న"), "hi": ("मिट्टी तैयार", "खेत की तैयारी", "जुताई"),
                "ta": ("மண் தயாரிப்பு", "உழவு"), "kn": ("ಮಣ್ಣಿನ ಸಿದ್ಧತೆ", "ಉಳುಮೆ"),
                "ml": ("മണ്ണൊരുക്കം", "നിലം ഒരുക്ക"), "mr": ("मशागत", "जमीन तयार"),
            },
            "pest": {
                "en": ("pest prevention", "pest control", "prevent pests", "insect", "pest"),
                "te": ("పురుగు నివారణ", "పురుగు నియంత్రణ", "పురుగు"), "hi": ("कीट से बचाव", "कीट नियंत्रण", "कीट"),
                "ta": ("பூச்சி தடுப்பு", "பூச்சி கட்டுப்பாடு", "பூச்சி"), "kn": ("ಕೀಟ ನಿಯಂತ್ರಣ", "ಕೀಟ ತಡೆ", "ಕೀಟ"),
                "ml": ("കീട നിയന്ത്രണം", "കീട പ്രതിരോധം", "കീടം"), "mr": ("कीड नियंत्रण", "कीड प्रतिबंध", "कीड"),
            },
            "growth": {
                "en": ("growth stage", "growing stage", "crop stage", "crop growth"), "te": ("పెరుగుదల దశ", "పంట దశ"),
                "hi": ("वृद्धि अवस्था", "फसल की अवस्था", "फसल का चरण"), "ta": ("வளர்ச்சி நிலை", "பயிர் நிலை"),
                "kn": ("ಬೆಳವಣಿಗೆಯ ಹಂತ", "ಬೆಳೆಯ ಹಂತ"), "ml": ("വളർച്ചാഘട്ടം", "വിളയുടെ ഘട്ടം"),
                "mr": ("वाढीची अवस्था", "पिकाची अवस्था"),
            },
        }
        selected = next((topic for topic, translations in topic_terms.items()
                         if any(term in text for term in translations.get(locale, translations["en"]))), None)
        if selected == "soil":
            return {"tool": "ask-kisan-hita", "status": "soil-health-reference", "topic": selected,
                    "supported": True, "clarification_required": False,
                    "answer": localized("soil_health_info", language),
                    "source": "Government of India Soil Health Card FAQ — https://soilhealth.dac.gov.in/files/FAQ_Final_English.pdf"}
        if selected == "fertilizer":
            return {"tool": "ask-kisan-hita", "status": "soil-test-based-fertilizer-caution", "topic": selected,
                    "supported": True, "clarification_required": False,
                    "answer": localized("fertilizer_safety", language),
                    "source": "Government of India Soil Health Card FAQ — https://soilhealth.dac.gov.in/files/FAQ_Final_English.pdf"}
        if selected:
            answer_key = {"irrigation": "irrigation_details", "soil_prep": "soil_prep_details",
                          "pest": "pest_details", "growth": "growth_details"}[selected]
            return {"tool": "ask-kisan-hita", "status": "needs-topic-details", "topic": selected,
                    "supported": False, "clarification_required": True,
                    "missing_information": ["crop and local field details"], "answer": localized(answer_key, language),
                    "source": "No farm-specific recommendation available; contact a local KVK or agriculture officer."}
        return {"tool": "ask-kisan-hita", "status": "general", "supported": False,
                "clarification_required": True, "answer": localized("general", language),
                "source": "Deterministic local language templates; no generative model was used."}

    def _weather(self, question: str, language: str, session: dict[str, object], arguments: dict[str, object]) -> dict[str, object]:
        asks_spray = any(word in question.lower() for word in ("spray", "pesticide", "spraying", "పిచికారీ", "మందు కొట్ట", "छिड़क", "फवार", "தெளிக்க", "ಸಿಂಪಡ", "തളിക്ക"))
        spray_fields = {key: str(arguments[key]).strip() for key in ("crop", "growth_stage", "spray_product") if arguments.get(key)}
        missing_spray = [key for key in ("crop", "growth_stage", "spray_product") if not spray_fields.get(key)]
        if asks_spray and missing_spray:
            return {"tool": "my-farm-today", "status": "needs_spray_details", "supported": False,
                    "clarification_required": True, "missing_information": missing_spray,
                    "answer": localized("spray_details", language)}
        location = session.get("farm_location")
        if not isinstance(location, dict) or not location.get("state") or not location.get("district"):
            return {"tool": "my-farm-today", "status": "needs_location", "supported": False,
                    "clarification_required": True, "missing_information": ["farm state and district"],
                    "answer": localized("weather_location", language)}
        try:
            forecast = self.weather.get_forecast(FarmTodayRequest(
                state=str(location["state"]), district=str(location["district"]),
                question=question, language=language, **spray_fields,
            ))
        except Exception:
            return {"tool": "my-farm-today", "status": "provider_unavailable", "supported": False,
                    "answer": localized("weather_unavailable", language)}
        if forecast.is_mock:
            return {"tool": "my-farm-today", "status": "development_sample", "supported": False,
                    "source": forecast.source, "answer": localized("weather_unavailable", language)}
        index = self._forecast_index(question, language)
        day = forecast.forecast[index] if index < len(forecast.forecast) else None
        if day is None:
            return {"tool": "my-farm-today", "status": "missing_forecast_day", "supported": False,
                    "source": forecast.source, "timestamp": forecast.fetched_at.isoformat() if forecast.fetched_at else None,
                    "answer": localized("weather_unavailable", language)}
        answer = weather_answer(
            forecast.district or forecast.location,
            self._day_label(index, language), day.precipitation_probability,
            day.summary, day.temperature_c, language,
        )
        if asks_spray:
            answer = localized("spray_caution", language) + " " + answer
        if forecast.is_stale:
            answer = localized("weather_stale", language) + " " + answer
        return {"tool": "my-farm-today", "status": "completed", "supported": day.precipitation_probability is not None,
                "answer": answer, "source": forecast.source,
                "timestamp": forecast.fetched_at.isoformat() if forecast.fetched_at else None,
                "location": forecast.resolved_place or forecast.location,
                "geographic_resolution": forecast.geographic_resolution,
                "is_stale": forecast.is_stale, "is_forecast_not_warning": True,
                "day": day.model_dump(mode="json"),
                "forecast_data": forecast.model_dump(mode="json")}

    @staticmethod
    def _forecast_index(question: str, language: str) -> int:
        text = question.lower()
        after = {"en": ("day after tomorrow",), "te": ("ఎల్లుండి",), "hi": ("परसों",), "ta": ("நாளை மறுநாள்",), "kn": ("ನಾಡಿದ್ದು",), "ml": ("മറ്റന്നാൾ",), "mr": ("परवा",)}
        tomorrow = {"en": ("tomorrow",), "te": ("రేపు",), "hi": ("कल",), "ta": ("நாளை",), "kn": ("ನಾಳೆ",), "ml": ("നാളെ",), "mr": ("उद्या",)}
        locale = locale_key(language)
        return 2 if any(word in text for word in after[locale]) else 1 if any(word in text for word in tomorrow[locale]) else 0

    @staticmethod
    def _day_label(index: int, language: str) -> str:
        labels = {0: "the forecast period", 1: "tomorrow", 2: "the day after tomorrow"}
        return labels.get(index, "the forecast period")

    def _crop(self, language: str, arguments: dict[str, object]) -> dict[str, object]:
        try:
            request = CropRequest.model_validate({**arguments, "language": language})
        except ValidationError as error:
            invalid_fields = {str(issue["loc"][0]) for issue in error.errors() if issue.get("loc")}
            missing_required = invalid_fields.intersection({"district", "season"})
            if missing_required == {"district", "season"}:
                prompt = localized("crop_need_both", language)
            elif missing_required == {"district"}:
                prompt = localized("crop_need_district", language)
            elif missing_required == {"season"}:
                prompt = localized("crop_need_season", language)
            else:
                prompt = localized("crop_invalid", language)
            return {"tool": "choose-my-crop", "status": "needs_details", "supported": False,
                    "clarification_required": True, "answer": prompt}
        try:
            response = self.crops.recommend(request)
        except Exception:
            response = None
        if response is None or response.is_mock:
            response = CropResponse(
                recommendations=[], disclaimer=localized("crop_no_evidence", language),
                source="No current crop guidance is available.", is_mock=False,
                outcome="no_applicable_evidence",
            )
        verified = (response.outcome == "verified_recommendation" and bool(response.recommendations)
                and any(item.evidence_type == "current_recommendation" for item in response.evidence)
                and response.recommendation_ready and not response.is_mock)
        if not verified:
            if response.outcome == "verified_recommendation":
                response.outcome = "no_applicable_evidence"
                response.disclaimer = localized("crop_no_evidence", language)
            response.recommendations = []
            response.recommendation_ready = False
        response = attach_regional_context(response, request)
        outcome_status = {
            "verified_recommendation": "verified_recommendation",
            "regional_context_only": "regional_context_only",
            "no_applicable_evidence": "no_verified_data",
        }[response.outcome]
        result: dict[str, object] = {
            "tool": "choose-my-crop", "status": outcome_status, "supported": verified,
            "source": response.source, "answer": response.disclaimer,
            "outcome": response.outcome,
            "recommendations": [item.model_dump(mode="json") for item in response.recommendations],
            "evidence": [item.model_dump(mode="json") for item in response.evidence],
            "catalog_version": response.catalog_version,
            "missing_conditions": response.missing_conditions,
            "evidence_issue": response.evidence_issue,
            "regional_context": response.regional_context,
        }
        if response.missing_conditions:
            result["clarification_required"] = True
        return result

    def assess_crop_image(self, request: CropHealthRequest, image: bytes, language: str) -> tuple[CropHealthResponse, dict[str, object]]:
        """Run the image tool and return explicit evidence for the grounded answer layer."""
        provider_result = self.disease.analyze(request, image)
        if provider_result.is_mock:
            tool_result: dict[str, object] = {
                "tool": "check-my-crop", "status": "no_classifier", "supported": False,
                "source": "No image-analysis model is configured.",
                "answer": localized("image_uncertain", language),
                "crop": request.crop, "symptoms": request.symptoms,
                "filename": request.filename, "content_type": request.content_type,
                "size_bytes": request.size_bytes, "diagnosis_made": False,
            }
            return CropHealthResponse(
                possible_conditions=[], guidance=[localized("image_help", language)],
                needs_expert=True, uncertainty=localized("image_uncertain", language),
                source="No image-analysis model is configured; no diagnosis was made.", is_mock=False,
            ), tool_result
        condition_text = "; ".join(f"{item.name} ({round(item.confidence * 100)}%)" for item in provider_result.possible_conditions)
        answer = provider_result.uncertainty
        if condition_text:
            answer = f"The image service returned these possibilities: {condition_text}. {answer}"
        tool_result = {
            "tool": "check-my-crop", "status": "completed", "supported": bool(provider_result.possible_conditions),
            "source": provider_result.source, "answer": answer,
            "conditions": [item.model_dump(mode="json") for item in provider_result.possible_conditions],
            "guidance": provider_result.guidance, "uncertainty": provider_result.uncertainty,
            "needs_expert": provider_result.needs_expert, "diagnosis_made": bool(provider_result.possible_conditions),
        }
        return provider_result, tool_result

    def _market(self, language: str, arguments: dict[str, object]) -> dict[str, object]:
        try:
            request = MarketPriceRequest.model_validate({**arguments, "language": language})
        except ValidationError:
            return {"tool": "market-prices", "status": "needs_details", "supported": False,
                    "clarification_required": True, "missing_information": ["crop and market"],
                    "answer": localized("market_details", language)}
        try:
            records = [record for record in self.market.lookup(request) if not record.is_mock]
        except Exception:
            records = []
        now = datetime.now(timezone.utc)
        fresh = [record for record in records if (record.observed_at.replace(tzinfo=timezone.utc) if record.observed_at.tzinfo is None else record.observed_at) >= now - timedelta(days=7)]
        if not fresh:
            if records:
                stale_answer = localized("market_stale", language) + " " + "; ".join(
                    f"{record.crop} in {record.market}: {record.price} {record.unit}, reported {record.observed_at.date().isoformat()}"
                    for record in records
                ) + f" Source: {'; '.join(sorted({record.source for record in records}))}."
                return {"tool": "market-prices", "status": "stale_data", "supported": False,
                        "source": "; ".join(sorted({record.source for record in records})),
                        "timestamp": max(record.observed_at for record in records).isoformat(),
                        "prices": [record.model_dump(mode="json") for record in records],
                        "answer": stale_answer}
            return {"tool": "market-prices", "status": "no_verified_data", "supported": False,
                    "source": "No authorized live price feed returned current records.",
                    "answer": localized("market_unavailable", language)}
        records_data = [record.model_dump(mode="json") for record in fresh]
        return {"tool": "market-prices", "status": "completed", "supported": True,
                "source": "; ".join(sorted({record.source for record in fresh})),
                "timestamp": max(record.observed_at for record in fresh).isoformat(),
                "prices": records_data,
                "answer": localized("market_available", language) + " " + "; ".join(
                    f"{record.crop} in {record.market}: {record.price} {record.unit}, reported {record.observed_at.date().isoformat()}"
                    for record in fresh
                ) + f" Source: {'; '.join(sorted({record.source for record in fresh}))}."}
