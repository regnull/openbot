from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.services import Services

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_services(request: Request) -> Services:
    return request.app.state.services


async def get_session(services: Services = Depends(get_services)) -> AsyncIterator[AsyncSession]:
    async with services.session_factory() as session:
        yield session


async def require_api_key(request: Request, services: Services = Depends(get_services),
                          key: str | None = Depends(api_key_header)) -> None:
    expected = services.settings.openbot_api_key
    if not expected:
        return
    if key != expected and request.query_params.get("api_key") != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
