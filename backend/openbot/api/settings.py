from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from openbot.api.deps import get_services
from openbot.api.schemas import DatabaseLocationOut, SettingOut
from openbot.runtime import app_settings
from openbot.services import Services


def database_location(database_url: str) -> str:
    """Return the effective on-disk database directory for display in Settings."""
    if database_url.startswith("sqlite"):
        database = database_url.split("///", 1)[1] if "///" in database_url else database_url
        if database == ":memory:":
            return database
        return str(Path(database).expanduser().resolve().parent)
    return database_url


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingOut])
async def list_settings(services: Services = Depends(get_services)):
    return await app_settings.describe(services)


@router.get("/database-location", response_model=DatabaseLocationOut)
async def get_database_location(services: Services = Depends(get_services)):
    return DatabaseLocationOut(location=database_location(services.settings.database_url))


@router.patch("", response_model=list[SettingOut])
async def patch_settings(body: dict[str, Any], services: Services = Depends(get_services)):
    """Set one or more runtime settings. The batch is validated as a whole: a bad key or value leaves nothing changed."""
    try:
        await app_settings.update_settings(services, body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return await app_settings.describe(services)


@router.delete("/{key}", response_model=list[SettingOut])
async def reset_setting(key: str, services: Services = Depends(get_services)):
    """Drop the stored override so the setting goes back to its environment value."""
    try:
        await app_settings.reset_setting(services, key)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return await app_settings.describe(services)
