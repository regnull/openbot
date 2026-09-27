from fastapi import APIRouter, Depends, HTTPException, Query

from openbot.api.deps import get_services
from openbot.api.schemas import ModelsOut
from openbot.runtime.model_catalog import CATALOG_PROVIDERS
from openbot.runtime.providers import PROVIDER_MODELS
from openbot.services import Services

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsOut)
async def list_models(provider: str = Query(...), services: Services = Depends(get_services)):
    """One provider's catalog. Until the first fetch has landed (fresh install, offline) it is the builtin
    suggestion list, flagged `source: builtin`, so the picker always has something to show."""
    if provider not in CATALOG_PROVIDERS:
        raise HTTPException(422, f"no catalog for provider {provider!r}; one of {', '.join(CATALOG_PROVIDERS)}")
    catalog = services.model_catalog
    got = await catalog.get(provider) if catalog is not None else None
    if got is None:
        return ModelsOut(provider=provider, source="builtin", stale=True, fetched_at=None,
                         models=[{"id": m, "name": m} for m in PROVIDER_MODELS[provider]])
    return ModelsOut(provider=provider, source="catalog", stale=got.stale, fetched_at=got.fetched_at, models=got.models)
