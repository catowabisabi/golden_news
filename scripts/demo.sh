#!/bin/bash
# Golden News - Start Script
# Dashboard starts immediately; collect + AI analysis run in the background.

cd "$(dirname "$0")/.."

echo "==================================="
echo "Golden News"
echo "==================================="

echo ""
echo "Step 1: Initialize Database"
python3 scripts/init_db.py

echo ""
echo "Step 2: Test APIs"
python3 src/api_tester.py

echo ""
echo "Step 3: Start WebSocket Server"
echo "   ws://localhost:8765"
python3 src/websocket_server.py &
WS_PID=$!

echo ""
echo "Step 4: Start Dashboard"
echo "   http://localhost:8050"
echo "   (collect + AI analysis run automatically in background)"
cd dashboard && python3 app.py &
DASH_PID=$!

echo ""
echo "==================================="
echo "All services started!"
echo "   Dashboard: http://localhost:8050"
echo "   WebSocket: ws://localhost:8765"
echo "==================================="
echo ""
echo "Press Ctrl+C to stop all services"

trap "kill $WS_PID $DASH_PID 2>/dev/null" EXIT
wait
