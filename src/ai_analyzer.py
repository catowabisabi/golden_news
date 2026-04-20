#!/usr/bin/env python3
"""
Golden News - AI Analyzer
Generates trading signals and alpha ideas from news using LLM
"""
import sqlite3
import json
import os
import anthropic
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

MINIMAX_CHAT_KEY = os.environ.get("MINIMAX_CHAT_KEY", "")

class AIAnalyzer:
    def __init__(self):
        self.client = anthropic.Anthropic(
            base_url='https://api.minimax.io/anthropic',
            api_key=MINIMAX_CHAT_KEY
        )

    def analyze_article(self, article_text, title):
        """Analyze article and generate detailed trading signal"""

        system_prompt = """You are Golden News AI - a financial trading signal generator.

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

        user_prompt = f"Title: {title}\n\nContent: {article_text[:2000]}"

        try:
            response = self.client.messages.create(
                model="MiniMax-M2.7",
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )

            text = "".join(block.text for block in response.content if block.type == "text")

            # Parse JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end != 0:
                json_str = text[start:end]
                signal = json.loads(json_str)
                signal["ai_model"] = "minimax-m2.7"
                return signal
        except Exception as e:
            print(f"      Error: {e}")

        return None

def process_unanalyzed_articles():
    """Process all unanalyzed articles and generate signals"""
    print("🤖 Golden News AI Analyzer")
    print("=" * 50)

    analyzer = AIAnalyzer()
    db = sqlite3.connect(DB_PATH)

    # Sample up to 5 articles from each source to ensure asset-class diversity
    cursor = db.execute("""
        SELECT id, title, summary, content FROM (
            SELECT a.id, a.title, a.summary, a.content, a.source_id,
                   ROW_NUMBER() OVER (PARTITION BY a.source_id ORDER BY a.fetched_at DESC) AS rn
            FROM news_articles a
            WHERE a.is_analyzed = 0 AND (a.summary IS NOT NULL OR a.content IS NOT NULL)
        )
        WHERE rn <= 5
        ORDER BY RANDOM()
        LIMIT 30
    """)
    articles = cursor.fetchall()

    if not articles:
        print("   No new articles to analyze")
        db.close()
        return

    print(f"   Found {len(articles)} articles to analyze\n")

    for article_id, title, summary, content in articles:
        article_text = summary or content or ""
        if not article_text.strip():
            db.execute("UPDATE news_articles SET is_analyzed = 1 WHERE id = ?", (article_id,))
            continue

        print(f"   📰 {title[:60]}...")

        signal = analyzer.analyze_article(article_text, title)

        if signal and signal.get("signal_type") != "none":
            # Determine direction
            direction = signal.get("direction", "neutral")
            if direction not in ("long", "short", "neutral"):
                direction = "neutral"

            # Save trading signal
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
                signal.get("ai_model", "unknown")
            ))

            db.execute("""
                UPDATE news_articles
                SET is_analyzed = 1, is_trading_signal = 1
                WHERE id = ?
            """, (article_id,))

            ticker = signal.get("ticker", "")
            conf = int(signal.get("confidence", 0) * 100)
            print(f"      ✅ {direction.upper()} {signal.get('asset_class', '').upper()} | {conf}% | {ticker}")
        else:
            db.execute("UPDATE news_articles SET is_analyzed = 1 WHERE id = ?", (article_id,))
            print(f"      ⏭️  No signal")

    db.commit()
    db.close()
    print("\n🎉 Analysis complete!")

if __name__ == "__main__":
    process_unanalyzed_articles()
