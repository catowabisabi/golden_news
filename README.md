# 🏆 Golden News - Real-Time News Intelligence System

> AI-powered news aggregation, analysis & trading signal generation

## Overview

Golden News is a real-time news intelligence platform that:
- Aggregates news from 30+ APIs (free & paid)
- Tests API health automatically
- Generates AI-powered trading signals and alpha ideas
- Visualizes news relationships as an interactive graph

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp config/api_keys.example.json config/api_keys.json
# Edit config/api_keys.json with your keys

# Run the news collector
python src/collector.py

# Run the WebSocket server
python src/websocket_server.py

# Run the dashboard
cd dashboard && python -m http.server 8050
```

## Architecture

```
golden_news/
├── config/
│   ├── api_keys.json       # Your API keys (user-configured)
│   └── news_sources.json    # All news source definitions
├── database/
│   ├── schema.sql          # SQLite schema
│   └── golden_news.db      # SQLite database
├── src/
│   ├── collector.py        # News collection from all sources
│   ├── api_tester.py       # Tests API health
│   ├── websocket_server.py # Real-time WebSocket server
│   ├── ai_analyzer.py      # AI trading signal generation
│   └── news_graph.py       # News relationship graph builder
├── dashboard/
│   ├── index.html          # Interactive visualization
│   └── app.py              # Plotly Dash dashboard
├── tests/
│   └── test_apis.py        # API tests
├── scripts/
│   ├── init_db.py          # Initialize database
│   └── seed_sources.py     # Seed news sources
└── requirements.txt
```

## Features

- **30+ News APIs**: Free and paid, tested and flagged
- **Real-time WebSocket**: Push news to clients instantly
- **AI Trading Signals**: GPT-4/MiniMax-powered alpha generation
- **News Graph**: D3.js visualization of linked news relationships
- **Color-coded**: News connected by theme/color with lines

## API Keys Needed

Create `config/api_keys.json`:

```json
{
  "openai": "your-openai-key",
  "minimax_chat": "your-minimax-chat-key",
  "minimax_tts": "your-minimax-tts-key",
  "newsapi": "your-newsapi-key",
  "mediastack": "your-mediastack-key",
  "bing_search": "your-bing-key",
  "twitter_bearer": "your-twitter-bearer-token"
}
```

## License

MIT
