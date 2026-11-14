from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from pydantic import BaseModel
from pydantic import Field

from qbrixcore.engine.spec import ACCEPTED_FORMS

from proxysvc.mod.engine.catalog import engine_catalog
from proxysvc.transport.http.auth.dependencies import require_scopes

router = APIRouter(prefix="/engines", tags=["engines"])


class Engine(BaseModel):
    name: str
    title: str
    default: bool
    latest: str = Field(description="The version a new cycle on this engine runs.")
    versions: list[str] = Field(description="Every version this install ships.")
    suits: str
    learns_from: str
    needs: str
    needs_context: bool


class EngineList(BaseModel):
    engines: list[Engine]
    forms: str = Field(description="How an engine is named wherever one is chosen.")


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=EngineList,
)
async def list_engines(_scoped=Depends(require_scopes(["loop:read"]))):
    """the engines a cycle can run, the default first."""
    return EngineList(engines=engine_catalog(), forms=ACCEPTED_FORMS)
