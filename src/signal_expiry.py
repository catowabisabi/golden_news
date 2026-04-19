#!/usr/bin/env python3
"""
Golden News - Signal Expiry
Marks trading signals inactive when they exceed their time_horizon window.

  intraday   → expires after  24 h
  short-term → expires after   7 d (168 h)
  medium-term→ expires after  30 d (720 h)

Run manually or via cron alongside run_pipeline.py.
"""
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

# How many hours each horizon is valid for
EXPIRY_HOURS: dict[str, int] = {
    "intraday": 24,
    "short-term": 7 * 24,
    "medium-term": 30 * 24,
}


def expire_signals(db_path: str | Path = DB_PATH) -> int:
    """
    Deactivate signals whose time_horizon window has elapsed.

    Returns the total number of signals marked inactive.
    """
    db = sqlite3.connect(db_path)
    total = 0
    try:
        for horizon, hours in EXPIRY_HOURS.items():
            cur = db.execute(
                """
                UPDATE trading_signals
                SET is_active = 0
                WHERE is_active = 1
                  AND time_horizon = ?
                  AND datetime(generated_at, ? || ' hours') <= datetime('now')
                """,
                (horizon, f"+{hours}"),
            )
            expired = cur.rowcount
            if expired:
                print(f"  Expired {expired:>3} {horizon} signal(s)")
            total += expired
        db.commit()
    finally:
        db.close()
    return total


if __name__ == "__main__":
    print("Golden News - Signal Expiry")
    print("=" * 40)
    count = expire_signals()
    print(f"\nTotal expired: {count}")
