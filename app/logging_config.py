"""Application-wide logging setup."""
import logging
import os

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging() -> None:
    """Idempotent. Level comes from LOG_LEVEL (default INFO)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not any(getattr(h, "_regops", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._regops = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
