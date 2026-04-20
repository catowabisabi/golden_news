"""
Unit tests for src/signal_expiry.py
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.signal_expiry import expire_signals, EXPIRY_HOURS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: str) -> sqlite3.Connection:
    """Create a minimal in-memory schema for signal tests."""
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE news_sources (
            id INTEGER PRIMARY KEY,
            name TEXT,
            display_name TEXT,
            category TEXT DEFAULT 'general',
            api_type TEXT DEFAULT 'rss',
            is_active INTEGER DEFAULT 1,
            is_working INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        INSERT INTO news_sources (id, name, display_name) VALUES (1, 'test', 'Test');

        CREATE TABLE news_articles (
            id INTEGER PRIMARY KEY,
            source_id INTEGER,
            title TEXT,
            fetched_at TEXT DEFAULT (datetime('now')),
            is_analyzed INTEGER DEFAULT 0,
            is_trading_signal INTEGER DEFAULT 0
        );
        INSERT INTO news_articles (id, source_id, title) VALUES (1, 1, 'Test article');

        CREATE TABLE trading_signals (
            id INTEGER PRIMARY KEY,
            article_id INTEGER,
            signal_type TEXT DEFAULT 'alpha',
            asset_class TEXT DEFAULT 'multi',
            direction TEXT DEFAULT 'neutral',
            confidence REAL DEFAULT 0.5,
            headline TEXT DEFAULT '',
            time_horizon TEXT,
            is_active INTEGER DEFAULT 1,
            ai_model TEXT,
            generated_at TEXT
        );
        """
    )
    return db


def _insert_signal(db, horizon: str, generated_at: str, is_active: int = 1) -> int:
    cur = db.execute(
        """INSERT INTO trading_signals (article_id, time_horizon, is_active, generated_at)
           VALUES (1, ?, ?, ?)""",
        (horizon, is_active, generated_at),
    )
    db.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExpiryHours:
    def test_intraday_is_24h(self):
        assert EXPIRY_HOURS["intraday"] == 24

    def test_short_term_is_7d(self):
        assert EXPIRY_HOURS["short-term"] == 7 * 24

    def test_medium_term_is_30d(self):
        assert EXPIRY_HOURS["medium-term"] == 30 * 24


class TestExpireSignals:
    def test_expired_intraday_is_deactivated(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = _make_db(str(db_path))
        # Insert a signal generated 25 hours ago → past intraday window
        _insert_signal(db, "intraday", "datetime('now', '-25 hours')")
        db.execute(
            "UPDATE trading_signals SET generated_at = datetime('now', '-25 hours')"
        )
        db.commit()
        db.close()

        count = expire_signals(db_path)
        assert count == 1

        db2 = sqlite3.connect(str(db_path))
        row = db2.execute("SELECT is_active FROM trading_signals").fetchone()
        db2.close()
        assert row[0] == 0

    def test_fresh_intraday_stays_active(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = _make_db(str(db_path))
        # 1 hour old — still within 24-hour window
        db.execute(
            "INSERT INTO trading_signals (article_id, time_horizon, is_active, generated_at)"
            " VALUES (1, 'intraday', 1, datetime('now', '-1 hours'))"
        )
        db.commit()
        db.close()

        count = expire_signals(db_path)
        assert count == 0

        db2 = sqlite3.connect(str(db_path))
        row = db2.execute("SELECT is_active FROM trading_signals").fetchone()
        db2.close()
        assert row[0] == 1

    def test_already_inactive_not_counted(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = _make_db(str(db_path))
        # Already inactive, generated 48 h ago
        db.execute(
            "INSERT INTO trading_signals (article_id, time_horizon, is_active, generated_at)"
            " VALUES (1, 'intraday', 0, datetime('now', '-48 hours'))"
        )
        db.commit()
        db.close()

        count = expire_signals(db_path)
        assert count == 0

    def test_multiple_horizons_expire_independently(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = _make_db(str(db_path))
        db.executemany(
            "INSERT INTO trading_signals (article_id, time_horizon, is_active, generated_at)"
            " VALUES (1, ?, 1, ?)",
            [
                ("intraday",    "datetime('now', '-25 hours')"),   # expired
                ("short-term",  "datetime('now', '-2 hours')"),    # fresh
                ("medium-term", "datetime('now', '-800 hours')"),  # expired
            ],
        )
        db.execute(
            "UPDATE trading_signals SET generated_at = datetime('now', '-25 hours')"
            " WHERE time_horizon = 'intraday'"
        )
        db.execute(
            "UPDATE trading_signals SET generated_at = datetime('now', '-2 hours')"
            " WHERE time_horizon = 'short-term'"
        )
        db.execute(
            "UPDATE trading_signals SET generated_at = datetime('now', '-800 hours')"
            " WHERE time_horizon = 'medium-term'"
        )
        db.commit()
        db.close()

        count = expire_signals(db_path)
        assert count == 2  # intraday + medium-term

    def test_returns_zero_on_empty_table(self, tmp_path):
        db_path = tmp_path / "test.db"
        _make_db(str(db_path))
        assert expire_signals(db_path) == 0
