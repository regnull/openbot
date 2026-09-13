from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI

from openbot.config import Settings, get_settings


def create_app(settings: Settings | None = None, services=None) -> FastAPI:
    load_dotenv()
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="OpenBot", lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services

    api = APIRouter(prefix="/api/v1")

    @api.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(api)
    return app


app = create_app()
