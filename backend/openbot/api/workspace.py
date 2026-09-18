from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from openbot.api.deps import get_services
from openbot.api.schemas import DirectoryEntryOut, DirectoryListingOut
from openbot.services import Services
from openbot.tools.builtin.workspace import browse_workspace_directory

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/directories", response_model=DirectoryListingOut)
async def list_directories(path: str = Query(".", description="Directory path (relative, absolute, or ~-relative)"),
                           services: Services = Depends(get_services)):
    """Backs the working-directory picker: browsers cannot reveal a chosen folder's full path,
    so the UI walks accessible directories through the server. The selected path is later
    validated as an existing, accessible directory when a thread is created."""
    try:
        here, parent, entries = browse_workspace_directory(services.settings.workspace_root, path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return DirectoryListingOut(path=here, parent=parent, entries=[DirectoryEntryOut(name=n, path=p) for n, p in entries])
