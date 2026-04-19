#!/usr/bin/env python3
"""
Golden News - Flask backend.

Serves the signal-first dashboard (index.html) and a small REST API
over the SQLite database. No Dash, no WebSocket: the UI polls the
REST endpoints every 30s.
"""
import re
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"
DASHBOARD_DIR = Path(__file__).parent

server = Flask(__name__, static_folder=None)


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def get_latest_articles(limit=50):
    with get_db() as db:
        cur = db.execute(
            """
            SELECT a.id, a.title, a.summary, a.url, a.source_id,
                   a.published_at, a.fetched_at, a.sentiment_score,
                   a.sentiment_label, a.is_trading_signal,
                   s.display_name AS source_name, s.category
            FROM news_articles a
            JOIN news_sources s ON a.source_id = s.id
            ORDER BY a.fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_active_signals(limit=20):
    with get_db() as db:
        cur = db.execute(
            """
            SELECT ts.id, ts.article_id, ts.signal_type, ts.asset_class,
                   ts.direction, ts.confidence, ts.headline, ts.rationale,
                   ts.entry_price, ts.exit_price, ts.stop_loss,
                   ts.time_horizon, ts.generated_at,
                   a.title       AS article_title,
                   a.url         AS article_url,
                   a.published_at AS article_published_at,
                   s.display_name AS source_name
            FROM trading_signals ts
            JOIN news_articles a ON ts.article_id = a.id
            JOIN news_sources s ON a.source_id = s.id
            WHERE ts.is_active = 1
            ORDER BY ts.generated_at DESC
            LIMIT ?
            """,
            (limit,),
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


@server.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


@server.route("/health")
def health():
    return jsonify({"status": "ok"})


@server.route("/api/articles")
def api_articles():
    return jsonify(get_latest_articles(limit=50))


@server.route("/api/signals")
def api_signals():
    return jsonify(get_active_signals(limit=20))


@server.route("/api/graph-data")
def api_graph_data():
    return jsonify(get_graph_data())


@server.route("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "index.html")


if __name__ == "__main__":
    print("Golden News dashboard: http://localhost:8050")
    server.run(host="0.0.0.0", port=8050, debug=False)
