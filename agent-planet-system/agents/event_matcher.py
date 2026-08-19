# agents/event_matcher.py — Wildcats Event Matcher Agent V2
# Scope: Semantic matching of user interests against embedded Wildcats events
# Returns ONLY real event data (title, URL, date) — never fabricates events
import logging

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

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
            "Format tên sự kiện rõ ràng, kèm ngày và link nếu có.\n"
            "QUAN TRỌNG: CHỈ giới thiệu sự kiện từ dữ liệu được cung cấp. KHÔNG bịa ra sự kiện."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle ONLY EVENT_MATCH_REQUEST events.

        Deterministic routing: this agent no longer responds to every
        NEW_USER_JOINED event (which caused spam). It only activates on
        explicit event match requests.
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

        # Format real event data for the LLM prompt
        events_text = ""
        for i, ev in enumerate(matches, 1):
            events_text += (
                f"\n{i}. {ev['title']}"
                f"\n   Ngày: {ev.get('event_date') or 'TBD'}"
                f"\n   Địa điểm: {ev.get('location') or 'Online'}"
                f"\n   Link: {ev.get('event_url') or 'N/A'}"
                f"\n   Tags: {ev.get('tags', '')}"
            )

        prompt = (
            f"Người dùng '{user_name}' đang quan tâm đến: {query}\n"
            f"Các sự kiện Wildcats phù hợp nhất:\n{events_text}\n\n"
            "Hãy giới thiệu sự kiện phù hợp nhất một cách tự nhiên và hấp dẫn.\n"
            "CHỈ sử dụng thông tin sự kiện ở trên. KHÔNG bịa thêm sự kiện."
        )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)

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
