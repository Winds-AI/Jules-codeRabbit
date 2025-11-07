import sys
from typing import Any

import fastapi
import uvicorn

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.manifest import router as manifest_router
from src.register import router as register_router
from src.setup_ui import router as setup_router
from src.queue import configure_review_handler, shutdown_queue
from src.services.review_processor import ReviewProcessor
from src.utils.paths import STATIC_DIR
from src.webhook import router as webhook_router


app = FastAPI(title="Jules Code Reviewer")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(manifest_router, prefix="/github", tags=["manifest"])
app.include_router(register_router, prefix="/github", tags=["register"])
app.include_router(webhook_router, tags=["webhook"])
app.include_router(setup_router, tags=["setup"])

@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "pong"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "The Jules Code Reviewer is operational and ready to review your code.",
        "environment": {
            "python version": sys.version,
            "fastapi version": fastapi.__version__,
            "uvicorn version": uvicorn.__version__,
        },
    }


@app.on_event("startup")
async def _configure_queue_worker() -> None:
    configure_review_handler(ReviewProcessor())


@app.on_event("shutdown")
async def _shutdown_queue_worker() -> None:
    await shutdown_queue()
