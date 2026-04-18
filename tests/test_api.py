"""
Smoke tests for Golden News API.
Run: pytest tests/
These catch broken endpoints and serialization errors before deployment.
"""


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_articles_status(client):
    res = client.get("/api/articles")
    assert res.status_code == 200


def test_articles_returns_list(client):
    data = client.get("/api/articles").get_json()
    assert isinstance(data, list)


def test_articles_fields(client):
    data = client.get("/api/articles").get_json()
    if not data:
        return  # empty DB is fine; field check needs at least one row
    art = data[0]
    for field in ("id", "title", "url", "source_name", "sentiment_label"):
        assert field in art, f"Missing field: {field}"


def test_signals_status(client):
    res = client.get("/api/signals")
    assert res.status_code == 200


def test_signals_returns_list(client):
    data = client.get("/api/signals").get_json()
    assert isinstance(data, list)


def test_signals_fields(client):
    data = client.get("/api/signals").get_json()
    if not data:
        return
    sig = data[0]
    for field in ("id", "direction", "asset_class", "confidence", "headline", "time_horizon"):
        assert field in sig, f"Missing field: {field}"


def test_graph_data_status(client):
    res = client.get("/api/graph-data")
    assert res.status_code == 200


def test_graph_data_shape(client):
    data = client.get("/api/graph-data").get_json()
    assert "nodes" in data
    assert "edges" in data
    assert "signals" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)
