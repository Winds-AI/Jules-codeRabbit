from src.logger import logger


def main() -> None:
    host = "0.0.0.0"
    port = 8000
    display_url = f"http://localhost:{port}"

    logger.info(
        "Starting Jules Code Reviewer API on {display_url} (binding to {host}:{port})",
        display_url=display_url,
        host=host,
        port=port,
    )

    import uvicorn

    uvicorn.run(
        app="src.main:app",
        host=host,
        port=port,
        reload=True,
        workers=1,
        log_level="debug",
    )


if __name__ == "__main__":
    main()
