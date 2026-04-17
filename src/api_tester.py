#!/usr/bin/env python3
"""
Golden News - API Tester
Tests all news APIs and marks them as working/not working
"""
import sqlite3
import json
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent

def get_db():
    return sqlite3.connect(PROJECT_ROOT / "database" / "golden_news.db")

def get_api_keys():
    keys_path = PROJECT_ROOT / "config" / "api_keys.json"
    if not keys_path.exists():
        return {}
    with open(keys_path) as f:
        return json.load(f)

def test_rss(source, keys):
    """Test RSS feed"""
    base_url = source["base_url"]
    if not base_url:
        return False, 0, "No base_url"

    urls_to_try = []
    if "google" in base_url.lower():
        urls_to_try.append(f"{base_url}/search?q=breaking+news&hl=en-US&gl=US&ceid=US:en")
    elif "reddit" in base_url.lower():
        urls_to_try.append(f"{base_url}.rss")
    elif "cnbc" in base_url.lower():
        urls_to_try.append("https://search.cnbc.com/rs/search/combinedcms/view.xml?ids=36")
    elif "zerohedge" in base_url.lower():
        urls_to_try.append("https://www.zerohedge.com/feed")
    elif "investing" in base_url.lower():
        urls_to_try.append(f"{base_url}")
    else:
        urls_to_try.append(f"{base_url}/news")

    for url in urls_to_try:
        try:
            start = time.time()
            r = requests.get(url, timeout=10, headers={"User-Agent": "GoldenNews/1.0"})
            elapsed = int((time.time() - start) * 1000)
            if r.status_code == 200 and len(r.text) > 100:
                return True, elapsed, None
        except Exception as e:
            continue
    return False, 0, "All URLs failed"

def test_rest(source, keys):
    """Test REST API"""
    base_url = source["base_url"]
    required = json.loads(source.get("required_keys", "[]"))

    # Get first available key
    api_key = None
    for req in required:
        if keys.get(req):
            api_key = keys[req]
            break

    if not api_key and required:
        return False, 0, f"Missing keys: {required}"

    # Test based on source
    if source["name"] == "newsapi_org":
        url = f"{base_url}/top-headlines?country=us&category=business&apiKey={api_key}"
    elif source["name"] == "mediastack":
        url = f"{base_url}/news?access_key={api_key}&categories=business,science"
    elif source["name"] == "bing_news_search":
        url = f"{base_url}/news/search?q=breaking+news&mkt=en-US&count=5"
        headers = {"Ocp-Apim-Subscription-Key": api_key}
    elif source["name"] == "finnhub":
        url = f"{base_url}/news?token={api_key}&category=general"
        headers = {}
    elif source["name"] == "alpha_vantage":
        url = f"{base_url}?function=NEWS_SENTIMENT&apikey={api_key}"
        headers = {}
    elif source["name"] == "newsdata_io":
        url = f"{base_url}/news?apikey={api_key}&language=en"
        headers = {}
    elif source["name"] == "gdelt_project":
        url = f"{base_url}/query?query=oil+price&maxrecords=10&output=json"
        headers = {}
    else:
        return False, 0, f"No test defined for {source['name']}"

    try:
        start = time.time()
        r = requests.get(url, timeout=15, headers=headers if 'headers' in dir() else {"User-Agent": "GoldenNews/1.0"})
        elapsed = int((time.time() - start) * 1000)
        if r.status_code == 200 and len(r.text) > 50:
            return True, elapsed, None
        else:
            return False, elapsed, f"HTTP {r.status_code}"
    except Exception as e:
        return False, 0, str(e)[:100]

def test_api(source_id, source, keys):
    """Test a single API"""
    api_type = source["api_type"]
    if api_type == "rss":
        ok, ms, err = test_rss(source, keys)
    elif api_type == "rest":
        ok, ms, err = test_rest(source, keys)
    else:
        ok, ms, err = (False, 0, f"Unsupported api_type: {api_type}")

    return source_id, ok, ms, err

def test_all_apis():
    print("🧪 Golden News - Testing All APIs")
    print("=" * 60)

    db = get_db()
    keys = get_api_keys()

    cursor = db.execute("SELECT * FROM news_sources WHERE is_active = 1")
    sources = cursor.fetchall()
    cols = [desc[0] for desc in db.execute("SELECT * FROM news_sources").description]

    source_map = {row[0]: dict(zip(cols, row)) for row in sources}

    print(f"Testing {len(source_map)} sources...\n")

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(test_api, sid, src, keys): sid
            for sid, src in source_map.items()
        }
        for future in as_completed(futures):
            sid, ok, ms, err = future.result()
            src = source_map[sid]
            status = "✅ WORKING" if ok else "❌ FAILED"
            rate_limit = src.get("rate_limit_rpm", "?")
            free_or_paid = "💰 PAID" if src["is_paid"] else "🆓 FREE"
            print(f"  {status} | {rate_limit} rpm | {free_or_paid} | {src['display_name']}")
            if err:
                print(f"           └─ {err}")
            if ms:
                print(f"           └─ {ms}ms")
            results.append((sid, ok, ms, err))

    # Update database
    print("\n💾 Updating database...")
    cursor = db.cursor()
    for sid, ok, ms, err in results:
        cursor.execute("""
            UPDATE news_sources
            SET is_working = ?, last_tested_at = datetime('now'),
                last_response_time_ms = ?
            WHERE id = ?
        """, (1 if ok else 0, ms, sid))
    db.commit()
    db.close()

    # Summary
    working = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n📊 Summary: {working}/{len(results)} APIs working")
    return results

if __name__ == "__main__":
    test_all_apis()
