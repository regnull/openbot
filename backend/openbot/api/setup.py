from __future__ import annotations

from fastapi import APIRouter, Depends

from openbot.api.deps import get_services
from openbot.runtime.setup import setup_status
from openbot.services import Services

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status")
async def status(services: Services = Depends(get_services)):
    """Whether the minimum configuration is met; the UI shows the setup wizard until it is."""
    return setup_status(services.settings)
