import sys
import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _init_test_db(db_path: Path) -> None:
    """Create a fresh test database with the full production schema."""
    schema_sql = (PROJECT_ROOT / "database" / "schema.sql").read_text()
    db = sqlite3.connect(str(db_path))
    db.executescript(schema_sql)
    db.execute(
        "INSERT OR IGNORE INTO news_sources "
        "(name, display_name, category, api_type) "
        "VALUES ('test_source', 'Test Source', 'general', 'rss')"
    )
    db.commit()
    db.close()


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("golden_news") / "test.db"
    _init_test_db(db_path)
    return db_path


@pytest.fixture
def client(test_db_path, monkeypatch):
    import dashboard.app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", test_db_path)
    app_module.server.config["TESTING"] = True
    with app_module.server.test_client() as c:
        yield c
