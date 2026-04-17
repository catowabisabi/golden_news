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

def collect_rss(source, keys):
    """Collect from RSS feed"""
    base_url = source["base_url"]
    if not base_url:
        return []

    # Build RSS URL
    urls_to_try = []
    name = source["name"]

    if "google" in name.lower():
        urls_to_try.append(f"{base_url}/search?q=breaking+news+oil+price&hl=en-US&gl=US&ceid=US:en")
        urls_to_try.append(f"{base_url}/search?q=geopolitics+markets&hl=en-US&gl=US&ceid=US:en")
    elif "cnbc" in name.lower():
        urls_to_try.append("https://search.cnbc.com/rs/search/combinedcms/view.xml?ids=36")
    elif "bbc" in name.lower():
        urls_to_try.append(f"{base_url}/world/rss.xml")
    elif "reddit" in name.lower():
        urls_to_try.append("https://www.reddit.com/r/news/.rss")
        urls_to_try.append("https://www.reddit.com/r/worldnews/.rss")
    elif "zerohedge" in name.lower():
        urls_to_try.append("https://www.zerohedge.com/feed")
    elif "investing" in name.lower():
        urls_to_try.append(f"{base_url}/rss/news.rss")
    elif "yahoo" in name.lower():
        urls_to_try.append("https://finance.yahoo.com/news/rssindex")
    elif "guardian" in name.lower():
        urls_to_try.append("https://www.theguardian.com/world/rss")
    else:
        urls_to_try.append(f"{base_url}/feed")

    articles = []
    for url in urls_to_try:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "GoldenNews/1.0"})
            if r.status_code != 200:
                continue

            feed = feedparser.parse(r.text)
            for entry in feed.entries[:15]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:500],
                    "content": entry.get("content", [{}])[0].get("value", "")[:2000],
                    "url": entry.get("link", ""),
                    "author": entry.get("author", ""),
                    "published_at": entry.get("published", datetime.now().isoformat()),
                })
            break  # Got articles, stop trying
        except Exception:
            continue

    return articles[:10]

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
            r = requests.get(url, timeout=15)
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
            r = requests.get(url, timeout=15)
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
            r = requests.get(url, timeout=15)
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
            r = requests.get(url, timeout=15)
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
        print(f"      Error collecting {name}: {e}")

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
    print("📰 Golden News Collector")
    print("=" * 50)

    db = get_db()
    keys = get_api_keys()

    cursor = db.execute("""
        SELECT * FROM news_sources
        WHERE is_active = 1 AND is_working = 1
    """)
    cols = [desc[0] for desc in db.execute("SELECT * FROM news_sources").description]
    sources = cursor.fetchall()
    source_map = {row[0]: dict(zip(cols, row)) for row in sources}

    print(f"Collecting from {len(source_map)} working sources...\n")

    all_results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(collect_source, sid, src, keys): sid
            for sid, src in source_map.items()
        }
        for future in as_completed(futures):
            sid, name, articles = future.result()
            print(f"  {name}: {len(articles)} articles")
            all_results.append((sid, articles))

            # Log request
            db.execute("""
                INSERT INTO api_request_log
                (source_id, status_code, articles_fetched, requested_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (sid, 200 if articles else 204, len(articles)))

    # Save articles to database
    print("\n💾 Saving articles...")
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
    print(f"\n🎉 Collected {saved} new articles!")

    return saved

if __name__ == "__main__":
    collect_all()
