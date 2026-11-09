from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models.conversation import ConversationRecord
from app.schemas.features import ChatResponse
from app.schemas.voice import ConversationResponse, GroundedAnswerRequest, FeatureDestination, VoiceTurnResponse
from app.services.agent import AgentOrchestrator
from app.services.language import text


class VoiceService:
    """Persistent conversation lifecycle and request idempotency."""

    HISTORY_LIMIT = 40
    REQUEST_CACHE_LIMIT = 20
    FARM_DETAIL_LIMITS = {
        "state": 100, "district": 160, "soil_type": 80, "water_availability": 16,
        "season": 80, "priority": 100, "crop": 100, "growth_stage": 100,
        "spray_product": 160, "market": 160, "variety": 100,
    }

    @classmethod
    def _remember_details(cls, session: dict[str, object], values: dict[str, object] | None) -> None:
        if not values:
            return
        details = dict(session.get("farm_details", {}))
        for key, value in values.items():
            if value is None or key not in {*cls.FARM_DETAIL_LIMITS, "farm_size_acres"}:
                continue
            if key == "water_availability" and (not isinstance(value, str) or value not in {"rainfed", "limited", "assured"}):
                continue
            if key == "farm_size_acres":
                if isinstance(value, (int, float)) and 0 < value <= 100_000:
                    details[key] = float(value)
                continue
            if isinstance(value, str) and len(value.strip()) <= cls.FARM_DETAIL_LIMITS[key]:
                details[key] = value.strip()
        session["farm_details"] = details

    def __init__(self, agent: AgentOrchestrator, session_factory: sessionmaker[Session] | None = None,
                 retention_days: int = 30):
        self.agent = agent
        self.session_factory = session_factory
        self.retention_days = max(1, retention_days)
        self.sessions: dict[str, dict[str, object]] = {}

    def _expired(self, data: dict[str, object]) -> bool:
        timestamp = data.get("_updated_at")
        if not isinstance(timestamp, str):
            return False
        try:
            updated = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return updated < datetime.now(timezone.utc) - timedelta(days=self.retention_days)

    def _delete(self, conversation_id: str) -> None:
        self.sessions.pop(conversation_id, None)
        if self.session_factory is not None:
            with self.session_factory() as db:
                record = db.get(ConversationRecord, conversation_id)
                if record is not None:
                    db.delete(record)
                    db.commit()

    def _get(self, conversation_id: str) -> dict[str, object] | None:
        cached = self.sessions.get(conversation_id)
        if cached is not None:
            if self._expired(cached):
                self._delete(conversation_id)
                return None
            return cached
        if self.session_factory is None:
            return None
        with self.session_factory() as db:
            record = db.get(ConversationRecord, conversation_id)
            if record is None:
                return None
            data = dict(record.data)
            data.setdefault("_updated_at", record.updated_at.isoformat() if record.updated_at else datetime.now(timezone.utc).isoformat())
            if self._expired(data):
                db.delete(record)
                db.commit()
                return None
        self.sessions[conversation_id] = data
        return data

    def _save(self, conversation_id: str, data: dict[str, object]) -> None:
        data["_updated_at"] = datetime.now(timezone.utc).isoformat()
        self.sessions[conversation_id] = data
        if self.session_factory is None:
            return
        with self.session_factory() as db:
            db.merge(ConversationRecord(id=conversation_id, data=data))
            db.commit()

    @staticmethod
    def _response(conversation_id: str, session: dict[str, object]) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conversation_id,
            language=str(session["language"]),
            language_status="unverified",
            language_notice=text("voice_unavailable", str(session["language"])),
            farm_location=session.get("farm_location"),
            history=list(session.get("history", [])),
        )

    def create_conversation(self, language: str) -> ConversationResponse:
        conversation_id = str(uuid4())
        self._save(conversation_id, {
            "language": language, "last_intent": None, "turns": 0, "history": [],
            "active_feature": None, "farm_details": {}, "recent_tool_results": [],
            "pending_question": None, "turn_requests": [],
        })
        return self._response(conversation_id, self.sessions[conversation_id])

    def set_language(self, conversation_id: str, language: str) -> ConversationResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        session["language"] = language
        self._save(conversation_id, session)
        return self._response(conversation_id, session)

    def append_exchange(self, conversation_id: str, language: str, message: str, response: str, feature: str | None) -> ConversationResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        session["language"] = language
        history = list(session.get("history", []))
        history.extend([{"role": "farmer", "text": message}, {"role": "assistant", "text": response}])
        session["history"] = history[-self.HISTORY_LIMIT:]
        if feature:
            session["active_feature"] = feature
        self._save(conversation_id, session)
        return self._response(conversation_id, session)

    def append_assistant_response(self, conversation_id: str, language: str, response: str, feature: str | None) -> ConversationResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        session["language"] = language
        history = list(session.get("history", []))
        history.append({"role": "assistant", "text": response})
        session["history"] = history[-self.HISTORY_LIMIT:]
        if feature:
            session["active_feature"] = feature
        self._save(conversation_id, session)
        return self._response(conversation_id, session)

    def set_farm_location(self, conversation_id: str, state: str, district: str) -> ConversationResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        session["farm_location"] = {"state": state.strip(), "district": district.strip()}
        self._save(conversation_id, session)
        return self._response(conversation_id, session)

    def understand(self, conversation_id: str, message: str, client_turn_id: str | None = None,
                   tool_arguments: dict[str, object] | None = None) -> VoiceTurnResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        request_cache = list(session.get("turn_requests", []))
        if client_turn_id:
            cached = next((item for item in request_cache if item.get("id") == client_turn_id), None)
            if cached:
                return VoiceTurnResponse.model_validate(cached["response"])

        language = str(session["language"])
        was_pending_question = session.get("pending_question")
        self._remember_details(session, tool_arguments)
        result = self.agent.route(message, language, session, tool_arguments)
        session["last_intent"] = result.intent.value
        session["active_feature"] = result.destination.value
        session["turns"] = int(session.get("turns", 0)) + 1
        session["pending_question"] = message if result.clarification_required else None
        if result.tool_result:
            recent = list(session.get("recent_tool_results", []))
            recent.append({"question": message, **result.tool_result})
            session["recent_tool_results"] = recent[-5:]
            session["last_tool_result"] = result.tool_result
        history = list(session.get("history", []))
        resumed = bool(tool_arguments) and was_pending_question == message
        if resumed and len(history) >= 2 and history[-2].get("role") == "farmer" and history[-2].get("text") == message and history[-1].get("role") == "assistant":
            history[-1] = {"role": "assistant", "text": result.response}
        else:
            history.extend([{"role": "farmer", "text": message}, {"role": "assistant", "text": result.response}])
        session["history"] = history[-self.HISTORY_LIMIT:]
        if result.destination.value == "my-farm-today" and (result.tool_result or {}).get("status") == "needs_location":
            notice = text("weather_location_notice", language)
        else:
            notice = text("feature_evidence_notice", language)
        response = VoiceTurnResponse(
            conversation_id=conversation_id, language=language, result=result,
            feature_implemented=True,
            feature_notice=notice,
        )
        if client_turn_id:
            request_cache.append({"id": client_turn_id, "response": response.model_dump(mode="json")})
            session["turn_requests"] = request_cache[-self.REQUEST_CACHE_LIMIT:]
        self._save(conversation_id, session)
        return response

    def continue_pending(self, conversation_id: str, tool_arguments: dict[str, object] | None = None) -> VoiceTurnResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        pending = session.get("pending_question")
        if not isinstance(pending, str) or not pending.strip():
            return None
        language = str(session["language"])
        self._remember_details(session, tool_arguments)
        result = self.agent.route(pending, language, session, tool_arguments)
        session["last_intent"] = result.intent.value
        session["active_feature"] = result.destination.value
        session["pending_question"] = None if not result.clarification_required else pending
        history = list(session.get("history", []))
        history.append({"role": "assistant", "text": result.response})
        session["history"] = history[-self.HISTORY_LIMIT:]
        if result.tool_result:
            session["last_tool_result"] = result.tool_result
            recent = list(session.get("recent_tool_results", []))
            recent.append({"question": pending, **result.tool_result})
            session["recent_tool_results"] = recent[-5:]
        response = VoiceTurnResponse(conversation_id=conversation_id, language=language, result=result,
            feature_implemented=True, feature_notice=text("follow_up_notice", language))
        self._save(conversation_id, session)
        return response

    def record_tool_result(self, conversation_id: str, farmer_message: str,
                           feature: FeatureDestination, tool_result: dict[str, object]) -> ChatResponse | None:
        session = self._get(conversation_id)
        if session is None:
            return None
        language = str(session["language"])
        generated = self.agent.answer_generator.generate(GroundedAnswerRequest(
            original_question=farmer_message, language=language,
            conversation_context=list(session.get("history", []))[-16:],
            active_feature=feature.value, tool_name=feature,
            tool_result=tool_result,
            missing_information=list(tool_result.get("missing_information", [])),
            provenance=str(tool_result.get("source", "")) or None,
            instructions="Answer in the selected language using only this server-produced feature result. Do not diagnose or recommend treatment without reliable evidence.",
        ))
        history = list(session.get("history", []))
        history.extend([{"role": "farmer", "text": farmer_message}, {"role": "assistant", "text": generated.answer}])
        session["history"] = history[-self.HISTORY_LIMIT:]
        session["active_feature"] = feature.value
        session["last_tool_result"] = {key: value for key, value in tool_result.items() if key not in {"image_bytes", "image_base64"}}
        recent = list(session.get("recent_tool_results", []))
        recent.append({"question": farmer_message, **session["last_tool_result"]})
        session["recent_tool_results"] = recent[-5:]
        session["pending_question"] = None
        self._save(conversation_id, session)
        return ChatResponse(conversation_id=conversation_id, language=language,
            response=generated.answer, suggested_feature=feature.value,
            is_mock=generated.is_mock, source=generated.adapter_name,
            clarification_required=generated.clarification_required,
            tool_name=feature.value, tool_result=session["last_tool_result"],
            answer_supported=generated.supported_by_evidence, answer_mode=generated.adapter_name)
