# agents/discipline_boss.py — "Sếp Kỷ Luật" (Discipline Boss)
# Scope: Monitors goal updates (progress, deadline, status), sends strict-yet-playful reminders
import logging

from agents.base_agent import BaseAgent

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
            "1. Theo dõi mục tiêu, tiến độ (progress %), và deadline của người dùng.\n"
            "2. Nếu mục tiêu bị trì hoãn, tiến độ thấp, hoặc gần deadline, gửi nhắc nhở nghiêm khắc nhưng vui nhộn.\n"
            "3. Nếu mục tiêu hoàn thành (100%), khen ngợi nhiệt tình.\n"
            "4. Nếu có deadline, nhắc nhở về thời hạn.\n"
            "Phản hồi ngắn gọn bằng tiếng Việt (2-3 câu), vui nhộn nhưng có tác dụng thúc đẩy.\n"
            "Chỉ trả về lời nhắc/khen, không giải thích gì thêm."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle ONLY GOAL_UPDATE and GOAL_REMINDER events.

        Deterministic routing: this agent does NOT respond to
        NEW_USER_JOINED, GAME_REQUEST, or EVENT_MATCH_REQUEST events.
        """
        return data.get("type") in ("GOAL_UPDATE", "GOAL_REMINDER")

    def handle_event(self, data: dict) -> None:
        event_type = data.get("type")
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")

        if event_type == "GOAL_UPDATE":
            self._handle_goal_update(data, user_name, user_id, conversation_id)
        elif event_type == "GOAL_REMINDER":
            self._handle_goal_reminder(data, user_name, user_id, conversation_id)

    def _handle_goal_update(self, data: dict, user_name: str, user_id: str, conversation_id: str) -> None:
        goal_title = data.get("goal_title", "mục tiêu")
        status = data.get("status", "in_progress")
        progress = data.get("progress", 0)
        target_date = data.get("target_date", "")

        if status == "completed":
            prompt = (
                f"Người dùng '{user_name}' vừa hoàn thành mục tiêu: '{goal_title}' (100%).\n"
                "Hãy khen ngợi họ thật nhiệt tình, kiểu drill sergeant đang tự hào!"
            )
        elif progress > 0:
            deadline_note = f" Deadline: {target_date}." if target_date else ""
            prompt = (
                f"Người dùng '{user_name}' cập nhật mục tiêu: '{goal_title}' — tiến độ {progress}%.{deadline_note}\n"
            )
            if progress < 50:
                prompt += "Tiến độ còn thấp! Nhắc nhở họ tăng tốc, nghiêm khắc nhưng hài hước!"
            else:
                prompt += "Đã qua nửa đường! Động viên họ hoàn thành nốt!"
        else:
            prompt = (
                f"Người dùng '{user_name}' vừa tạo/cập nhật mục tiêu: '{goal_title}' (trạng thái: {status}).\n"
                "Hãy nhắc nhở họ bắt đầu, nghiêm khắc nhưng hài hước!"
            )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)

    def _handle_goal_reminder(self, data: dict, user_name: str, user_id: str, conversation_id: str) -> None:
        pending_goals = data.get("pending_goals", [])
        if not pending_goals:
            return

        # pending_goals can be list of strings (legacy) or list of dicts (new)
        goals_lines = []
        for g in pending_goals:
            if isinstance(g, dict):
                line = f"- {g['title']} (tiến độ: {g.get('progress', 0)}%"
                if g.get("target_date"):
                    line += f", deadline: {g['target_date']}"
                line += ")"
                goals_lines.append(line)
            else:
                goals_lines.append(f"- {g}")

        goals_text = "\n".join(goals_lines)
        prompt = (
            f"Người dùng '{user_name}' có các mục tiêu đang bị trì hoãn:\n{goals_text}\n\n"
            "Hãy nhắc nhở họ kiểu sergeant vui nhộn nhưng nghiêm túc! "
            "Nếu có deadline gần, nhấn mạnh thời hạn."
        )

        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)
