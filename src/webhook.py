from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/webhook", summary="Receive GitHub webhooks")
async def receive_webhook() -> dict[str, str]:
    """Placeholder webhook receiver.

    TODO: Verify signature and enqueue jobs according to Plan instructions.
    """
    raise HTTPException(status_code=501, detail="Webhook endpoint not yet implemented")
