"""
Logging utilities.
"""

import logging
import sys


def setup_logging(level=logging.INFO, name="rf_inspector"):
    """
    Set up basic logging configuration.

    Args:
        level: Logging level
        name: Logger name

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
