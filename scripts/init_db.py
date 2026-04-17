#!/usr/bin/env python3
"""
Golden News - Initialize Database
Creates SQLite database and seeds news sources from config
"""
import sqlite3
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"
SOURCES_PATH = PROJECT_ROOT / "config" / "news_sources.json"

def init_database():
    print("🏦 Initializing Golden News Database...")

    # Create database directory
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load schema
    schema = SCHEMA_PATH.read_text()

    # Create tables
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(schema)
    conn.commit()
    print(f"   ✅ Database created: {DB_PATH}")

    # Seed news sources
    sources_data = json.loads(SOURCES_PATH.read_text())
    sources = sources_data["sources"]

    cursor = conn.cursor()
    for src in sources:
        required_keys = json.dumps(src.get("required_keys", []))
        cursor.execute("""
            INSERT OR IGNORE INTO news_sources
            (name, display_name, category, api_type, base_url, docs_url,
             is_paid, monthly_cost_usd, description, required_keys, rate_limit_rpm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            src["name"],
            src["display_name"],
            src["category"],
            src["api_type"],
            src.get("base_url"),
            src.get("docs_url"),
            src["is_paid"],
            src.get("monthly_cost_usd", 0),
            src.get("description", ""),
            required_keys,
            src.get("rate_limit_rpm", 60)
        ))

    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM news_sources")
    count = cursor.fetchone()[0]
    print(f"   ✅ Seeded {count} news sources")

    # Create default user preferences
    cursor.execute("""
        INSERT OR IGNORE INTO user_preferences (key, value) VALUES
        ('ai_enabled', 'true'),
        ('websocket_port', '8765'),
        ('refresh_interval_seconds', '60'),
        ('max_articles_per_fetch', '100')
    """)
    conn.commit()
    print("   ✅ Default preferences set")

    conn.close()
    print("\n🎉 Database initialization complete!")

if __name__ == "__main__":
    init_database()
