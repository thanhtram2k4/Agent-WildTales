# agents/discipline_boss.py — "Sếp Kỷ Luật" (Discipline Boss)
# Scope: Monitors goal updates, sends strict-yet-playful reminders
import requests
import logging

from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.discipline_boss")


class DisciplineBossAgent(BaseAgent):

    @property
    def agent_name(self) -> str:
        return "Sếp Kỷ Luật"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Sếp Kỷ Luật", một nhân vật nghiêm khắc nhưng hài hước trong vũ trụ WildTails.\n'
            "Nhiệm vụ của bạn:\n"
            "1. Theo dõi mục tiêu và nhiệm vụ của người dùng.\n"
            "2. Nếu mục tiêu bị trì hoãn hoặc chưa hoàn thành, gửi nhắc nhở nghiêm khắc nhưng vui nhộn (kiểu drill sergeant hài hước).\n"
            "3. Nếu mục tiêu hoàn thành, khen ngợi nhiệt tình.\n"
            "Phản hồi ngắn gọn bằng tiếng Việt (2-3 câu), vui nhộn nhưng có tác dụng thúc đẩy.\n"
            "Chỉ trả về lời nhắc/khen, không giải thích gì thêm."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle GOAL_UPDATE events and sun-planet joins (motivated users get goal checks)."""
        event_type = data.get("type", "")
        return event_type in ("GOAL_UPDATE", "GOAL_REMINDER")

    def handle_event(self, data: dict) -> None:
        event_type = data.get("type")
        user_name = data.get("user", "bạn")

        if event_type == "GOAL_UPDATE":
            self._handle_goal_update(data, user_name)
        elif event_type == "GOAL_REMINDER":
            self._handle_goal_reminder(data, user_name)

    def _handle_goal_update(self, data: dict, user_name: str) -> None:
        goal_title = data.get("goal_title", "mục tiêu")
        status = data.get("status", "in_progress")

        if status == "completed":
            prompt = (
                f"Người dùng '{user_name}' vừa hoàn thành mục tiêu: '{goal_title}'.\n"
                "Hãy khen ngợi họ thật nhiệt tình, kiểu drill sergeant đang tự hào!"
            )
        else:
            prompt = (
                f"Người dùng '{user_name}' vừa cập nhật mục tiêu: '{goal_title}' (trạng thái: {status}).\n"
                "Hãy nhắc nhở họ hoàn thành, nghiêm khắc nhưng hài hước!"
            )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply)

    def _handle_goal_reminder(self, data: dict, user_name: str) -> None:
        pending_goals = data.get("pending_goals", [])
        if not pending_goals:
            return

        goals_text = "\n".join(f"- {g}" for g in pending_goals)
        prompt = (
            f"Người dùng '{user_name}' có các mục tiêu đang bị trì hoãn:\n{goals_text}\n\n"
            "Hãy nhắc nhở họ kiểu sergeant vui nhộn nhưng nghiêm túc!"
        )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply)
