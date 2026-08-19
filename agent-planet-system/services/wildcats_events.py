# services/wildcats_events.py — Wildcats.io event fetcher with TTL cache
import logging
import time
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("wildtails.wildcats_events")

EVENTS_URL = "https://www.wildcats.io/event-list"
FETCH_TIMEOUT = 15  # seconds
DEFAULT_TTL = 600  # 10 minutes
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


@dataclass
class WildcatsEvent:
    title: str
    description: str = ""
    event_date: str = ""
    location: str = ""
    event_url: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class WildcatsEventCache:
    """In-memory TTL cache for Wildcats events."""

    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self._events: list[WildcatsEvent] = []
        self._last_fetched: float = 0.0

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._last_fetched) > self.ttl

    @property
    def events(self) -> list[WildcatsEvent]:
        return list(self._events)

    def refresh(self, use_fixture: bool = False) -> list[WildcatsEvent]:
        """Fetch and parse events. Returns cached list on success."""
        try:
            if use_fixture:
                html = self._load_fixture()
            else:
                html = self._fetch_live()

            if html:
                self._events = parse_events_html(html)
                self._last_fetched = time.time()
                logger.info("Refreshed %d Wildcats events", len(self._events))
        except Exception as e:
            logger.warning("Event refresh failed (serving stale cache): %s", e)

        return self._events

    def get_events(self, use_fixture: bool = False) -> list[WildcatsEvent]:
        """Return events, refreshing automatically if stale."""
        if self.is_stale or not self._events:
            self.refresh(use_fixture=use_fixture)
        return self.events

    def search(self, query: str, top_k: int = 5) -> list[WildcatsEvent]:
        """Simple keyword search across title, description, and tags."""
        query_lower = query.lower()
        keywords = query_lower.split()

        scored: list[tuple[int, WildcatsEvent]] = []
        for event in self._events:
            searchable = f"{event.title} {event.description} {' '.join(event.tags)}".lower()
            score = sum(1 for kw in keywords if kw in searchable)
            if score > 0:
                scored.append((score, event))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ev for _, ev in scored[:top_k]]

    @staticmethod
    def _fetch_live() -> str | None:
        try:
            headers = {
                "User-Agent": "WildTails-EventBot/1.0",
                "Accept": "text/html",
            }
            resp = requests.get(EVENTS_URL, timeout=FETCH_TIMEOUT, headers=headers)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.warning("Live fetch from %s failed: %s", EVENTS_URL, e)
            return None

    @staticmethod
    def _load_fixture() -> str | None:
        fixture_path = FIXTURE_DIR / "wildcats_events.html"
        if fixture_path.exists():
            return fixture_path.read_text(encoding="utf-8")
        logger.warning("Fixture file not found at %s", fixture_path)
        return None


def parse_events_html(html: str) -> list[WildcatsEvent]:
    """Parse Wildcats event-list HTML into structured events.

    This parser handles common event-list page patterns:
    - Collection items with title, date, description, location, link
    - Falls back to generic heading + paragraph extraction
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[WildcatsEvent] = []

    # Strategy 1: Look for structured collection/event items
    # Common class patterns on event-list pages
    items = soup.select(
        ".collection-item, .event-item, .w-dyn-item, [data-event]"
    )

    if items:
        for item in items:
            event = _parse_event_item(item)
            if event and event.title:
                events.append(event)

    # Strategy 2: Fallback — extract from headings + sibling text
    if not events:
        headings = soup.find_all(["h2", "h3", "h4"])
        for heading in headings:
            title = heading.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            desc_parts = []
            for sib in heading.find_next_siblings():
                if sib.name in ("h2", "h3", "h4"):
                    break
                text = sib.get_text(strip=True)
                if text:
                    desc_parts.append(text)

            link_tag = heading.find("a") or heading.find_parent("a")
            event_url = ""
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                if not href.startswith("http"):
                    href = f"https://www.wildcats.io{href}"
                event_url = href

            events.append(WildcatsEvent(
                title=title,
                description=" ".join(desc_parts)[:500],
                event_url=event_url,
            ))

    return events


def _parse_event_item(item) -> WildcatsEvent | None:
    """Extract structured data from a single event DOM element."""
    # Title
    title_el = item.find(["h2", "h3", "h4", "h5"]) or item.find(class_=re.compile(r"title|name", re.I))
    title = title_el.get_text(strip=True) if title_el else ""

    if not title:
        return None

    # Description
    desc_el = item.find(class_=re.compile(r"desc|summary|excerpt|text|body", re.I))
    if not desc_el:
        desc_el = item.find("p")
    description = desc_el.get_text(strip=True)[:500] if desc_el else ""

    # Date
    date_el = item.find("time") or item.find(class_=re.compile(r"date|time|when", re.I))
    event_date = ""
    if date_el:
        event_date = date_el.get("datetime", "") or date_el.get_text(strip=True)

    # Location
    loc_el = item.find(class_=re.compile(r"location|venue|place|where", re.I))
    location = loc_el.get_text(strip=True) if loc_el else ""

    # Link
    link_el = item.find("a", href=True)
    event_url = ""
    if link_el:
        href = link_el["href"]
        if not href.startswith("http"):
            href = f"https://www.wildcats.io{href}"
        event_url = href

    # Tags
    tags = []
    tag_els = item.find_all(class_=re.compile(r"tag|category|label|badge", re.I))
    for tag_el in tag_els:
        tag_text = tag_el.get_text(strip=True)
        if tag_text:
            tags.append(tag_text.lower())

    return WildcatsEvent(
        title=title,
        description=description,
        event_date=event_date,
        location=location,
        event_url=event_url,
        tags=tags,
    )


# Module-level singleton cache
event_cache = WildcatsEventCache()
