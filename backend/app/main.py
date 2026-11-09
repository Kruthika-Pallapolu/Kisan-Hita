from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.routes.contracts import router as contracts_router
from app.api.routes.features import router as features_router
from app.api.routes.health import router as health_router
from app.api.routes.voice import router as voice_router
from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.core.database import Base
from app import models as _models  # register persistent conversation table
from app.core.errors import http_error_handler, internal_error_handler, validation_error_handler
from app.schemas.features import ApiInfo
from app.services.container import build_container, build_services


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            engine = getattr(application.state, "engine", None)
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Kisan Hita API", version="0.1.1", description="Kisan Hita API foundation and typed feature contracts.", lifespan=lifespan)
    app.state.settings = settings
    app.state.providers = build_container(settings)
    app.state.engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(bind=app.state.engine)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.services = build_services(app.state.providers, app.state.session_factory, settings.conversation_retention_days)
    app.add_middleware(CORSMiddleware, allow_origins=settings.frontend_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["Content-Type", "Accept"])
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)

    def api_root_payload():
        return {
            "service": "Kisan Hita API",
            "api_prefix": settings.api_v1_prefix,
            "health": f"{settings.api_v1_prefix}/health",
            "docs": "/docs",
        }

    @app.get("/", response_model=ApiInfo, tags=["health"])
    @app.get(settings.api_v1_prefix, response_model=ApiInfo, tags=["health"])
    def api_root():
        return api_root_payload()

    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(contracts_router, prefix=settings.api_v1_prefix)
    app.include_router(features_router, prefix=settings.api_v1_prefix)
    app.include_router(voice_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
