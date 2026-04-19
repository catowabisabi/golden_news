import sys
from pathlib import Path

import pytest

# Make dashboard importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.app import server


@pytest.fixture
def client():
    server.config["TESTING"] = True
    with server.test_client() as c:
        yield c
