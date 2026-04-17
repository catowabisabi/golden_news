-- ============================================================
-- Golden News - SQLite Database Schema
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================
-- NEWS SOURCES: All configured news APIs
-- ============================================================
CREATE TABLE IF NOT EXISTS news_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN (
        'breaking', 'finance', 'energy', 'geopolitics',
        'crypto', 'commodities', 'general', 'social'
    )),
    api_type TEXT NOT NULL CHECK (api_type IN (
        'rest', 'websocket', 'rss', 'websocket_stream'
    )),
    base_url TEXT,
    docs_url TEXT,
    is_paid INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_working INTEGER,  -- NULL=untested, 0=failed, 1=working
    last_tested_at TEXT,
    last_response_time_ms INTEGER,
    rate_limit_rpm INTEGER,
    monthly_cost_usd REAL,
    description TEXT,
    required_keys TEXT,  -- JSON array of required key names
    config_schema TEXT,  -- JSON schema for source-specific config
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- API KEYS: Stored encrypted API keys
-- ============================================================
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name TEXT NOT NULL UNIQUE,
    key_value TEXT NOT NULL,  -- Stored as-is for demo; in production, encrypt
    key_type TEXT NOT NULL CHECK (key_type IN (
        'openai', 'minimax_chat', 'minimax_tts',
        'newsapi', 'mediastack', 'bing_search',
        'twitter_bearer', 'twitter_api', 'reuters',
        'bloomberg', 'finnhub', 'alphavantage',
        'newsdata', 'websearch', 'custom'
    )),
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- NEWS ARTICLES: Collected articles
-- ============================================================
CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES news_sources(id),
    source_article_id TEXT,  -- Original ID from source
    title TEXT NOT NULL,
    summary TEXT,
    content TEXT,
    url TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    language TEXT DEFAULT 'en',
    sentiment_score REAL,  -- -1 to 1
    sentiment_label TEXT CHECK (sentiment_label IN ('positive', 'negative', 'neutral')),
    is_analyzed INTEGER NOT NULL DEFAULT 0,
    is_trading_signal INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_id, source_article_id)
);

-- ============================================================
-- KEYWORDS: Extracted keywords per article
-- ============================================================
CREATE TABLE IF NOT EXISTS article_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    relevance_score REAL DEFAULT 1.0,
    is_entity INTEGER DEFAULT 0,  -- Named entity
    entity_type TEXT  -- person, org, location, etc.
);

-- ============================================================
-- TRADING SIGNALS: AI-generated signals
-- ============================================================
CREATE TABLE IF NOT EXISTS trading_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES news_articles(id),
    signal_type TEXT NOT NULL CHECK (signal_type IN (
        'alpha', 'trade_idea', 'risk_alert', 'momentum', 'reversal'
    )),
    asset_class TEXT CHECK (asset_class IN (
        'oil', 'gold', 'stocks', 'crypto', 'bonds', 'forex', 'commodities', 'multi'
    )),
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short', 'neutral')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    headline TEXT NOT NULL,
    rationale TEXT,
    entry_price TEXT,  -- Can be "current" or a price range
    exit_price TEXT,
    stop_loss TEXT,
    time_horizon TEXT,  -- intraday, short-term, medium-term
    is_active INTEGER NOT NULL DEFAULT 1,
    ai_model TEXT,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- NEWS GRAPH: Relationships between articles
-- ============================================================
CREATE TABLE IF NOT EXISTS news_graph (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_a_id INTEGER NOT NULL REFERENCES news_articles(id),
    article_b_id INTEGER NOT NULL REFERENCES news_articles(id),
    relationship_type TEXT NOT NULL CHECK (relationship_type IN (
        'same_event', 'same_asset', 'same_theme', 'causal',
        'contradicts', 'confirms', 'updates'
    )),
    strength REAL NOT NULL DEFAULT 0.5 CHECK (strength >= 0 AND strength <= 1),
    shared_keywords TEXT,  -- JSON array of shared keywords
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(article_a_id, article_b_id)
);

-- ============================================================
-- API REQUEST LOG: For debugging & rate limiting
-- ============================================================
CREATE TABLE IF NOT EXISTS api_request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES news_sources(id),
    endpoint TEXT,
    status_code INTEGER,
    response_time_ms INTEGER,
    articles_fetched INTEGER DEFAULT 0,
    error_message TEXT,
    requested_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- MARKET DATA: Price data for correlation
-- ============================================================
CREATE TABLE IF NOT EXISTS market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    change_pct REAL,
    volume INTEGER,
    source TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- USER PREFERENCES: Configurable settings
-- ============================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_articles_source ON news_articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_published ON news_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON news_articles(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_analyzed ON news_articles(is_analyzed);
CREATE INDEX IF NOT EXISTS idx_keywords_article ON article_keywords(article_id);
CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON article_keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_signals_active ON trading_signals(is_active, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_article ON trading_signals(article_id);
CREATE INDEX IF NOT EXISTS idx_graph_a ON news_graph(article_a_id);
CREATE INDEX IF NOT EXISTS idx_graph_b ON news_graph(article_b_id);
CREATE INDEX IF NOT EXISTS idx_market_symbol ON market_prices(symbol, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_source ON api_request_log(source_id, requested_at DESC);

-- ============================================================
-- TRIGGERS
-- ============================================================
CREATE TRIGGER IF NOT EXISTS tr_sources_updated
AFTER UPDATE ON news_sources
BEGIN
    UPDATE news_sources SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS tr_keys_updated
AFTER UPDATE ON api_keys
BEGIN
    UPDATE api_keys SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS tr_prefs_updated
AFTER UPDATE ON user_preferences
BEGIN
    UPDATE user_preferences SET updated_at = datetime('now') WHERE id = NEW.id;
END;
