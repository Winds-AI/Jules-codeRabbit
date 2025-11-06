from loguru import logger
import sys
import os

def setup_logger():
    log_dir = 'src/logs'
    os.makedirs(log_dir, exist_ok=True)
    logger.remove() # Remove default handler

    # Define a more detailed format
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    # Configure console logging
    logger.add(
        sys.stdout,
        level="INFO",
        format=log_format,
        colorize=True # Enable colorization for console
    )

    # Configure file logging
    logger.add(
        "src/logs/{time:YYYY-MM-DD}.log",
        rotation="50 MB", # Reduced rotation size for more frequent rotation if needed
        retention="10 days", # Keep logs for 10 days
        level="DEBUG",
        format=log_format,
        enqueue=True, # Make logging asynchronous for performance
        backtrace=True, # Include traceback in logs
        diagnose=True # Add exception diagnosis information
    )

    return logger

logger = setup_logger()