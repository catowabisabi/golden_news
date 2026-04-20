#!/usr/bin/env python3
"""
Golden News - Database Backup

Creates a timestamped copy of golden_news.db in the backups/ directory
using SQLite's online backup API (safe while the server is running).

Usage:
  python scripts/backup_db.py

Cron (daily at 02:00):
  0 2 * * * /usr/bin/python3 /path/to/golden_news/scripts/backup_db.py >> /var/log/golden_news_backup.log 2>&1
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"
BACKUP_DIR = PROJECT_ROOT / "backups"
MAX_BACKUPS = 7  # keep last 7 daily backups


def backup():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"golden_news_{timestamp}.db"

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    size_kb = dest.stat().st_size // 1024
    print(f"Backup saved: {dest.name} ({size_kb} KB)")

    # Prune old backups, keeping only the most recent MAX_BACKUPS
    existing = sorted(BACKUP_DIR.glob("golden_news_*.db"))
    for old in existing[:-MAX_BACKUPS]:
        old.unlink()
        print(f"Removed old backup: {old.name}")


if __name__ == "__main__":
    backup()
