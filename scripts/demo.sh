#!/bin/bash
# Golden News - Start Script
# Dashboard starts immediately; collect + AI analysis run in background.

# Resolve project root without relying on `dirname` (not in Synology PATH)
PROJECT_DIR="$(cd "${0%/*}/.." 2>/dev/null && pwd)"
if [ -z "$PROJECT_DIR" ]; then
  echo "ERROR: cannot resolve project root from $0" >&2
  exit 1
fi

echo "==================================="
echo "Golden News"
echo "==================================="
echo "Project: $PROJECT_DIR"

echo ""
echo "Step 1: Initialize Database"
python3 "$PROJECT_DIR/scripts/init_db.py"

echo ""
echo "Step 2: Test APIs"
python3 "$PROJECT_DIR/src/api_tester.py"

echo ""
echo "Step 3: Start WebSocket Server"
echo "   ws://localhost:8765"
python3 "$PROJECT_DIR/src/websocket_server.py" &
WS_PID=$!

echo ""
echo "Step 4: Start Dashboard"
echo "   http://localhost:8050"
echo "   (collect + AI analysis run automatically in background)"
python3 "$PROJECT_DIR/dashboard/app.py" &
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
