# Kisan Hita

Kisan Hita is a multilingual farmer-facing prototype with a React/Vite frontend and a FastAPI backend. The original `Kisan Hita.html` is retained as a reference artifact; the running application is the frontend in `frontend/`.

## Requirements

- Node.js 20 or newer and npm
- Python 3.11 or newer
- PostgreSQL for a persistent hosted deployment (local development may use SQLite)

## Local setup

From the project root, install frontend dependencies and prepare a backend virtual environment:

```sh
cd frontend && npm ci
cd ../backend && python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the backend in one terminal:

```sh
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```sh
cd frontend
npm run dev
```

The frontend is at http://localhost:5173. The backend health endpoint is http://127.0.0.1:8000/api/v1/health. The frontend defaults to `http://127.0.0.1:8000/api/v1`; override it at build time with `VITE_API_BASE_URL` when the backend is hosted elsewhere.

## Configuration and credentials

Copy `.env.example` as a reference for backend environment variable names. The application does not automatically load `.env`; configure variables in the shell or hosting provider. Keep real environment files local and untracked. Never put provider keys in frontend variables or any `VITE_` variable.

By default, `GNANI_LIVE_API_ENABLED=false` and the voice provider selectors use local mocks. For an explicitly approved live voice deployment, set `GNANI_LIVE_API_ENABLED=true`, `SPEECH_TO_TEXT_PROVIDER=prisma-live`, `TEXT_TO_SPEECH_PROVIDER=timbre-live`, and provide `GNANI_API_KEY` only in the backend environment. Do not set a key in frontend configuration. Gemini/reasoning provider keys, if introduced, must likewise remain server-side.

## Render deployment

Deploy the backend as a Render **Web Service** and the frontend as a Render **Static Site**. Use a Render-managed PostgreSQL database for persistent conversations; do not deploy the local SQLite file.

**Backend Web Service**

- Build command: `pip install -r backend/requirements.txt`
- Start command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Set `DATABASE_URL` to the Render PostgreSQL connection string.
- Set `FRONTEND_ORIGINS` to the exact HTTPS origin of the deployed frontend (no wildcard).
- Keep live AI providers disabled unless separately configured and approved.

**Frontend Static Site**

- Build command: `cd frontend && npm ci && npm run build`
- Publish directory: `frontend/dist`
- Set build-time `VITE_API_BASE_URL` to `https://<backend-service-host>/api/v1`.

Set the frontend API URL before the static-site build. After deployment, verify `/api/v1/health` on the backend and exercise frontend requests from the deployed origin. Keep provider credentials exclusively in backend service environment settings.

## Tests and production build

```sh
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npm test -- --run && npm run build
```

The backend tests use in-memory databases and mocked provider responses. They do not verify live provider connectivity. The production build writes to the ignored `frontend/dist/` directory.

## Data and service limitations

Weather can use Open-Meteo forecasts, which are model-grid estimates rather than district-wide observations. Crop, market, and disease results depend on configured providers and available verified evidence; unavailable services should remain clearly identified. Do not present illustrative or mock data as official live observations.

See `docs/` for architecture, integration, and geographic-data notes. `VOICE_FOUNDATION.md` documents the voice implementation.
