# Controlled Gnani speech test

This is an operator runbook only. The application defaults to local/mock speech. No live request is part of unit tests, frontend tests, or the build. Never put the API key in `frontend/.env`, a Vite variable, source control, or a browser request.

## Enable only for one deliberate test

Obtain the challenge API credential from the provider dashboard and check the current credit balance first. In a private terminal, from `backend/`, set these values only for the backend process:

```sh
export GNANI_LIVE_API_ENABLED=true
export GNANI_API_KEY='your-provider-key'
export SPEECH_TO_TEXT_PROVIDER=prisma-live
export TEXT_TO_SPEECH_PROVIDER=timbre-live
PYTHONPATH=. .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The flags are opt-in. Both provider categories are selected separately; configuring only one leaves the other on its configured provider. Stop the backend after the test and unset the variables. Do not use these settings in automated tests or a shared development server.

## Minimum first test

1. Record one short (3–5 second), clear WAV question in a supported language, under 30 seconds and the configured upload-size cap.
2. Submit that one recording once. Check the transcript before pressing **Send**. Do not retry automatically if the request times out; first check the provider dashboard and backend logs.
3. Request speech for one short answer once and play it once.
4. Check the provider dashboard usage/credit balance after each request. Confirm how STT duration and TTS output are charged before doing more tests. The challenge offers programme credits, but this project does not infer a price-per-request or guarantee that a call is free.
5. Stop the backend and remove the live environment variables. Confirm the ordinary server starts with mock providers.

Live tests are intentionally not automated. Error/timeout responses can be ambiguous about provider-side processing, so do not add retries or call both models repeatedly.

## Contract and limits

The speech adapters use the challenge REST APIs. Prisma v2.5 is the model listed for the challenge; `/stt/v3` is the documented REST path and does not mean model v3. The adapter omits the optional model selector so the endpoint uses its documented v2.5 default. The frontend normalizes recorded audio to WAV, and the server validates WAV structure and enforces 30 seconds before provider submission. Timbre uses the v2.5 model and a language-specific listed voice. Provider requests are made only by backend adapters; failures do not invent transcripts or audio.

All seven configured languages are listed in provider language/voice documentation, but that does not establish end-to-end quality. Fluent-speaker review and actual audio tests are still required. Translation drafts also require fluent-speaker review.
