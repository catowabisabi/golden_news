#!/bin/bash
# Golden News - Demo Script
# Runs everything from scratch

cd /mnt/c/Users/enoma/Desktop/golden_news

echo "==================================="
echo "🏆 Golden News - Demo Runner"
echo "==================================="

echo ""
echo "📊 Step 1: Initialize Database"
python3 scripts/init_db.py

echo ""
echo "🧪 Step 2: Test APIs"
python3 src/api_tester.py

echo ""
echo "📰 Step 3: Collect News"
python3 src/collector.py

echo ""
echo "🤖 Step 4: Generate AI Signals"
python3 src/ai_analyzer.py

echo ""
echo "🌐 Step 5: Start WebSocket Server"
echo "   ws://localhost:8765"
python3 src/websocket_server.py &
WS_PID=$!

echo ""
echo "📊 Step 6: Start Dashboard"
echo "   http://localhost:8050"
cd dashboard && python3 app.py &
DASH_PID=$!

echo ""
echo "==================================="
echo "🎉 All services started!"
echo "   Dashboard: http://localhost:8050"
echo "   WebSocket: ws://localhost:8765"
echo "==================================="
echo ""
echo "Press Ctrl+C to stop all services"
wait
