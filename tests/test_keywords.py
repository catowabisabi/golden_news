"""
Unit tests for keyword extraction in dashboard/app.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.app import _extract_keywords, _STOP_WORDS


class TestStopWords:
    def test_common_articles_excluded(self):
        for word in ("the", "a", "an"):
            assert word in _STOP_WORDS

    def test_common_verbs_excluded(self):
        for word in ("is", "are", "was", "were", "have", "had"):
            assert word in _STOP_WORDS

    def test_prepositions_excluded(self):
        for word in ("in", "on", "at", "to", "for", "of", "with", "from"):
            assert word in _STOP_WORDS

    def test_financial_noise_excluded(self):
        for word in ("percent", "rate", "data", "news"):
            assert word in _STOP_WORDS


class TestExtractKeywords:
    def test_returns_list(self):
        result = _extract_keywords("Oil prices rise sharply on OPEC decision")
        assert isinstance(result, list)

    def test_respects_limit(self):
        long_text = " ".join(f"keyword{i}" for i in range(100))
        result = _extract_keywords(long_text, limit=5)
        assert len(result) <= 5

    def test_default_limit_is_10(self):
        long_text = " ".join(f"keyword{i}" for i in range(100))
        result = _extract_keywords(long_text)
        assert len(result) <= 10

    def test_no_duplicates(self):
        result = _extract_keywords("gold gold gold silver silver")
        assert len(result) == len(set(result))

    def test_stop_words_absent(self):
        result = _extract_keywords("the market is rising because of the news report")
        for word in result:
            assert word not in _STOP_WORDS, f"Stop word leaked: {word}"

    def test_short_words_filtered(self):
        # Words < 4 chars should not appear (regex \b\w{4,}\b)
        result = _extract_keywords("oil gas war fed cut hike")
        for word in result:
            assert len(word) >= 4, f"Short word leaked: {word}"

    def test_none_input(self):
        assert _extract_keywords(None) == []

    def test_empty_input(self):
        assert _extract_keywords("") == []

    def test_real_headline(self):
        headline = (
            "Federal Reserve raises interest rates amid persistent inflation fears, "
            "sending stock markets lower across Asia and Europe"
        )
        kws = _extract_keywords(headline)
        # Should surface domain-relevant words
        assert any(w in kws for w in ("federal", "reserve", "raises", "interest", "inflation"))
        # Should not contain noise
        for w in kws:
            assert w not in _STOP_WORDS
