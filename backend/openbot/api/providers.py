from fastapi import APIRouter, Depends, HTTPException

from openbot.api.deps import get_services
from openbot.runtime.cli_agents import ADAPTERS, CliAgentError, adapter_for
from openbot.runtime.cli_agents.base import check_version, child_env, find_executable, login_status
from openbot.runtime.providers import list_ollama_models, provider_configured, provider_status
from openbot.services import Services

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def providers(services: Services = Depends(get_services)):
    st = services.settings
    emb_provider = st.embedding_model.split(":", 1)[0]
    ollama_models = await list_ollama_models(st, getattr(services, "http_client", None))
    # Only a file lookup; the CLI itself runs in cli_agent below, once the editor asks for it.
    cli_agents = [{"id": a.provider, "label": a.label, "found": find_executable(a, st) is not None,
                   "models": list(a.models)} for a in ADAPTERS.values()]
    return {"providers": provider_status(st, ollama_models), "cli_agents": cli_agents,
            "embedding_model": st.embedding_model, "embeddings_configured": provider_configured(st, emb_provider)}


@router.get("/cli/{provider}")
async def cli_agent(provider: str, services: Services = Depends(get_services)):
    """Where the CLI is, its version and whether it is logged in. The login state is the exit code of
    the CLI's own status command; its output is not passed on."""
    adapter = adapter_for(provider)
    if adapter is None:
        raise HTTPException(404, "not a CLI provider")
    out = {"id": adapter.provider, "label": adapter.label, "path": find_executable(adapter, services.settings),
           "version": None, "logged_in": None, "problem": None}
    if out["path"] is None:
        return {**out, "problem": adapter.not_found.removeprefix("error: ")}
    env = child_env()
    try:
        version = await check_version(adapter, out["path"], env)
    except CliAgentError as e:
        return {**out, "problem": str(e).removeprefix("error: ")}
    except OSError as e:
        return {**out, "problem": f"{adapter.label} could not be started: {e}"}
    out["version"] = ".".join(map(str, version)) if version else None
    out["logged_in"] = await login_status(adapter, out["path"], env)
    if out["logged_in"] is False:
        out["problem"] = f"{adapter.label} is not logged in. {adapter.login_hint}".rstrip()
    return out
