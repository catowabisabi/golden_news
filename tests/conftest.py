import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _create_test_db(path: str) -> None:
    """Bootstrap a fresh SQLite database from schema.sql."""
    schema = (PROJECT_ROOT / "database" / "schema.sql").read_text()
    db = sqlite3.connect(path)
    # schema.sql uses PRAGMA statements that must run individually
    for statement in schema.split(";"):
        stmt = statement.strip()
        if stmt:
            try:
                db.execute(stmt)
            except sqlite3.OperationalError:
                pass  # e.g. duplicate index on re-run
    # Seed a minimal news source so FK constraints are satisfied
    db.execute(
        "INSERT OR IGNORE INTO news_sources "
        "(name, display_name, category, api_type) "
        "VALUES ('test_src', 'Test Source', 'general', 'rss')"
    )
    db.commit()
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.app as app_module

    db_file = str(tmp_path / "test_golden_news.db")
    _create_test_db(db_file)

    # Redirect all DB calls to the temp database
    monkeypatch.setattr(app_module, "DB_PATH", Path(db_file))

    app_module.server.config["TESTING"] = True
    with app_module.server.test_client() as c:
        yield c
