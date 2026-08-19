# tests/test_events.py — Wildcats event parser tests using local HTML fixture
"""
Tests for the Wildcats event parsing, caching, and search logic.
All tests use the local HTML fixture — no internet required.
"""
import time
import pytest
from services.wildcats_events import (
    WildcatsEventCache,
    WildcatsEvent,
    parse_events_html,
)


@pytest.fixture
def cache():
    """Fresh cache instance with short TTL for testing."""
    return WildcatsEventCache(ttl=2)


@pytest.fixture
def loaded_cache(cache):
    """Cache pre-loaded from fixture."""
    cache.refresh(use_fixture=True)
    return cache


class TestEventParsing:
    """Tests for HTML parsing into WildcatsEvent objects."""

    def test_fixture_parses_five_events(self, loaded_cache):
        events = loaded_cache.events
        assert len(events) == 5

    def test_event_titles(self, loaded_cache):
        titles = [e.title for e in loaded_cache.events]
        assert "Startup Pitch Night" in titles
        assert "AI Hackathon 2026" in titles
        assert "Digital Wellness Retreat" in titles
        assert "Creative Writing Workshop" in titles
        assert "Wildcats Gaming Tournament" in titles

    def test_event_dates_parsed(self, loaded_cache):
        hackathon = [e for e in loaded_cache.events if "Hackathon" in e.title][0]
        assert hackathon.event_date == "2026-10-01"

    def test_event_locations(self, loaded_cache):
        workshop = [e for e in loaded_cache.events if "Writing" in e.title][0]
        assert workshop.location == "Online"

    def test_event_tags(self, loaded_cache):
        hackathon = [e for e in loaded_cache.events if "Hackathon" in e.title][0]
        assert "ai" in hackathon.tags
        assert "hackathon" in hackathon.tags
        assert "coding" in hackathon.tags

    def test_event_urls_absolute(self, loaded_cache):
        for event in loaded_cache.events:
            if event.event_url:
                assert event.event_url.startswith("https://www.wildcats.io/")

    def test_event_descriptions_not_empty(self, loaded_cache):
        for event in loaded_cache.events:
            assert len(event.description) > 10

    def test_to_dict_serialization(self, loaded_cache):
        d = loaded_cache.events[0].to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {"title", "description", "event_date", "location", "event_url", "tags"}


class TestEventSearch:
    """Tests for keyword search ranking."""

    def test_search_ai_hackathon(self, loaded_cache):
        results = loaded_cache.search("ai hackathon")
        assert len(results) >= 1
        assert results[0].title == "AI Hackathon 2026"

    def test_search_gaming(self, loaded_cache):
        results = loaded_cache.search("gaming tournament rpg")
        assert len(results) >= 1
        assert results[0].title == "Wildcats Gaming Tournament"

    def test_search_wellness(self, loaded_cache):
        results = loaded_cache.search("wellness mindfulness retreat")
        assert results[0].title == "Digital Wellness Retreat"

    def test_search_no_results(self, loaded_cache):
        results = loaded_cache.search("quantum physics blockchain")
        assert len(results) == 0

    def test_search_top_k_limit(self, loaded_cache):
        results = loaded_cache.search("event", top_k=2)
        assert len(results) <= 2


class TestCacheTTL:
    """Tests for TTL-based cache expiry."""

    def test_fresh_cache_is_stale(self, cache):
        assert cache.is_stale  # never fetched

    def test_loaded_cache_is_not_stale(self, loaded_cache):
        assert not loaded_cache.is_stale

    def test_cache_becomes_stale_after_ttl(self, loaded_cache):
        loaded_cache._last_fetched = time.time() - 10
        assert loaded_cache.is_stale

    def test_auto_refresh_on_stale(self, cache):
        """get_events should auto-refresh when stale."""
        events = cache.get_events(use_fixture=True)
        assert len(events) == 5
        assert not cache.is_stale


class TestEdgeCases:
    """Edge cases in HTML parsing."""

    def test_empty_html_returns_empty(self):
        events = parse_events_html("")
        assert events == []

    def test_html_with_no_events(self):
        events = parse_events_html("<html><body><p>No events here</p></body></html>")
        assert events == []

    def test_malformed_html_does_not_crash(self):
        events = parse_events_html("<div class='event-item'><h3></h3></div>")
        assert isinstance(events, list)
