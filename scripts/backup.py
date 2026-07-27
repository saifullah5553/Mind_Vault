"""Backup & recovery.

Creates a timestamped zip of the database, config, logs, and publish manifests
into `storage/backups/`. Wire this into the daily GitHub Action (or cron) so no
generated content or configuration is ever lost.

Usage:
    python -m scripts.backup
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.config import ROOT_DIR, get_settings
from core.logging_setup import get_logger

log = get_logger("scripts.backup")


def main() -> None:
    settings = get_settings()
    backups = settings.storage_path("backups")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = backups / f"mind_vault-backup-{stamp}.zip"

    include: list[Path] = []
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_file = Path(db_url.replace("sqlite:///", ""))
        if db_file.exists():
            include.append(db_file)
    include += list((ROOT_DIR / "config").glob("*.yaml"))
    include += list((ROOT_DIR / "logs").glob("*.log"))
    include += list((ROOT_DIR / "storage" / "videos").glob("*_publish.json"))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in include:
            if path.exists():
                zf.write(path, arcname=path.relative_to(ROOT_DIR) if ROOT_DIR in path.parents else path.name)

    log.info("Backup written: %s (%d files)", out, len(include))
    print(f"Backup: {out}")


if __name__ == "__main__":
    main()
