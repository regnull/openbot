from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from openbot.api.deps import get_services
from openbot.api.schemas import SettingOut
from openbot.runtime import app_settings
from openbot.services import Services

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingOut])
async def list_settings(services: Services = Depends(get_services)):
    return await app_settings.describe(services)


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
