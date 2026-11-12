from fastapi import APIRouter, HTTPException

from app.modules import fixture_dir_harvest as harvest_module
from app.schemas.entities import HarvestIngestRequest, HarvestRequest

router = APIRouter(tags=["harvests"])


@router.get("/harvests")
def list_harvests():
    return harvest_module.list_harvests()


@router.post("/harvests")
def create_harvest(body: HarvestRequest):
    try:
        return harvest_module.create_harvest(
            body.directory,
            recursive=body.recursive,
            ingest=body.ingest,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/harvests/{harvest_id}")
def get_harvest(harvest_id: int):
    try:
        return harvest_module.get_harvest_detail(harvest_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/harvests/{harvest_id}/ingest")
def ingest_harvest(harvest_id: int, body: HarvestIngestRequest):
    try:
        return harvest_module.ingest_harvest(harvest_id, mode=body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
