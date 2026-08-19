# agents/event_matcher.py — Wildcats Event Matcher Agent
# Scope: Detects user interests from SSE events, recommends matching Wildcats events
import logging

from agents.base_agent import BaseAgent
from services.wildcats_events import event_cache

logger = logging.getLogger("wildtails.agents.event_matcher")


class EventMatcherAgent(BaseAgent):

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
            "Format tên sự kiện rõ ràng, kèm ngày và link nếu có."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle EVENT_MATCH_REQUEST and public NEW_USER_JOINED events."""
        event_type = data.get("type", "")
        return event_type in ("EVENT_MATCH_REQUEST", "NEW_USER_JOINED")

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        event_type = data.get("type")

        # Build interest query from event context
        if event_type == "EVENT_MATCH_REQUEST":
            query = data.get("query", "")
        else:
            # For NEW_USER_JOINED, derive interests from recent context
            context = self.fetch_recent_context(n=5)
            query = self._extract_interests(context, data)

        if not query:
            return

        # Search event cache (uses fixture in tests, live in production)
        matching_events = event_cache.get_events(use_fixture=False)
        if not matching_events:
            # Fallback to fixture if live fetch returns nothing
            matching_events = event_cache.get_events(use_fixture=True)

        results = event_cache.search(query, top_k=2)
        if not results:
            return

        # Format event recommendations
        events_text = ""
        for i, ev in enumerate(results, 1):
            events_text += (
                f"\n{i}. {ev.title}"
                f"\n   Ngày: {ev.event_date or 'TBD'}"
                f"\n   Địa điểm: {ev.location or 'Online'}"
                f"\n   Link: {ev.event_url or 'N/A'}"
                f"\n   Mô tả: {ev.description[:100]}"
            )

        prompt = (
            f"Người dùng '{user_name}' có vẻ quan tâm đến: {query}\n"
            f"Các sự kiện phù hợp từ Wildcats:\n{events_text}\n\n"
            "Hãy giới thiệu sự kiện phù hợp nhất một cách tự nhiên và hấp dẫn."
        )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply)

    def _extract_interests(self, context: str, data: dict) -> str:
        """Derive search keywords from chat context and event metadata."""
        planet = data.get("planet", "")
        message = data.get("message", "")

        keywords = []
        # Planet-based hints
        if planet == "Vườn kỷ niệm":
            keywords.extend(["wellness", "writing", "mindfulness"])
        elif planet == "Hành tinh mặt trời":
            keywords.extend(["gaming", "hackathon", "networking"])

        # Extract key nouns from recent context (simple heuristic)
        interest_signals = [
            "code", "coding", "lập trình", "AI", "game", "gaming",
            "viết", "writing", "sáng tạo", "creative",
            "startup", "kinh doanh", "business",
            "wellness", "sức khỏe", "mindfulness",
        ]
        combined_text = f"{context} {message}".lower()
        for signal in interest_signals:
            if signal.lower() in combined_text:
                keywords.append(signal)

        return " ".join(set(keywords)) if keywords else ""
