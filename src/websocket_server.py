#!/usr/bin/env python3
"""
Golden News - WebSocket Server
Real-time news streaming to connected clients
"""
import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
import websockets
from websockets.server import serve

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

# Connected clients
CONNECTED_CLIENTS = set()
SUBSCRIPTIONS = {}  # client_id -> set of categories

class NewsBroadcaster:
    def __init__(self):
        self.clients = set()
        self.lock = asyncio.Lock()

    async def register(self, websocket):
        await asyncio.wait([w.send(json.dumps({
            "type": "connected",
            "message": "Connected to Golden News WebSocket",
            "timestamp": datetime.now().isoformat()
        })) for w in self.clients])

        async with self.lock:
            self.clients.add(websocket)
        print(f"✅ Client connected. Total: {len(self.clients)}")

    async def unregister(self, websocket):
        async with self.lock:
            self.clients.discard(websocket)
        print(f"👋 Client disconnected. Total: {len(self.clients)}")

    async def broadcast(self, message):
        if not self.clients:
            return
        msg = json.dumps(message, default=str)
        async with self.lock:
            dead = set()
            for client in self.clients:
                try:
                    await client.send(msg)
                except Exception:
                    dead.add(client)
            self.clients -= dead

    async def broadcast_new_article(self, article):
        await self.broadcast({
            "type": "new_article",
            "data": article,
            "timestamp": datetime.now().isoformat()
        })

    async def broadcast_trading_signal(self, signal):
        await self.broadcast({
            "type": "trading_signal",
            "data": signal,
            "timestamp": datetime.now().isoformat()
        })

broadcaster = NewsBroadcaster()

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def get_latest_articles(minutes=30, limit=20):
    """Get latest articles from database"""
    db = get_db()
    cursor = db.execute("""
        SELECT a.id, a.title, a.summary, a.url, a.source_id,
               a.published_at, a.fetched_at, a.sentiment_score,
               a.sentiment_label, a.is_trading_signal,
               s.display_name as source_name, s.category
        FROM news_articles a
        JOIN news_sources s ON a.source_id = s.id
        WHERE a.fetched_at > datetime('now', '-' || ? || ' minutes')
        ORDER BY a.fetched_at DESC
        LIMIT ?
    """, (minutes, limit))
    cols = [desc[0] for desc in db.execute("SELECT * FROM news_articles LIMIT 1").description]
    cols.extend(["source_name", "category"])
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

def get_active_signals(limit=10):
    """Get active trading signals"""
    db = get_db()
    cursor = db.execute("""
        SELECT ts.*, a.title as article_title, s.display_name as source_name
        FROM trading_signals ts
        JOIN news_articles a ON ts.article_id = a.id
        JOIN news_sources s ON a.source_id = s.id
        WHERE ts.is_active = 1
        ORDER BY ts.generated_at DESC
        LIMIT ?
    """, (limit,))
    cols = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

def get_api_status():
    """Get API status summary"""
    db = get_db()
    cursor = db.execute("""
        SELECT category, COUNT(*) as total,
               SUM(CASE WHEN is_working = 1 THEN 1 ELSE 0 END) as working
        FROM news_sources
        WHERE is_active = 1
        GROUP BY category
    """)
    cols = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

async def handle_client(websocket):
    await broadcaster.register(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                cmd = data.get("command")

                if cmd == "ping":
                    await websocket.send(json.dumps({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    }))

                elif cmd == "get_latest":
                    articles = get_latest_articles(
                        minutes=data.get("minutes", 30),
                        limit=data.get("limit", 20)
                    )
                    await websocket.send(json.dumps({
                        "type": "latest_articles",
                        "data": articles,
                        "timestamp": datetime.now().isoformat()
                    }))

                elif cmd == "get_signals":
                    signals = get_active_signals(limit=data.get("limit", 10))
                    await websocket.send(json.dumps({
                        "type": "trading_signals",
                        "data": signals,
                        "timestamp": datetime.now().isoformat()
                    }))

                elif cmd == "get_status":
                    status = get_api_status()
                    await websocket.send(json.dumps({
                        "type": "api_status",
                        "data": status,
                        "timestamp": datetime.now().isoformat()
                    }))

                elif cmd == "subscribe":
                    cat = data.get("category")
                    if cat:
                        if id(websocket) not in SUBSCRIPTIONS:
                            SUBSCRIPTIONS[id(websocket)] = set()
                        SUBSCRIPTIONS[id(websocket)].add(cat)
                        await websocket.send(json.dumps({
                            "type": "subscribed",
                            "category": cat
                        }))

                elif cmd == "unsubscribe":
                    cat = data.get("category")
                    if cat and id(websocket) in SUBSCRIPTIONS:
                        SUBSCRIPTIONS[id(websocket)].discard(cat)

            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON"
                }))
    finally:
        await broadcaster.unregister(websocket)

async def poll_database(broadcaster, interval=15):
    """Poll database for new articles and broadcast"""
    last_check = datetime.now()

    while True:
        await asyncio.sleep(interval)

        db = get_db()
        cursor = db.execute("""
            SELECT a.id, a.title, a.summary, a.url,
                   a.published_at, a.fetched_at, a.sentiment_score,
                   a.is_trading_signal,
                   s.display_name as source_name, s.category
            FROM news_articles a
            JOIN news_sources s ON a.source_id = s.id
            WHERE a.fetched_at > ?
            ORDER BY a.fetched_at DESC
            LIMIT 10
        """, (last_check.isoformat(),))
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        db.close()

        if rows:
            last_check = datetime.now()
            for row in reversed(rows):
                article = dict(zip(cols, row))
                await broadcaster.broadcast_new_article(article)

        # Also check for new trading signals
        db = get_db()
        cursor = db.execute("""
            SELECT ts.*, a.title as article_title, s.display_name as source_name
            FROM trading_signals ts
            JOIN news_articles a ON ts.article_id = a.id
            JOIN news_sources s ON a.source_id = s.id
            WHERE ts.generated_at > ?
            ORDER BY ts.generated_at DESC
            LIMIT 5
        """, (last_check.isoformat(),))
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        db.close()

        for row in rows:
            signal = dict(zip(cols, row))
            await broadcaster.broadcast_trading_signal(signal)

async def main(port=8765):
    print(f"🌐 Starting Golden News WebSocket Server on port {port}...")
    print(f"📊 Connect via: ws://localhost:{port}")
    print("\nAvailable commands:")
    print("  ping              - Health check")
    print("  get_latest        - Get latest articles")
    print("  get_signals       - Get active trading signals")
    print("  get_status        - Get API status")
    print("  subscribe         - Subscribe to category updates")
    print()

    # Start database poller
    poller = asyncio.create_task(poll_database(broadcaster, interval=15))

    async with serve(handle_client, "0.0.0.0", port):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        import sys
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
        asyncio.run(main(port))
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
