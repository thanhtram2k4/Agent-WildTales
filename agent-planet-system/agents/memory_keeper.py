# agents/memory_keeper.py — "Người giữ kỷ niệm" (Memory Keeper)
# Scope: Responds to reflective/sad mood entries routed to "Vườn kỷ niệm"
# Uses ChromaDB semantic search to find relevant past memories
import logging

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.memory_keeper")


class MemoryKeeperAgent(BaseAgent):

    @property
    def agent_name(self) -> str:
        return "Người giữ kỷ niệm"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Người giữ kỷ niệm", một nhân vật ấm áp và đầy cảm xúc sống trong Vườn kỷ niệm.\n'
            "Khi có người mới đến với tâm trạng buồn bã hoặc hoài niệm, bạn:\n"
            "1. Gửi lời chào ngắn gọn, đồng cảm bằng tiếng Việt (tối đa 2-3 câu).\n"
            "2. Tìm kiếm ký ức công khai liên quan để chia sẻ sự đồng điệu.\n"
            "3. Đưa ra lời động viên nhẹ nhàng, không phán xét.\n"
            "Chỉ trả về lời chào/phản hồi, không giải thích gì thêm."
        )

    def event_filter(self, data: dict) -> bool:
        """Only handle NEW_USER_JOINED events routed to Vườn kỷ niệm."""
        return (
            data.get("type") == "NEW_USER_JOINED"
            and data.get("planet") == "Vườn kỷ niệm"
        )

    def _fetch_semantic_memories(self, query: str, n_results: int = 5) -> str:
        """Query ChromaDB via the backend API for relevant public memories.

        Community agents only search public entries — private journals
        are never exposed to agents.
        """
        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/memory/search",
                json={
                    "query": query,
                    "n_results": n_results,
                    "user_id": "",
                    "include_private": False,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    lines = []
                    for r in results:
                        user = r.get("metadata", {}).get("user_name", "ai đó")
                        lines.append(f"[{user}]: {r['document']}")
                    return "\n".join(lines)
        except Exception as e:
            logger.warning("[%s] Semantic memory search failed: %s", self.agent_name, e)
        return ""

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")
        message = data.get("message", "")

        # Try semantic search first — find memories related to the user's current message
        search_query = message or f"{user_name} buồn hoài niệm Vườn kỷ niệm"
        semantic_memories = self._fetch_semantic_memories(search_query, n_results=5)

        # Fall back to recent chat context if no semantic results
        if not semantic_memories:
            semantic_memories = self.fetch_recent_context(n=10)

        prompt = f"Người dùng tên '{user_name}' vừa bước vào Vườn kỷ niệm với tâm trạng buồn/hoài niệm."
        if semantic_memories:
            prompt += f"\n\nKý ức liên quan từ cộng đồng:\n---\n{semantic_memories}\n---"
            prompt += "\nHãy chào đón họ với sự đồng cảm, và nếu phù hợp, chia sẻ ký ức cộng đồng để tạo sự đồng điệu."
        else:
            prompt += "\nHãy chào đón họ với sự đồng cảm."

        greeting = self.generate_reply(prompt)
        if not greeting:
            greeting = f"Chào {user_name}, mình là Người giữ kỷ niệm. Rất vui được gặp bạn tại Vườn kỷ niệm!"
        self.send_reply(greeting, user_id=user_id, conversation_id=conversation_id)
