from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/manifest", summary="Return GitHub App manifest placeholder")
async def get_manifest() -> dict[str, str]:
    """Temporary placeholder manifest endpoint.

    TODO: Populate from environment configuration per Plan guidelines.
    """
    raise HTTPException(status_code=501, detail="Manifest endpoint not yet implemented")
