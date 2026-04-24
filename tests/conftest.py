import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Point dashboard at an isolated test database *before* importing the app module
# so DB_PATH is resolved to the temp file, not the production database.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["GOLDEN_NEWS_DB"] = _tmp_db.name

_SCHEMA = Path(__file__).parent.parent / "database" / "schema.sql"

sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialise schema in the test DB
_db = sqlite3.connect(_tmp_db.name)
_db.executescript(_SCHEMA.read_text())
_db.execute(
    "INSERT OR IGNORE INTO news_sources (name, display_name, category, api_type)"
    " VALUES ('test_src', 'Test Source', 'general', 'rss')"
)
_db.commit()
_db.close()

from dashboard.app import server  # noqa: E402 — must come after env var is set


@pytest.fixture
def client():
    server.config["TESTING"] = True
    with server.test_client() as c:
        yield c
