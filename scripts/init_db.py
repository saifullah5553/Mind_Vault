"""Initialize (or reset) the Mind_Vault database.

Usage:
    python -m scripts.init_db          # create tables if missing
    python -m scripts.init_db --reset  # DROP and recreate (destructive)
"""

from __future__ import annotations

import argparse

from core.config import get_settings
from core.database.session import init_db
from core.logging_setup import get_logger

log = get_logger("scripts.init_db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the Mind_Vault database")
    parser.add_argument("--reset", action="store_true", help="drop all tables first (destructive)")
    args = parser.parse_args()

    settings = get_settings()
    log.info("Using database: %s", settings.database_url)
    init_db(drop=args.reset)
    log.info("Database ready%s.", " (reset)" if args.reset else "")


if __name__ == "__main__":
    main()
