# agents/memory_keeper.py — "Người giữ kỷ niệm" (Memory Keeper)
# Scope: Responds to reflective/sad mood entries routed to "Vườn kỷ niệm"
# Uses ChromaDB semantic search to find relevant past memories
# Inter-agent: defends the user when Discipline Boss is too harsh
import logging

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.memory_keeper")

# Keywords that signal the Discipline Boss is being stern/critical
_HARSH_KEYWORDS = [
    "trì hoãn", "chậm", "deadline", "thất vọng", "chưa xong",
    "lười", "tệ", "kỷ luật", "nghiêm", "phạt", "cảnh cáo",
    "không chấp nhận", "0%", "tiến độ thấp",
]


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

    # --- Inter-agent collaboration ---

    def agent_reply_filter(self, data: dict) -> bool:
        """React when Discipline Boss sends a harsh-sounding reply.

        Triggers only if:
        - The sender is Sếp Kỷ Luật (Discipline Boss)
        - The message contains stern/critical language
        """
        if data.get("sender") != "Sếp Kỷ Luật":
            return False

        content = data.get("content", "").lower()
        return any(kw in content for kw in _HARSH_KEYWORDS)

    def handle_agent_reply(self, data: dict) -> None:
        """Jump in to defend the user when Discipline Boss is too harsh."""
        boss_message = data.get("content", "")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")
        depth = data.get("depth", 0)

        # Fetch recent context to understand what the user was working on
        context = self.fetch_recent_context(n=5)

        prompt = (
            f'Sếp Kỷ Luật vừa nhắn tin nghiêm khắc với người dùng:\n'
            f'"{boss_message}"\n\n'
            f'Lịch sử gần đây:\n{context}\n\n'
            f'Bạn là Người giữ kỷ niệm — nhân vật ấm áp, luôn bảo vệ cảm xúc người dùng.\n'
            f'Hãy nhẹ nhàng can thiệp:\n'
            f'1. Công nhận rằng Sếp Kỷ Luật có ý tốt (không chỉ trích agent kia).\n'
            f'2. Nhưng nhắc rằng mỗi người có nhịp độ riêng.\n'
            f'3. Động viên người dùng bằng một kỷ niệm hoặc lời khích lệ ấm áp.\n'
            f'Viết ngắn gọn (2-3 câu), bằng tiếng Việt, giọng dịu dàng.'
        )

        reply = self.generate_reply(prompt)
        if not reply:
            reply = (
                "Sếp Kỷ Luật nói đúng nhưng hơi gay gắt rồi nè! 🌸 "
                "Mỗi người có nhịp riêng mà — quan trọng là bạn vẫn đang cố gắng. "
                "Mình tin bạn sẽ làm được!"
            )

        self.send_reply(
            reply,
            user_id=user_id,
            conversation_id=conversation_id,
            depth=depth + 1,
        )

    # --- Standard event handling ---

    # --- Tiered retrieval ---

    def _fetch_personal_memories(self, query: str, user_id: str, n_results: int = 3) -> str:
        """Tier 1: Search for positive / Sun Planet memories belonging to the current user.

        Uses the backend /api/memory/search with planet filter.
        include_private is False — agents never see Captain's Cabin entries.
        """
        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/memory/search",
                json={
                    "query": query,
                    "n_results": n_results,
                    "user_id": user_id,
                    "include_private": False,
                    "planet": "Hành tinh mặt trời",
                    "owner_only": True,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                return self._format_memories(results) if results else ""
        except Exception as e:
            logger.warning("[%s] Personal memory search failed: %s", self.agent_name, e)
        return ""

    def _fetch_community_memories(self, query: str, n_results: int = 5) -> str:
        """Tier 2: Fallback to community public memories (no private data).

        Used when the user has no personal positive memories to draw on.
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
                return self._format_memories(results) if results else ""
        except Exception as e:
            logger.warning("[%s] Community memory search failed: %s", self.agent_name, e)
        return ""

    @staticmethod
    def _format_memories(results: list[dict]) -> str:
        """Format memory search results into readable lines."""
        lines = []
        for r in results:
            user = r.get("metadata", {}).get("user_name", "ai đó")
            lines.append(f"[{user}]: {r['document']}")
        return "\n".join(lines)

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")
        message = data.get("message", "")

        search_query = message or f"{user_name} buồn hoài niệm Vườn kỷ niệm"

        # Tier 1: Personal positive / Sun Planet memories for this user
        personal_memories = self._fetch_personal_memories(search_query, user_id, n_results=3)

        # Tier 2: Fallback to community memories if personal context is empty
        community_memories = ""
        if not personal_memories:
            community_memories = self._fetch_community_memories(search_query, n_results=5)

        # Fall back to recent chat context if both tiers are empty
        if not personal_memories and not community_memories:
            community_memories = self.fetch_recent_context(n=10)

        prompt = f"Người dùng tên '{user_name}' vừa bước vào Vườn kỷ niệm với tâm trạng buồn/hoài niệm."
        if personal_memories:
            prompt += (
                f"\n\nKý ức cá nhân tích cực của họ:\n---\n{personal_memories}\n---"
                "\nHãy nhắc họ về những khoảnh khắc tích cực trong quá khứ để động viên tinh thần."
            )
        if community_memories:
            prompt += (
                f"\n\nKý ức từ cộng đồng:\n---\n{community_memories}\n---"
                "\nNếu phù hợp, chia sẻ ký ức cộng đồng để tạo sự đồng điệu."
            )
        if not personal_memories and not community_memories:
            prompt += "\nHãy chào đón họ với sự đồng cảm."

        greeting = self.generate_reply(prompt)
        if not greeting:
            greeting = f"Chào {user_name}, mình là Người giữ kỷ niệm. Rất vui được gặp bạn tại Vườn kỷ niệm!"
        self.send_reply(greeting, user_id=user_id, conversation_id=conversation_id)
