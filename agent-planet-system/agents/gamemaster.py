# agents/gamemaster.py — "Thuyền Viên Bão Thú" (Gamemaster)
# Scope: Responds to positive/playful mood entries, serves trivia via backend game API
import logging

import requests
from agents.base_agent import BaseAgent, BACKEND_URL

logger = logging.getLogger("wildtails.agents.gamemaster")


class GamemasterAgent(BaseAgent):

    @property
    def agent_name(self) -> str:
        return "Thuyền Viên Bão Thú"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Thuyền Viên Bão Thú" (Gamemaster), nhân vật vui nhộn và sáng tạo trong vũ trụ WildTails.\n'
            "Nhiệm vụ của bạn:\n"
            "1. Tổ chức các thử thách trivia trong chat.\n"
            "2. Đưa ra câu đố rõ ràng, hấp dẫn.\n"
            "3. Giữ không khí vui vẻ, hào hứng.\n"
            "Phản hồi bằng tiếng Việt, ngắn gọn (3-4 câu), đầy năng lượng.\n"
            "Format rõ ràng: nêu câu hỏi, phần thưởng, và mời người chơi trả lời."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle ONLY sun-planet joins and GAME_REQUEST events.

        Deterministic routing: this agent does NOT respond to
        GOAL_UPDATE, GOAL_REMINDER, or EVENT_MATCH_REQUEST events.
        """
        event_type = data.get("type", "")
        if event_type == "GAME_REQUEST":
            return True
        if event_type == "NEW_USER_JOINED" and data.get("planet") == "Hành tinh mặt trời":
            return True
        return False

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        user_id = data.get("user_id", "")
        conversation_id = data.get("conversation_id", "")

        # Start a trivia game via the backend API
        self._start_trivia_game(user_name, user_id, conversation_id)

    def _start_trivia_game(self, user_name: str, user_id: str, conversation_id: str) -> None:
        """Start a trivia game room via backend and present the question."""
        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/game/start",
                json={"user_id": user_id, "user_name": user_name, "game_type": "trivia"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("[Gamemaster] Failed to start game: %s", resp.status_code)
                return

            game_data = resp.json()
            question = game_data.get("question", "")
            reward = game_data.get("reward", 5)
            room_id = game_data.get("room_id", "?")

            prompt = (
                f"Người dùng '{user_name}' vừa đến Hành tinh Mặt Trời!\n"
                f"Hãy chào đón họ và đưa ra câu đố trivia sau:\n"
                f"Câu hỏi: {question}\n"
                f"Phần thưởng: {reward} Catalyst Points\n"
                f"Room ID: #{room_id}\n\n"
                "ĐỪNG tiết lộ đáp án. Nói họ trả lời bằng cách nhắn đáp án trong chat.\n"
                "Nhắc họ Room ID để hệ thống kiểm tra."
            )

            reply = self.generate_reply(prompt)
            if not reply:
                reply = (
                    f"Chào {user_name}! 🎮 Chào mừng đến Hành tinh Mặt Trời!\n\n"
                    f"Câu đố (Room #{room_id}): {question}\n"
                    f"Phần thưởng: {reward} ⚡ Catalyst Points\n\n"
                    "Nhắn đáp án của bạn trong chat nhé!"
                )
            self.send_reply(reply, user_id=user_id, conversation_id=conversation_id)

        except requests.exceptions.ConnectionError:
            logger.warning("[Gamemaster] Cannot connect to backend to start game")
        except Exception as e:
            logger.warning("[Gamemaster] Error starting game: %s", e)
