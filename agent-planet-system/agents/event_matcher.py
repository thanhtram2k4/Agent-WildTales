# agents/event_matcher.py — Wildcats Event Matcher Agent V2
# Scope: Semantic matching of user interests against embedded Wildcats events
# Returns ONLY real event data (title, URL, date) — never fabricates events
# V3: Proactive goal-aware matching with deduplication
import logging
import re
import time
from collections import defaultdict

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.event_matcher")

# ---------------------------------------------------------------------------
# Relevance gate — keywords/patterns that signal a journal entry is seeking
# networking, learning, or events.  Kept as module-level constants so
# unit tests can assert against them.
# ---------------------------------------------------------------------------
_INTEREST_KEYWORDS = [
    # Vietnamese
    "muốn học", "tìm hiểu", "quan tâm", "sự kiện", "workshop", "meetup",
    "networking", "gặp gỡ", "kết nối", "cộng đồng", "khóa học", "hội thảo",
    "seminar", "tham gia", "đăng ký", "hackathon", "bootcamp", "mentor",
    "dự án", "cơ hội", "tình nguyện", "volunteer",
    # English fallback
    "event", "learn", "connect", "join", "community", "opportunity",
]

_INTEREST_RE = re.compile(
    "|".join(re.escape(kw) for kw in _INTEREST_KEYWORDS),
    re.IGNORECASE,
)

# Deduplication: remember (user_id, event_title) pairs we already sent.
# Bounded per user to avoid unbounded memory growth.
_MAX_DEDUP_PER_USER = 50
_DEDUP_TTL_SECONDS = 24 * 60 * 60  # 24 hours


class _DeduplicationCache:
    """Track which events have already been surfaced to each user."""

    def __init__(self):
        # {user_id: {event_title_lower: timestamp_sent}}
        self._sent: dict[str, dict[str, float]] = defaultdict(dict)

    def is_duplicate(self, user_id: str, event_title: str) -> bool:
        title_key = event_title.strip().lower()
        sent_map = self._sent.get(user_id, {})
        ts = sent_map.get(title_key)
        if ts is None:
            return False
        # Expired entries are not duplicates
        if time.time() - ts > _DEDUP_TTL_SECONDS:
            del sent_map[title_key]
            return False
        return True

    def mark_sent(self, user_id: str, event_title: str) -> None:
        title_key = event_title.strip().lower()
        sent_map = self._sent[user_id]
        sent_map[title_key] = time.time()
        # Evict oldest entries if over limit
        if len(sent_map) > _MAX_DEDUP_PER_USER:
            oldest_key = min(sent_map, key=sent_map.get)
            del sent_map[oldest_key]


def should_match_events(message: str, active_goals: list[dict] | None = None) -> bool:
    """Relevance gate: decide if a journal entry warrants event matching.

    Returns True when the message text (or the user's active goal titles)
    contain interest-signalling keywords.  This prevents the Event Scout
    from spamming every single public journal entry.
    """
    # Check the journal message itself
    if _INTEREST_RE.search(message):
        return True

    # Check active goal titles for latent interest signals
    if active_goals:
        combined = " ".join(g.get("title", "") for g in active_goals)
        if _INTEREST_RE.search(combined):
            return True

    return False


class EventMatcherAgent(BaseAgent):

    def __init__(self):
        super().__init__()
        self._dedup = _DeduplicationCache()

    @property
    def agent_name(self) -> str:
        return "Wildcats Event Scout"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Wildcats Event Scout", chuyên viên tìm kiếm sự kiện trong vũ trụ WildTails.\n'
            "Nhiệm vụ:\n"
            "1. Phân tích sở thích, tâm trạng, và nội dung chia sẻ của người dùng.\n"
            "2. Giới thiệu 1-2 sự kiện phù hợp nhất từ danh sách Wildcats.\n"
            "3. Giải thích ngắn gọn vì sao sự kiện này phù hợp với họ.\n"
            "Phản hồi bằng tiếng Việt, ngắn gọn (3-4 câu). "
            "Format tên sự kiện rõ ràng, kèm ngày và link nếu có.\n"
            "QUAN TRỌNG: CHỈ giới thiệu sự kiện từ dữ liệu được cung cấp. KHÔNG bịa ra sự kiện."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle EVENT_MATCH_REQUEST events (both explicit and proactive).

        Deterministic routing: this agent no longer responds to every
        NEW_USER_JOINED event (which caused spam). It only activates on
        event match requests — which the backend now emits proactively
        when the relevance gate fires.
        """
        return data.get("type") == "EVENT_MATCH_REQUEST"

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")
        query = data.get("query", "")

        if not query:
            return

        # Use semantic matching API to find relevant events
        matches = self._semantic_match(query)
        if not matches:
            return

        # Deduplicate: filter out events this user has already seen
        fresh_matches = []
        for ev in matches:
            title = ev.get("title", "")
            if not self._dedup.is_duplicate(user_id, title):
                fresh_matches.append(ev)

        if not fresh_matches:
            logger.debug("[EventMatcher] All matches already sent to %s, skipping", user_id)
            return

        # Format real event data for the LLM prompt
        events_text = ""
        for i, ev in enumerate(fresh_matches, 1):
            events_text += (
                f"\n{i}. {ev['title']}"
                f"\n   Ngày: {ev.get('event_date') or 'TBD'}"
                f"\n   Địa điểm: {ev.get('location') or 'Online'}"
                f"\n   Link: {ev.get('event_url') or 'N/A'}"
                f"\n   Tags: {ev.get('tags', '')}"
            )

        # Include active goals context if provided
        goals_context = ""
        active_goals = data.get("active_goals", [])
        if active_goals:
            goals_text = ", ".join(g.get("title", "") for g in active_goals if g.get("title"))
            if goals_text:
                goals_context = f"\nMục tiêu hiện tại của họ: {goals_text}\n"

        prompt = (
            f"Người dùng '{user_name}' đang quan tâm đến: {query}\n"
            f"{goals_context}"
            f"Các sự kiện Wildcats phù hợp nhất:\n{events_text}\n\n"
            "Hãy giới thiệu sự kiện phù hợp nhất một cách tự nhiên và hấp dẫn.\n"
            "CHỈ sử dụng thông tin sự kiện ở trên. KHÔNG bịa thêm sự kiện."
        )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)
            # Mark all surfaced events as sent for this user
            for ev in fresh_matches:
                self._dedup.mark_sent(user_id, ev.get("title", ""))

    def _semantic_match(self, query: str, n_results: int = 2) -> list[dict]:
        """Call the backend semantic event matching API."""
        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/events/match",
                json={"query": query, "n_results": n_results},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("matches", [])
        except Exception as e:
            logger.warning("[EventMatcher] Semantic match failed: %s", e)
        return []
