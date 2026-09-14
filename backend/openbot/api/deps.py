from __future__ import annotations

import hmac
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
    # compare_digest, not ==: `==` on str short-circuits at the first differing byte, which leaks the
    # key prefix-by-prefix to anyone who can time the 401s. Compare bytes, because compare_digest
    # rejects str with non-ASCII code points (a 500 on a hostile header, otherwise).
    want = expected.encode()
    supplied = [c for c in (key, request.query_params.get("api_key")) if c is not None]
    if not any(hmac.compare_digest(c.encode(), want) for c in supplied):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
