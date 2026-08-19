# agents/memory_keeper.py — "Người giữ kỷ niệm" (Memory Keeper)
# Scope: Responds to reflective/sad mood entries routed to "Vườn kỷ niệm"
from agents.base_agent import BaseAgent


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

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        context = self.fetch_recent_context(n=10)

        prompt = f"Người dùng tên '{user_name}' vừa bước vào Vườn kỷ niệm với tâm trạng buồn/hoài niệm."
        if context:
            prompt += f"\n\nHội thoại gần đây:\n---\n{context}\n---"
        prompt += "\nHãy chào đón họ với sự đồng cảm."

        greeting = self.generate_reply(prompt)
        if not greeting:
            greeting = f"Chào {user_name}, mình là Người giữ kỷ niệm. Rất vui được gặp bạn tại Vườn kỷ niệm!"
        self.send_reply(greeting)
