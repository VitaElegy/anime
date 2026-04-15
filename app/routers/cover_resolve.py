"""Title-to-cover matching — deterministic hash + SQLite persistent mapping."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import cover_resolver

router = APIRouter()


class CoverRequest(BaseModel):
    titles: list[str]


class CoverResult(BaseModel):
    title: str
    title_hash: str
    cover_url: str
    bangumi_id: int
    name_cn: str = ""
    name: str = ""


@router.post("/batch", response_model=list[CoverResult], summary="Batch resolve titles to covers")
async def batch_resolve_covers(req: CoverRequest):
    return [CoverResult(**item) for item in await cover_resolver.resolve_titles(req.titles)]
