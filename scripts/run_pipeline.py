#!/usr/bin/env python3
"""
Golden News - Pipeline Runner

Runs the full data pipeline in sequence:
  1. Collect news from all active sources
  2. Analyse unanalysed articles and generate AI trading signals
  3. Expire signals that have exceeded their time_horizon

Designed to be called by cron or any external scheduler.

Example crontab (hourly):
  0 * * * * /usr/bin/python3 /path/to/golden_news/scripts/run_pipeline.py >> /var/log/golden_news.log 2>&1
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import collect_all
from src.ai_analyzer import process_unanalyzed_articles
from src.signal_expiry import expire_signals


def run():
    start = time.time()
    print("=" * 55)
    print("Golden News Pipeline")
    print("=" * 55)

    print("\n[1/3] Collecting news...")
    saved = collect_all()
    print(f"      → {saved} new articles saved")

    print("\n[2/3] Analysing articles...")
    process_unanalyzed_articles()

    print("\n[3/3] Expiring stale signals...")
    expired = expire_signals()
    print(f"      → {expired} signal(s) deactivated")

    elapsed = time.time() - start
    print(f"\nPipeline complete in {elapsed:.1f}s")


if __name__ == "__main__":
    run()
