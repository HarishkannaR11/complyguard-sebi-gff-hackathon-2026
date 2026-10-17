"""Run Alembic migrations programmatically (used at API startup and by tests)."""
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.database import DEFAULT_DATABASE_URL

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]


def _config(database_url: str) -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    # Don't let alembic's fileConfig() clobber the application's logging setup.
    cfg.attributes["configure_logging"] = False
    return cfg


def run_migrations(database_url: str | None = None) -> None:
    """Upgrade the database to the latest revision. Raises on failure (no silent skips)."""
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    logger.info("Running database migrations")
    command.upgrade(_config(url), "head")
