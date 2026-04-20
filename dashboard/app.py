#!/usr/bin/env python3
"""
Golden News – Flask backend.

Serves the signal-first dashboard (index.html) and a small REST API
over the SQLite database. Includes a 15-minute background auto-fetch
scheduler and filter/sort support on all collection endpoints.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"
DASHBOARD_DIR = Path(__file__).parent

server = Flask(__name__, static_folder=None)

# ── Background scheduler ──────────────────────────────────────────────────────
FETCH_INTERVAL_SEC = 15 * 60  # 15 minutes

_sched = {
    "status": "idle",      # idle | fetching | error
    "last_fetch": None,    # ISO-8601 UTC string
    "next_fetch": None,    # ISO-8601 UTC string
    "fetching": False,
}


def _build_env():
    """Build subprocess env with MINIMAX_CHAT_KEY from api_keys.json if not already set."""
    env = os.environ.copy()
    if not env.get("MINIMAX_CHAT_KEY"):
        keys_path = PROJECT_ROOT / "config" / "api_keys.json"
        if keys_path.exists():
            try:
                keys = json.loads(keys_path.read_text())
                key = keys.get("minimax_chat", "")
                if key:
                    env["MINIMAX_CHAT_KEY"] = key
            except Exception:
                pass
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_pipeline():
    """Run collector then ai_analyzer as subprocesses. Thread-safe guard."""
    if _sched["fetching"]:
        return False
    _sched["fetching"] = True
    _sched["status"] = "fetching"
    env = _build_env()
    try:
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "src" / "collector.py")],
            timeout=180, capture_output=True, env=env,
        )
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "src" / "ai_analyzer.py")],
            timeout=180, capture_output=True, env=env,
        )
        _sched["status"] = "idle"
        _sched["last_fetch"] = datetime.now(timezone.utc).isoformat()
    except Exception:
        _sched["status"] = "error"
    finally:
        _sched["fetching"] = False
    return True


def _scheduler_loop():
    _run_pipeline()  # Fetch immediately on startup
    while True:
        next_ts = time.time() + FETCH_INTERVAL_SEC
        _sched["next_fetch"] = datetime.fromtimestamp(
            next_ts, tz=timezone.utc
        ).isoformat()
        time.sleep(FETCH_INTERVAL_SEC)
        _run_pipeline()


# ── Database helpers ──────────────────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def get_latest_articles(limit=100, source=None, asset=None, sort="newest"):
    conditions = ["1=1"]
    params: list = []
    if source:
        conditions.append("s.display_name = ?")
        params.append(source)
    if asset:
        conditions.append("ts.asset_class = ?")
        params.append(asset)

    order = "a.fetched_at DESC" if sort != "published" else "a.published_at DESC"
    where = " AND ".join(conditions)

    join_signal = "LEFT JOIN trading_signals ts ON ts.article_id = a.id" if asset else ""
    params.append(limit)
    with get_db() as db:
        cur = db.execute(
            f"""
            SELECT DISTINCT a.id, a.title, a.summary, a.url, a.source_id,
                   a.published_at, a.fetched_at, a.sentiment_score,
                   a.sentiment_label, a.is_trading_signal,
                   s.display_name AS source_name, s.category
            FROM news_articles a
            JOIN news_sources s ON a.source_id = s.id
            {join_signal}
            WHERE {where}
            ORDER BY {order}
            LIMIT ?
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_active_signals(
    limit=100, asset=None, source=None, sort="newest", direction=None
):
    conditions = ["ts.is_active = 1"]
    params: list = []
    if asset:
        conditions.append("ts.asset_class = ?")
        params.append(asset)
    if source:
        conditions.append("s.display_name = ?")
        params.append(source)
    if direction:
        conditions.append("ts.direction = ?")
        params.append(direction)

    order_map = {
        "newest": "ts.generated_at DESC",
        "confidence": "ts.confidence DESC",
    }
    order = order_map.get(sort, "ts.generated_at DESC")
    where = " AND ".join(conditions)
    params.append(limit)

    with get_db() as db:
        cur = db.execute(
            f"""
            SELECT ts.id, ts.article_id, ts.signal_type, ts.asset_class,
                   ts.direction, ts.confidence, ts.headline, ts.rationale,
                   ts.entry_price, ts.exit_price, ts.stop_loss,
                   ts.time_horizon, ts.generated_at,
                   a.title        AS article_title,
                   a.url          AS article_url,
                   a.published_at AS article_published_at,
                   s.display_name AS source_name
            FROM trading_signals ts
            JOIN news_articles a ON ts.article_id = a.id
            JOIN news_sources s  ON a.source_id   = s.id
            WHERE {where}
            ORDER BY {order}
            LIMIT ?
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


_STOP_WORDS = {
    "that", "this", "with", "from", "have", "been", "were", "they",
    "what", "when", "where", "which", "about", "would", "could",
    "your", "more", "than", "after", "also", "into", "some", "will",
    "their", "there", "just", "only", "over", "such", "before",
    "being", "through", "because",
}


def _extract_keywords(text, limit=10):
    words = re.findall(r"\b\w{4,}\b", (text or "").lower())
    seen = []
    for w in words:
        if w in _STOP_WORDS or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def get_graph_data():
    """Keyword-based relationship graph. Kept for API backwards-compat."""
    articles = get_latest_articles(limit=40)
    signals = get_active_signals(limit=10)
    signal_by_article = {s["article_id"]: s for s in signals}

    keyword_map = {
        art["id"]: _extract_keywords(f"{art['title']} {art.get('summary') or ''}")
        for art in articles
    }

    nodes = []
    for art in articles:
        sig = signal_by_article.get(art["id"])
        asset_class = sig["asset_class"] if sig else art.get("category")
        nodes.append({
            "id": art["id"],
            "title": art["title"][:60] + ("..." if len(art["title"]) > 60 else ""),
            "full_title": art["title"],
            "url": art["url"],
            "source": art["source_name"],
            "published": art["published_at"],
            "sentiment": art.get("sentiment_label") or "neutral",
            "asset_class": asset_class,
            "is_signal": bool(art.get("is_trading_signal")),
            "keywords": keyword_map.get(art["id"], []),
        })

    edges = []
    for i, a in enumerate(articles):
        ka = set(keyword_map[a["id"]])
        for b in articles[i + 1:]:
            shared = ka & set(keyword_map[b["id"]])
            if len(shared) >= 3:
                edges.append({
                    "source": a["id"],
                    "target": b["id"],
                    "strength": min(0.3 + 0.2 * len(shared), 1.0),
                    "shared_keywords": list(shared)[:5],
                })

    return {"nodes": nodes, "edges": edges, "signals": signals}


# ── Routes ────────────────────────────────────────────────────────────────────
@server.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@server.route("/health")
def health():
    return jsonify({"status": "ok"})


@server.route("/api/sources")
def api_sources():
    """Return sources that have at least one article in the DB."""
    with get_db() as db:
        cur = db.execute(
            """
            SELECT DISTINCT s.display_name, s.category
            FROM news_sources s
            INNER JOIN news_articles a ON a.source_id = s.id
            ORDER BY s.display_name
            """
        )
        return jsonify([dict(r) for r in cur.fetchall()])


@server.route("/api/articles")
def api_articles():
    source = request.args.get("source") or None
    asset = request.args.get("asset") or None
    sort = request.args.get("sort", "newest")
    return jsonify(get_latest_articles(limit=100, source=source, asset=asset, sort=sort))


@server.route("/api/signals")
def api_signals():
    asset = request.args.get("asset") or None
    source = request.args.get("source") or None
    sort = request.args.get("sort", "newest")
    direction = request.args.get("direction") or None
    return jsonify(
        get_active_signals(
            limit=100, asset=asset, source=source, sort=sort, direction=direction
        )
    )


@server.route("/api/graph-data")
def api_graph_data():
    return jsonify(get_graph_data())


@server.route("/api/scheduler-status")
def api_scheduler_status():
    return jsonify({
        "status": _sched["status"],
        "last_fetch": _sched["last_fetch"],
        "next_fetch": _sched["next_fetch"],
        "fetching": _sched["fetching"],
    })


@server.route("/api/fetch-now", methods=["POST", "OPTIONS"])
def api_fetch_now():
    if request.method == "OPTIONS":
        return "", 204
    if _sched["fetching"]:
        return jsonify({"queued": False, "reason": "already fetching"}), 202
    threading.Thread(target=_run_pipeline, daemon=True).start()
    return jsonify({"queued": True}), 202


@server.route("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "index.html")


if __name__ == "__main__":
    sched_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    sched_thread.start()
    print(f"Golden News dashboard → http://localhost:8050")
    print(f"Auto-fetching every {FETCH_INTERVAL_SEC // 60} minutes (immediate first run)")
    server.run(host="0.0.0.0", port=8050, debug=False)
