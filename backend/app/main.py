from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import CSRFMiddleware, SessionCookieMiddleware
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title="TriageAI API", version="0.0.1")

    # Middleware added last runs first, so the CSRF check rejects a forged
    # request before the session cookie is refreshed for it.
    app.add_middleware(SessionCookieMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_app()
