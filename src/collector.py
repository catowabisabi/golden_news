#!/usr/bin/env python3
"""
Golden News - News Collector
Collects news from all configured sources
"""
import sqlite3
import json
import time
import requests
import feedparser
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from log_config import get_logger

log = get_logger("collector")

_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds


def _get(url: str, **kwargs) -> requests.Response:
    """GET with exponential backoff on transient failures (5xx / 429 / network)."""
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("headers", {"User-Agent": "GoldenNews/1.0"})
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", _BACKOFF_BASE ** (attempt + 1)))
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                time.sleep(_BACKOFF_BASE ** attempt)
                continue
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(_BACKOFF_BASE ** attempt)
    # All retries exhausted — raise so callers can log/skip
    if last_exc:
        raise last_exc
    raise requests.RequestException(f"Failed after {_MAX_RETRIES} retries: {url}")

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

def get_db():
    return sqlite3.connect(DB_PATH)

def get_api_keys():
    keys_path = PROJECT_ROOT / "config" / "api_keys.json"
    if not keys_path.exists():
        return {}
    with open(keys_path) as f:
        return json.load(f)

def _fetch_rss_url(url):
    """Fetch and parse a single RSS URL. Returns list of article dicts."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "GoldenNews/1.0"})
        if r.status_code != 200:
            return []
        feed = feedparser.parse(r.text)
        return [
            {
                "title": e.get("title", ""),
                "summary": e.get("summary", "")[:500],
                "content": e.get("content", [{}])[0].get("value", "")[:2000],
                "url": e.get("link", ""),
                "author": e.get("author", ""),
                "published_at": e.get("published", datetime.now().isoformat()),
            }
            for e in feed.entries
        ]
    except Exception:
        return []


# Asset-specific Google News RSS queries (5 articles each = 30 total per run)
_GOOGLE_NEWS_QUERIES = [
    ("gold+silver+precious+metals+price+bullion",        5),
    ("bitcoin+ethereum+crypto+cryptocurrency+market",    5),
    ("stock+market+SP500+nasdaq+earnings+equities",      5),
    ("oil+crude+OPEC+energy+petroleum+price",            5),
    ("federal+reserve+bonds+interest+rates+inflation",   5),
    ("USD+EUR+GBP+forex+currency+exchange+rate",         5),
]

# Extra free RSS feeds for asset-class diversity (no API key needed)
_EXTRA_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",                        # crypto
    "https://feeds.marketwatch.com/marketwatch/topstories/",                  # stocks
    "https://www.kitco.com/rss/kitco-news.xml",                               # gold
    "https://www.oilprice.com/rss/main",                                      # oil/energy
    "https://www.forexlive.com/feed/news",                                    # forex
    "https://www.reddit.com/r/investing/.rss",                                # stocks/general
    "https://www.reddit.com/r/wallstreetbets/.rss",                           # stocks
    "https://www.reddit.com/r/Bitcoin/.rss",                                  # crypto
    "https://www.reddit.com/r/Gold/.rss",                                     # gold
]


def collect_rss(source, keys):
    """Collect from RSS feed with multi-asset coverage."""
    base_url = source["base_url"]
    if not base_url:
        return []

    name = source["name"]
    articles = []

    if "google" in name.lower():
        # Query EVERY asset class topic; collect up to 5 articles each
        for query, limit in _GOOGLE_NEWS_QUERIES:
            url = f"{base_url}/search?q={query}&hl=en-US&gl=US&ceid=US:en"
            batch = _fetch_rss_url(url)
            articles.extend(batch[:limit])
        return articles[:30]

    # Determine URLs to try (first success wins, except Google above)
    urls_to_try = []
    if "cnbc" in name.lower():
        urls_to_try.append("https://search.cnbc.com/rs/search/combinedcms/view.xml?ids=36")
    elif "bbc" in name.lower():
        urls_to_try.append(f"{base_url}/world/rss.xml")
    elif "reddit" in name.lower():
        # Finance + general subreddits for asset diversity
        urls_to_try += [
            "https://www.reddit.com/r/investing/.rss",
            "https://www.reddit.com/r/wallstreetbets/.rss",
            "https://www.reddit.com/r/Bitcoin/.rss",
            "https://www.reddit.com/r/Gold/.rss",
            "https://www.reddit.com/r/news/.rss",
            "https://www.reddit.com/r/worldnews/.rss",
        ]
    elif "zerohedge" in name.lower():
        urls_to_try.append("https://www.zerohedge.com/feed")
    elif "investing" in name.lower():
        # base_url already contains full RSS path for this source
        urls_to_try.append(base_url)
    elif "yahoo" in name.lower():
        urls_to_try += [
            "https://finance.yahoo.com/news/rssindex",
            "https://finance.yahoo.com/rss/topstories",
        ]
    elif "guardian" in name.lower():
        urls_to_try += [
            "https://www.theguardian.com/business/rss",
            "https://www.theguardian.com/world/rss",
        ]
    elif "duckduckgo" in name.lower() or "websearch" in name.lower():
        # Rotate through extra free feeds for asset diversity
        for feed_url in _EXTRA_FEEDS:
            batch = _fetch_rss_url(feed_url)
            articles.extend(batch[:5])
        return articles[:30]
    else:
        urls_to_try.append(f"{base_url}/feed")

    for url in urls_to_try:
        batch = _fetch_rss_url(url)
        if batch:
            articles.extend(batch[:10])
            # Reddit: collect from all subreddits; others stop at first success
            if "reddit" not in name.lower():
                break

    return articles[:30]

def collect_rest(source, keys):
    """Collect from REST API"""
    base_url = source["base_url"]
    name = source["name"]
    required = json.loads(source.get("required_keys", "[]"))

    # Get key
    api_key = None
    for req in required:
        if keys.get(req):
            api_key = keys[req]
            break

    if not api_key and required:
        return []

    articles = []
    try:
        if name == "newsapi_org":
            url = f"{base_url}/everything?q=oil+price+OR+stock+market+OR+breaking+news&language=en&sortBy=publishedAt&apiKey={api_key}"
            r = _get(url)
            if r.status_code == 200:
                data = r.json()
                for article in data.get("articles", [])[:15]:
                    articles.append({
                        "title": article.get("title", ""),
                        "summary": article.get("description", ""),
                        "content": article.get("content", ""),
                        "url": article.get("url", ""),
                        "author": article.get("author", ""),
                        "published_at": article.get("publishedAt", ""),
                    })

        elif name == "mediastack":
            url = f"{base_url}/news?access_key={api_key}&categories=business,science,technology&languages=en"
            r = _get(url)
            if r.status_code == 200:
                data = r.json()
                for article in data.get("data", [])[:15]:
                    articles.append({
                        "title": article.get("title", ""),
                        "summary": article.get("description", ""),
                        "content": article.get("description", ""),
                        "url": article.get("url", ""),
                        "author": "",
                        "published_at": article.get("published_at", ""),
                    })

        elif name == "finnhub":
            url = f"{base_url}/news?token={api_key}&category=general"
            r = _get(url)
            if r.status_code == 200:
                data = r.json()
                for item in data[:15]:
                    articles.append({
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", ""),
                        "content": item.get("summary", ""),
                        "url": item.get("url", ""),
                        "author": "",
                        "published_at": item.get("datetime", ""),
                    })

        elif name == "alpha_vantage":
            url = f"{base_url}?function=NEWS_SENTIMENT&apikey={api_key}&limit=20"
            r = _get(url)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("feed", [])[:15]:
                    articles.append({
                        "title": item.get("title", ""),
                        "summary": item.get("summary", "")[:500],
                        "content": item.get("summary", ""),
                        "url": item.get("url", ""),
                        "author": item.get("authors", [""])[0] if item.get("authors") else "",
                        "published_at": item.get("time_published", ""),
                    })

    except Exception as e:
        log.error("Error collecting %s: %s", name, e)

    return articles

def collect_source(source_id, source, keys):
    """Collect from a single source"""
    name = source["name"]
    api_type = source["api_type"]

    if api_type == "rss":
        articles = collect_rss(source, keys)
    elif api_type == "rest":
        articles = collect_rest(source, keys)
    else:
        articles = []

    return source_id, name, articles

def collect_all():
    """Collect from all working sources"""
    log.info("Golden News Collector starting")

    db = get_db()
    keys = get_api_keys()

    cursor = db.execute("""
        SELECT * FROM news_sources
        WHERE is_active = 1 AND is_working = 1
    """)
    cols = [desc[0] for desc in db.execute("SELECT * FROM news_sources").description]
    sources = cursor.fetchall()
    source_map = {row[0]: dict(zip(cols, row)) for row in sources}

    log.info("Collecting from %d working sources", len(source_map))

    all_results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(collect_source, sid, src, keys): sid
            for sid, src in source_map.items()
        }
        for future in as_completed(futures):
            sid, name, articles = future.result()
            log.info("  %s: %d articles", name, len(articles))
            all_results.append((sid, articles))

            db.execute("""
                INSERT INTO api_request_log
                (source_id, status_code, articles_fetched, requested_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (sid, 200 if articles else 204, len(articles)))

    log.info("Saving articles to database...")
    saved = 0
    for source_id, articles in all_results:
        for article in articles:
            try:
                db.execute("""
                    INSERT INTO news_articles
                    (source_id, title, summary, content, url, author,
                     published_at, fetched_at, language)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 'en')
                """, (
                    source_id,
                    article["title"],
                    article["summary"],
                    article.get("content", ""),
                    article["url"],
                    article.get("author", ""),
                    article.get("published_at", datetime.now().isoformat()),
                ))
                saved += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate

    db.commit()
    db.close()
    log.info("Collected %d new articles", saved)

    return saved

if __name__ == "__main__":
    collect_all()
