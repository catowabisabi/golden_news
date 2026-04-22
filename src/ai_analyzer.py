#!/usr/bin/env python3
"""
Golden News - AI Analyzer
Generates trading signals and alpha ideas from news using LLM
Processes up to 500 articles per run using a thread pool for concurrency.
"""
import re
import sqlite3
import json
import os
import time
import threading
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from log_config import get_logger

log = get_logger("analyzer")

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

def _load_api_key() -> str:
    key = os.environ.get("MINIMAX_CHAT_KEY", "")
    if not key:
        keys_path = PROJECT_ROOT / "config" / "api_keys.json"
        if keys_path.exists():
            try:
                key = json.loads(keys_path.read_text()).get("minimax_chat", "")
            except Exception:
                pass
    return key

MINIMAX_CHAT_KEY = _load_api_key()
BATCH_SIZE = 500
MAX_WORKERS = 5   # 500 RPM shared across ~6 agents → ~83 RPM budget each

_db_lock = threading.Lock()

SYSTEM_PROMPT = """You are Golden News AI - a financial trading signal generator.

For each financial/geopolitical news article, output ONLY a valid JSON object (no markdown, no explanation):

{
  "signal_type": "alpha|trade_idea|risk_alert|momentum|reversal",
  "asset_class": "oil|gold|stocks|crypto|bonds|forex|commodities|multi",
  "direction": "long|short|neutral",
  "confidence": 0.0-1.0,
  "headline": "One sentence trading signal headline",
  "rationale": "2-3 sentences explaining why this matters",
  "ticker": "optional ETF or stock ticker",
  "entry_price": "current or price range",
  "stop_loss": "optional stop loss",
  "take_profit": "optional take profit",
  "timeframe": "intraday|short-term|medium-term",
  "sector_calls": {"OVERWEIGHT": [], "UNDERWEIGHT": [], "FLAT": []},
  "risk_factors": []
}

If the news is NOT relevant to trading/financial markets, respond with:
{"signal_type": "none", "asset_class": "multi", "direction": "neutral", "confidence": 0.0, "headline": "Not applicable", "rationale": "Not trading relevant", "timeframe": "N/A"}

Rules:
- confidence >= 0.7 means HIGH conviction
- Always include ticker if relevant (use ETF tickers: XLE for energy, SPY for S&P, DXY for dollar, etc.)
- Include 2-5 risk factors even if not trading
- Think about: price impact, sector correlation, market sentiment, supply/demand
"""


_MINIMAX_URL = "https://api.minimax.io/anthropic/v1/messages"
_MINIMAX_HEADERS = {
    "x-api-key": MINIMAX_CHAT_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

_SENTINEL_EMPTY = "EMPTY"    # article has no text — mark analyzed, no signal
_SENTINEL_ERROR = "ERROR"    # API call failed — do NOT mark analyzed, retry next run

def _analyze_one(article_id, title, summary, content):
    """Analyze a single article. Returns (article_id, result) where result is:
      signal dict   — parsed signal from AI
      _SENTINEL_EMPTY — no text to analyze
      _SENTINEL_ERROR — API/network error, should retry later
    """
    article_text = (summary or content or "").strip()
    if not article_text:
        return article_id, _SENTINEL_EMPTY

    user_prompt = f"Title: {title}\n\nContent: {article_text[:2000]}"
    payload = {
        "model": "MiniMax-M2.7",
        "max_tokens": 800,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    for attempt in range(2):  # 1 retry after 1-hour cooldown on 429
        try:
            resp = httpx.post(
                _MINIMAX_URL,
                headers=_MINIMAX_HEADERS,
                json=payload,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
            )
            if resp.status_code == 429:
                raise RuntimeError("429 rate_limit")
            resp.raise_for_status()
            data = resp.json()

            # Extract text — handle both Anthropic-standard and MiniMax variants
            text = ""
            content = data.get("content") or data.get("choices") or []
            for block in content:
                if not isinstance(block, dict):
                    continue
                # Skip pure thinking blocks (MiniMax extended-thinking)
                if set(block.keys()) == {"thinking"}:
                    continue
                # Anthropic format: {"type":"text","text":"..."}
                # MiniMax/OpenAI format: {"message":{"content":"..."}} or {"text":"..."}
                text = (block.get("text")
                        or block.get("value")
                        or (block.get("message") or {}).get("content")
                        or "")
                if text:
                    break
            if not text:
                log.warning("[warn] unexpected response shape: %s", json.dumps(data)[:300])
                return article_id, _SENTINEL_EMPTY

            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                signal = json.loads(text[start:end])
                signal["ai_model"] = "minimax-m2.7"
                return article_id, signal
            return article_id, _SENTINEL_EMPTY

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str.lower():
                if attempt == 0:
                    log.warning("[429] %s: server overloaded, waiting 1 hour...", title[:40])
                    time.sleep(60 * 60)
                    continue
                log.warning("[429] %s: still overloaded after cooldown, skipping", title[:40])
                return article_id, _SENTINEL_ERROR
            log.error("[err] %s: %s", title[:40], e)
            return article_id, _SENTINEL_ERROR

    return article_id, _SENTINEL_ERROR


def _save_results(db, results, title_map):
    """Write all results to DB under a single lock."""
    saved = 0
    errors = 0
    for article_id, signal in results:
        title = title_map.get(article_id, "")
        if signal is _SENTINEL_ERROR:
            errors += 1
            continue  # leave is_analyzed=0 so it gets retried next run

        if signal is _SENTINEL_EMPTY:
            db.execute("UPDATE news_articles SET is_analyzed=1 WHERE id=?", (article_id,))
            continue

        if signal.get("signal_type") == "none":
            db.execute("UPDATE news_articles SET is_analyzed=1 WHERE id=?", (article_id,))
            log.debug("skip (non-trading): %s", title[:55])
            continue

        direction = signal.get("direction", "neutral")
        if direction not in ("long", "short", "neutral"):
            direction = "neutral"

        db.execute("""
            INSERT INTO trading_signals
            (article_id, signal_type, asset_class, direction, confidence,
             headline, rationale, entry_price, exit_price, stop_loss,
             time_horizon, ai_model, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            article_id,
            signal.get("signal_type", "alpha"),
            signal.get("asset_class", "multi"),
            direction,
            signal.get("confidence", 0.5),
            signal.get("headline", ""),
            signal.get("rationale", ""),
            signal.get("entry_price", "current"),
            signal.get("take_profit", ""),
            signal.get("stop_loss", ""),
            signal.get("timeframe", "short-term"),
            signal.get("ai_model", "unknown"),
        ))
        db.execute("""
            UPDATE news_articles SET is_analyzed=1, is_trading_signal=1, is_outdated=0 WHERE id=?
        """, (article_id,))

        conf = int(signal.get("confidence", 0) * 100)
        ticker = signal.get("ticker", "")
        log.info("signal: %-7s %-12s %3d%% %-6s %s",
                 direction.upper(), signal.get("asset_class", ""), conf, ticker, title[:40])
        saved += 1

    db.commit()
    return saved, errors


_DEDUP_STOP = {
    'the','a','an','in','on','at','to','for','of','with','from','by','and',
    'or','but','as','is','are','was','were','be','been','have','has','had',
    'will','would','could','should','may','might','this','that','its','their',
    'over','after','into','than','about','said','says','report','news','amid',
}

def _tok(title):
    words = re.findall(r'\b[a-z]{4,}\b', (title or '').lower())
    return frozenset(w for w in words if w not in _DEDUP_STOP)


def _deduplicate(db):
    """Mark near-duplicate unanalyzed articles (same topic within 10 days) as outdated."""
    # Build reference from already-analyzed non-outdated articles (last 10 days)
    seen = [
        _tok(r[0]) for r in db.execute(
            "SELECT title FROM news_articles "
            "WHERE is_analyzed=1 AND is_outdated=0 "
            "AND fetched_at >= datetime('now','-10 days')"
        ).fetchall()
    ]

    # Candidates: unanalyzed articles
    candidates = db.execute(
        "SELECT id, title FROM news_articles "
        "WHERE is_analyzed=0 AND fetched_at >= datetime('now','-10 days') "
        "ORDER BY fetched_at ASC"
    ).fetchall()

    dup_ids = []
    for art_id, title in candidates:
        tokens = _tok(title)
        if tokens and any(len(tokens & s) >= 3 for s in seen if s):
            dup_ids.append((art_id,))
        else:
            seen.append(tokens)

    if dup_ids:
        db.executemany(
            "UPDATE news_articles SET is_analyzed=1, is_outdated=1 WHERE id=?",
            dup_ids,
        )
        db.commit()
        log.info("Dedup: skipped %d near-duplicate articles", len(dup_ids))
    return len(dup_ids)


def process_unanalyzed_articles():
    log.info("Golden News AI Analyzer starting")

    db = sqlite3.connect(DB_PATH)
    _deduplicate(db)  # remove near-duplicates before analysis

    # Sample up to 84 per source (~6 sources * 84 = ~500), diverse across asset classes
    cursor = db.execute("""
        SELECT id, title, summary, content FROM (
            SELECT a.id, a.title, a.summary, a.content, a.source_id,
                   ROW_NUMBER() OVER (PARTITION BY a.source_id ORDER BY a.fetched_at DESC) AS rn
            FROM news_articles a
            WHERE a.is_analyzed = 0 AND (a.summary IS NOT NULL OR a.content IS NOT NULL)
        )
        WHERE rn <= 84
        ORDER BY RANDOM()
        LIMIT ?
    """, (BATCH_SIZE,))
    articles = cursor.fetchall()

    if not articles:
        log.info("No new articles to analyze")
        db.close()
        return 0

    log.info("Analyzing %d articles with %d workers", len(articles), MAX_WORKERS)
    title_map = {row[0]: row[1] for row in articles}

    total_saved = 0
    total_errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_analyze_one, aid, title, summary, content): aid
            for aid, title, summary, content in articles
        }
        done = 0
        for future in as_completed(futures):
            article_id, signal = future.result()
            saved, errors = _save_results(db, [(article_id, signal)], title_map)
            total_saved += saved
            total_errors += errors
            done += 1
            if done % 50 == 0:
                log.info("... %d/%d done", done, len(articles))

    db.close()
    log.info("Done — %d signals saved from %d articles (%d API errors, will retry)",
             total_saved, len(articles), total_errors)
    return total_saved


if __name__ == "__main__":
    process_unanalyzed_articles()
