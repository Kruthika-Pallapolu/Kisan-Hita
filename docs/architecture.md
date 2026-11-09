# Architecture

The approved `Kisan Hita.html` homepage remains a standalone file. The React application lives in `frontend/`; its API lives in `backend/`. Neither CWP nor the standalone homepage is part of this app's build.

## Frontend

React + TypeScript + Vite with React Router. `Layout.tsx` supplies feature navigation and the global language selector. `VoiceSessionProvider` preserves the selected language and conversation in browser storage. The backend stores conversation history and the farm location in SQLite through `ConversationRecord`. A shared assistant dock is available on feature pages; the homepage retains its larger voice interaction area. Feature forms live in `App.tsx`; HTTP contracts are in `src/services/api.ts` and `src/types/api.ts`. Translations are catalogued in `src/localization/index.ts`.

The interface offers Telugu, English, Hindi, Tamil, Kannada, Malayalam and Marathi. The translation catalog audit covers every catalog key, including weather, market, crop-health, error and voice workflow copy. The new farmer-facing copy is draft translated and requires fluent-speaker review; the audit verifies key coverage, not translation quality. Provider-owned names, official state names, and returned source citations may remain in their original language. Typed feature routing uses deterministic phrase lists; this is not general natural-language understanding.

## Backend

FastAPI exposes weather, crop-choice, crop-photo intake, market lookup, assistant, voice-session, health and OpenAPI routes. Pydantic contracts live in `schemas/`. Business services depend on the provider protocols in `providers/interfaces.py`; `services/container.py` selects adapters independently from environment settings.

`services/agent.py` is the shared server-side orchestrator for voice turns, assistant messages, and supported feature submissions. It routes deterministic intent results to weather, crop, market, or disease interfaces, applies validation and safety rules, and formats grounded results through `GroundedAnswerProvider`. The configured answer implementation is a deterministic template formatter, not a language model. The Open-Meteo adapter provides a geocoded current forecast and seven-day forecast. Crop recommendations refuse to recommend without verified farm-specific evidence; Warangal can receive historical Central Telangana crop/rainfall context only. The image intake validates and forwards image bytes to the configured disease interface; no reliable local image model is configured, so photo receipt is never described as diagnosis. The market interface can be configured with the optional data.gov.in AGMARKNET daily price adapter; it is disabled without explicit `MARKET_PROVIDER=datagov` and a backend API key, and its upstream contract has only offline mock tests.

The `SpeechToTextProvider` and `TextToSpeechProvider` contracts are used by audio endpoints. Default adapters are unavailable mocks. Optional fixture selections return explicitly marked fixture values and perform no audio processing or network request. Backend-only Prisma v2.5 REST and Timbre v2.5 REST adapter classes follow the official documented contracts, but are not selected by default and have only been tested against injected local `httpx.MockTransport` responses. Live selection fails closed unless `GNANI_LIVE_API_ENABLED=true`, the matching live provider name is selected, and a backend `GNANI_API_KEY` is present. No code path attempted a live request in this task. Browser speech recognition remains English-only; device speech output depends on an installed matching voice.

SQLite initializes the conversation table at app startup. Conversation history, selected language, current feature, farm location, bounded validated farm details, pending question and recent tool results are saved across requests and app reloads. Sessions expire after the configured `CONVERSATION_RETENTION_DAYS` (default 30, configurable from 1 to 365); each request also bounds retained turn history. Client turn IDs provide duplicate submission protection. The browser stores the conversation identifier and selected language. No account or cloud sync exists.

## Provider and safety boundaries

- Provider credentials belong only in backend configuration. No Gnani SDK or credential is checked into the project. Backend-only Prisma/Timbre adapters and documented endpoints exist, but no Gnani API was called, authenticated to, or initialized in development or tests.
- Provider selection uses `WEATHER_PROVIDER`, `CROP_PROVIDER`, `DISEASE_PROVIDER`, `MARKET_PROVIDER`, `LLM_PROVIDER`, `INTENT_PROVIDER`, `SPEECH_TO_TEXT_PROVIDER` and `TEXT_TO_SPEECH_PROVIDER`. `LLM_PROVIDER` currently selects the deterministic answer formatter and the legacy mock chat provider. Unsupported selections fail initialization; there is no paid-provider fallback.
- The development crop, disease, market, LLM, STT and TTS provider implementations are test mocks. Public feature routes do not present their fictional sample payloads as real results.
- Weather responses keep their date, source attribution, uncertainty, missing values and stale state. Official IMD alerts are not integrated.
- The free hosted Open-Meteo API is restricted to non-commercial use. It is not cleared for commercial production; a properly licensed source is required before that use.
- Image uploads are size-limited and inspected for declared image type and file signature. They are processed in memory and are not stored by this endpoint.
- CORS accepts only configured origins.

## Current limits

The feature pages and safe workflows exist, but this is not yet the requested complete agricultural assistant. Choose My Crop does not yet produce evidence-backed recommendations; Check My Crop does not identify plant diseases; Market Prices has no authorized live data adapter; and the assistant is a deterministic router and grounded template formatter, not a generative model. Only the weather feature can retrieve live external data in the current configuration. Backend audio endpoints include explicitly disabled live adapters; default providers remain unavailable mocks. WAV audio is duration-checked before STT. The frontend supports editable STT transcripts and backend TTS controls, but real voice quality has not been verified. Non-English voice is explicitly unverified until actual STT/TTS providers and their language coverage have been compatibility-tested.

The five features must be described with these limitations in any demonstration. Do not label mock output as live, or an absent capability as complete. Future adapter work should implement the existing backend protocols, retain the Pydantic route contracts, store secrets only on the backend, and add adapter contract tests that mock provider HTTP responses. Do not use real provider credentials in development tests.
