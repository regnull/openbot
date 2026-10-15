from fastapi import APIRouter, Depends

from openbot.api.deps import get_services
from openbot.runtime.providers import list_ollama_models, provider_configured, provider_status
from openbot.services import Services

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def providers(services: Services = Depends(get_services)):
    st = services.settings
    emb_provider = st.embedding_model.split(":", 1)[0]
    ollama_models = await list_ollama_models(st, getattr(services, "http_client", None))
    return {"providers": provider_status(st, ollama_models), "embedding_model": st.embedding_model,
            "embeddings_configured": provider_configured(st, emb_provider)}
