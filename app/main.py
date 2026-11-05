from fastapi import FastAPI

from app import __version__
from app.api import admin_config, health, planned
from app.api.errors import install_error_handlers
from app.config import get_settings
from app.ingest import demand_router as demand
from app.ingest import router as profiles
from app.sessions import router as sessions


def create_app() -> FastAPI:
    get_settings().assert_safe_for_env()
    app = FastAPI(title="Pod C - Stakeholder Roleplay Agent", version=__version__)
    install_error_handlers(app)
    for module in (health, admin_config, profiles, demand, sessions, planned):
        app.include_router(module.router)
    return app


app = create_app()
