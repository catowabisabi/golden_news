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
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from log_config import get_logger

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("GOLDEN_NEWS_DB", str(PROJECT_ROOT / "database" / "golden_news.db")))
DASHBOARD_DIR = Path(__file__).parent

server = Flask(__name__, static_folder=None)


def _load_env_var(key: str) -> str:
    """Read a variable from .env file at project root."""
    val = os.environ.get(key, "")
    if not val:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith(key + "="):
                    val = line[len(key) + 1:]
                    break
    return val


_app_log = get_logger("app")

PAUSE_PASSWORD = _load_env_var("PAUSE_PASSWORD")
_app_log.info("[startup] PAUSE_PASSWORD loaded: %s",
              "(set, len=%d)" % len(PAUSE_PASSWORD) if PAUSE_PASSWORD else "(EMPTY — check .env)")
_paused = False
_current_analyzer_proc = None  # tracked so pause can kill it mid-run

# ── Background scheduler ──────────────────────────────────────────────────────
FETCH_INTERVAL_SEC = 60 * 60  # 60 minutes

_sched = {
    "status":   "idle",   # idle | fetching | error
    "stage":    "",       # "" | "collecting" | "analyzing"
    "progress": "",       # e.g. "42/426"
    "last_fetch": None,
    "next_fetch": None,
    "fetching": False,
}

_pipeline_logs: deque = deque(maxlen=300)  # circular buffer, last 300 lines


_LOG_LEVEL_MAP = {"info": 20, "warn": 30, "error": 40}  # logging.INFO/WARNING/ERROR


def _log(level: str, msg: str):
    _pipeline_logs.append({
        "t": datetime.now(timezone.utc).isoformat(),
        "level": level,   # info | warn | error
        "msg": msg,
    })
    _app_log.log(_LOG_LEVEL_MAP.get(level, 20), msg)


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


import re as _re

_DEDUP_STOP = {
    'the','a','an','in','on','at','to','for','of','with','from','by','and',
    'or','but','as','is','are','was','were','be','been','have','has','had',
    'will','would','could','should','may','might','this','that','its','their',
    'over','after','into','than','about','said','says','report','news','amid',
}

def _tok(title):
    words = _re.findall(r'\b[a-z]{4,}\b', (title or '').lower())
    return frozenset(w for w in words if w not in _DEDUP_STOP)


def _classify(line: str) -> str:
    low = line.lower()
    if any(k in low for k in ("error", "err]", "exception", "traceback", "failed", "could not")):
        return "error"
    if any(k in low for k in ("warn", "warning")):
        return "warn"
    return "info"


def _stream_subprocess(label: str, cmd: list, env: dict, timeout: int | None = None):
    """Run cmd, stream stdout/stderr line-by-line into log buffer and update _sched progress."""
    global _current_analyzer_proc
    proc = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    if label == "analyzer":
        _current_analyzer_proc = proc

    def _read():
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            _log(_classify(line), f"[{label}] {line}")

            # Parse progress from analyzer: "... 42/426 done"
            m = _re.search(r"(\d+)/(\d+)\s+done", line)
            if m:
                _sched["progress"] = f"{m.group(1)}/{m.group(2)}"

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _log("error", f"[{label}] killed after {timeout}s timeout")
    reader.join(timeout=5)
    if label == "analyzer":
        _current_analyzer_proc = None
    if proc.returncode and proc.returncode != 0:
        _log("error", f"[{label}] exited with code {proc.returncode}")


def _flush_backlog():
    """Flush unanalyzed backlog, deduplicate articles and signals."""
    with get_db() as db:
        # 1. Flush all unanalyzed articles as outdated
        cur = db.execute(
            "UPDATE news_articles SET is_analyzed=1, is_outdated=1 WHERE is_analyzed=0"
        )
        flushed = cur.rowcount

        # 2. Deduplicate analyzed (non-signal) articles within 10 days
        rows = db.execute(
            "SELECT id, title FROM news_articles "
            "WHERE is_outdated=0 AND is_trading_signal=0 "
            "AND fetched_at >= datetime('now','-10 days') "
            "ORDER BY fetched_at ASC"
        ).fetchall()
        seen, dup_ids = [], []
        for art_id, title in rows:
            tokens = _tok(title)
            if tokens and any(len(tokens & s) >= 3 for s in seen if s):
                dup_ids.append((art_id,))
            else:
                seen.append(tokens)
        if dup_ids:
            db.executemany("UPDATE news_articles SET is_outdated=1 WHERE id=?", dup_ids)

        # 3. Deduplicate trading_signals by headline similarity — keep highest confidence
        sig_rows = db.execute(
            "SELECT ts.id, ts.headline, ts.confidence FROM trading_signals ts "
            "JOIN news_articles a ON ts.article_id = a.id "
            "WHERE ts.is_active=1 "
            "AND a.fetched_at >= datetime('now','-10 days') "
            "ORDER BY ts.confidence DESC"
        ).fetchall()
        sig_seen, sig_dup_ids = [], []
        for sig_id, headline, conf in sig_rows:
            tokens = _tok(headline)
            if tokens and any(len(tokens & s) >= 3 for s in sig_seen if s):
                sig_dup_ids.append((sig_id,))
            else:
                sig_seen.append(tokens)
        if sig_dup_ids:
            db.executemany(
                "UPDATE trading_signals SET is_active=0 WHERE id=?", sig_dup_ids
            )

        db.commit()

    if flushed:
        _log("info", f"── Flushed {flushed} outdated unanalyzed articles ──")
    if dup_ids:
        _log("info", f"── Deduplicated {len(dup_ids)} near-duplicate articles ──")
    if sig_dup_ids:
        _log("info", f"── Deduplicated {len(sig_dup_ids)} near-duplicate signals ──")


def _run_pipeline():
    """Run collector then ai_analyzer as subprocesses. Thread-safe guard."""
    if _sched["fetching"]:
        return False
    _sched["fetching"] = True
    _sched["status"] = "fetching"
    env = _build_env()
    _flush_backlog()  # discard stale backlog before fetching fresh articles
    _log("info", "── Pipeline started ──")
    try:
        _sched["stage"] = "collecting"
        _sched["progress"] = ""
        _log("info", "[collector] starting...")
        _stream_subprocess("collector",
            [sys.executable, str(PROJECT_ROOT / "src" / "collector.py")],
            env, timeout=300)

        if _paused:
            _log("info", "── Analysis skipped (server is paused) ──")
        else:
            _sched["stage"] = "analyzing"
            _sched["progress"] = ""
            _log("info", "[analyzer] starting...")
            _stream_subprocess("analyzer",
                [sys.executable, str(PROJECT_ROOT / "src" / "ai_analyzer.py")],
                env)  # no timeout for analyzer

        _sched["status"] = "idle"
        _sched["stage"] = ""
        _sched["progress"] = ""
        _sched["last_fetch"] = datetime.now(timezone.utc).isoformat()
        _log("info", "── Pipeline complete ──")
    except Exception as e:
        _log("error", f"Pipeline error: {e}")
        _sched["status"] = "error"
        _sched["stage"] = ""
    finally:
        _sched["fetching"] = False
    return True


def _scheduler_loop():
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
    conditions = ["a.is_analyzed = 1", "(a.is_outdated = 0 OR a.is_trading_signal = 1)"]
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
    # articles / determiners
    "the", "a", "an",
    # pronouns
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their", "it", "its",
    # common verbs
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall",
    "get", "got", "said", "says", "say", "make", "made",
    # prepositions / conjunctions
    "in", "on", "at", "to", "for", "of", "with", "from", "by",
    "up", "out", "off", "into", "onto", "about", "above", "below",
    "between", "through", "during", "before", "after", "under",
    "over", "again", "then", "than", "so", "but", "and", "or",
    "not", "nor", "yet", "as", "if", "while", "although", "because",
    "since", "unless", "until", "though", "even",
    # demonstratives / relatives
    "this", "that", "these", "those", "which", "who", "whom",
    "what", "when", "where", "why", "how",
    # quantifiers / adverbs
    "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "only", "just", "also", "very", "much", "many",
    "well", "still", "now", "here", "there", "then", "too", "back",
    "already", "always", "often", "ever", "never", "once",
    # common filler words that pollute keyword graphs
    "said", "says", "told", "report", "reports", "reported",
    "news", "new", "year", "years", "week", "weeks", "month",
    "time", "times", "high", "higher", "low", "lower",
    "percent", "rate", "data", "based", "according",
    "amid", "amid", "amid", "against", "without",
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


@server.route("/api/source-status")
def api_source_status():
    """Return health status for every active news source."""
    with get_db() as db:
        cur = db.execute(
            """
            SELECT id, display_name, category, api_type, is_paid,
                   is_working, last_tested_at, last_response_time_ms,
                   rate_limit_rpm
            FROM news_sources
            WHERE is_active = 1
            ORDER BY category, display_name
            """
        )
        sources = [dict(r) for r in cur.fetchall()]

    # Attach recent article count per source (last 24 h)
    with get_db() as db:
        counts = {
            row[0]: row[1]
            for row in db.execute(
                """
                SELECT source_id, COUNT(*) FROM news_articles
                WHERE fetched_at >= datetime('now', '-24 hours')
                GROUP BY source_id
                """
            ).fetchall()
        }

    for s in sources:
        s["articles_last_24h"] = counts.get(s["id"], 0)
        # Normalise is_working: NULL → "untested", 0 → "down", 1 → "up"
        s["status"] = {None: "untested", 0: "down", 1: "up"}.get(s["is_working"], "untested")

    return jsonify(sources)


@server.route("/api/scheduler-status")
def api_scheduler_status():
    with get_db() as db:
        queued = db.execute(
            "SELECT COUNT(*) FROM news_articles WHERE is_analyzed=0"
            " AND (summary IS NOT NULL OR content IS NOT NULL)"
        ).fetchone()[0]
        total_signals = db.execute(
            "SELECT COUNT(*) FROM trading_signals WHERE is_active=1"
        ).fetchone()[0]
        strong_signals = db.execute(
            "SELECT COUNT(*) FROM trading_signals WHERE is_active=1 AND confidence >= 0.7"
        ).fetchone()[0]
    return jsonify({
        "status":         _sched["status"],
        "stage":          _sched["stage"],
        "progress":       _sched["progress"],
        "last_fetch":     _sched["last_fetch"],
        "next_fetch":     _sched["next_fetch"],
        "fetching":       _sched["fetching"],
        "paused":         _paused,
        "queued_count":   queued,
        "total_signals":  total_signals,
        "strong_signals": strong_signals,
    })


@server.route("/api/pause", methods=["POST", "OPTIONS"])
def api_pause():
    global _paused, _current_analyzer_proc
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    if body.get("password") != PAUSE_PASSWORD:
        return jsonify({"ok": False, "reason": "wrong password"}), 403
    _paused = True
    if _current_analyzer_proc and _current_analyzer_proc.poll() is None:
        _current_analyzer_proc.terminate()
        _log("warn", "── Analyzer terminated (pause requested) ──")
    _log("warn", "── Server paused by user — analysis suspended ──")
    return jsonify({"ok": True, "paused": True})


@server.route("/api/unpause", methods=["POST", "OPTIONS"])
def api_unpause():
    global _paused
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    if body.get("password") != PAUSE_PASSWORD:
        return jsonify({"ok": False, "reason": "wrong password"}), 403
    _paused = False
    _log("info", "── Server unpaused by user — analysis resumed ──")
    return jsonify({"ok": True, "paused": False})


@server.route("/api/pipeline-logs")
def api_pipeline_logs():
    since = request.args.get("since")  # ISO timestamp — client asks for new lines only
    logs = list(_pipeline_logs)
    if since:
        logs = [l for l in logs if l["t"] > since]
    return jsonify(logs)


@server.route("/api/fetch-now", methods=["POST", "OPTIONS"])
def api_fetch_now():
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    if body.get("password") != PAUSE_PASSWORD:
        return jsonify({"queued": False, "reason": "wrong password"}), 403
    if _sched["fetching"]:
        return jsonify({"queued": False, "reason": "already fetching"}), 202
    threading.Thread(target=_run_pipeline, daemon=True).start()
    return jsonify({"queued": True}), 202


@server.route("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "index.html")


if __name__ == "__main__":
    _flush_backlog()  # clear any stale backlog from previous session on startup
    sched_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    sched_thread.start()
    _app_log.info("Golden News dashboard → http://localhost:8050")
    _app_log.info("Auto-fetching every %d minutes", FETCH_INTERVAL_SEC // 60)
    server.run(host="0.0.0.0", port=8050, debug=False)
