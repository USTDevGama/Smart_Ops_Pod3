import logging

from fastapi import FastAPI

from app import __version__
from app.api import admin_config, health, planned, reports
from app.api.errors import install_error_handlers
from app.config import get_settings
from app.ingest import demand_router as demand
from app.ingest import router as profiles
from app.sessions import router as sessions


def configure_logging(level: str) -> None:
    """Show the app's own INFO lines next to uvicorn's. The app logs through the root logger,
    which prints nothing until something sets it up, so without this `docker logs` has no
    `llm call ... Ns` lines. Does nothing if the root logger already has handlers (the Celery
    worker, pytest)."""
    logging.basicConfig(
        level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def create_app() -> FastAPI:
    settings = get_settings()
    settings.assert_safe_for_env()
    configure_logging(settings.log_level)
    app = FastAPI(title="Pod C - Stakeholder Roleplay Agent", version=__version__)
    install_error_handlers(app)
    for module in (health, admin_config, profiles, demand, sessions, reports, planned):
        app.include_router(module.router)
    return app


app = create_app()
