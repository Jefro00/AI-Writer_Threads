"""Consistent backup of a running or stopped SQLite database using SQLite backup API.

Usage from project root:
    python tools/backup_sqlite.py

Not for PostgreSQL: use pg_dump/provider backups instead.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_DIR, settings


def main() -> None:
    url = settings.database_url
    if not url.startswith('sqlite:///'):
        raise SystemExit('DATABASE_URL does not point to SQLite; use a PostgreSQL backup tool.')
    source_path = Path(url.removeprefix('sqlite:///'))
    if not source_path.is_absolute():
        source_path = BASE_DIR / source_path
    if not source_path.exists():
        raise SystemExit(f'SQLite not found: {source_path}')
    output_dir = BASE_DIR / 'backups'
    output_dir.mkdir(exist_ok=True)
    filename = 'threads_engine_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.db'
    destination = output_dir / filename
    with sqlite3.connect(str(source_path)) as source, sqlite3.connect(str(destination)) as target:
        source.backup(target)
    print(f'Backup created: {destination} ({destination.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
