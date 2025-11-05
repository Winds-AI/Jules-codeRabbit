from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/register", summary="Handle GitHub App manifest conversion callback")
async def register_app() -> dict[str, str]:
    """Placeholder for the manifest conversion callback flow.

    TODO: Implement exchange of code for GitHub App credentials per latest docs.
    """
    raise HTTPException(status_code=501, detail="Register endpoint not yet implemented")
