from fastapi import FastAPI

from app import __version__
from app.api import health
from app.config import get_settings


def create_app() -> FastAPI:
    get_settings().assert_safe_for_env()
    app = FastAPI(title="Pod C - Stakeholder Roleplay Agent", version=__version__)
    app.include_router(health.router)
    return app


app = create_app()
