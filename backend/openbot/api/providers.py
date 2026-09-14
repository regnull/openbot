from fastapi import APIRouter, Depends

from openbot.api.deps import get_services
from openbot.runtime.providers import api_key_for, provider_status
from openbot.services import Services

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def providers(services: Services = Depends(get_services)):
    st = services.settings
    emb_provider = st.embedding_model.split(":", 1)[0]
    return {"providers": provider_status(st), "embedding_model": st.embedding_model,
            "embeddings_configured": bool(api_key_for(st, emb_provider))}
