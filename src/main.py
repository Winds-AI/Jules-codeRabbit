import sys
from typing import Any

import fastapi
import uvicorn

from fastapi import FastAPI

from src.manifest import router as manifest_router
from src.register import router as register_router
from src.webhook import router as webhook_router
from src.setup_ui import router as setup_router


app = FastAPI(title="Jules Code Reviewer")

app.include_router(manifest_router, prefix="/github", tags=["manifest"])
app.include_router(register_router, prefix="/github", tags=["register"])
app.include_router(webhook_router, tags=["webhook"])
app.include_router(setup_router, tags=["setup"])


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
