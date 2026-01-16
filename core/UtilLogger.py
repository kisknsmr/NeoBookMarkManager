import logging
import sys

def setup_logger(name="NeoBookMarkManager"):
    """
    Sets up a centralized logger that outputs to stdout/stderr.
    Format: [TIMESTAMP] [LEVEL] MESSAGE
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Check if handlers already exist to avoid duplicate logs
    if not logger.handlers:
        # Stream Handler for console output (Immediate Window equivalent)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)

        # Formatter
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

    return logger

# Singleton instance to be used across modules
logger = setup_logger()
