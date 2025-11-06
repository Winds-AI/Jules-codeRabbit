if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app="src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1,
        log_level="debug",
    )