from fastapi import APIRouter, Depends

from openbot.api.deps import get_services
from openbot.services import Services

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(services: Services = Depends(get_services)):
    reg = services.registry
    return {
        "tools": [
            {"name": s.name, "description": s.description, "source": s.source,
             "args_schema": s.tool.tool_call_schema.model_json_schema() if s.tool.tool_call_schema else {}}
            for s in reg.specs()
        ],
        "errors": reg.load_errors,
    }
