# agents/gamemaster.py — "Thuyền Viên Bão Thú" (Gamemaster)
# Scope: Responds to positive/playful mood entries, serves trivia/RPG challenges
import random

from agents.base_agent import BaseAgent


# Pre-defined trivia/riddles pool (expandable)
TRIVIA_POOL = [
    {
        "question": "Hành tinh nào trong hệ Mặt Trời có nhiều mặt trăng nhất?",
        "answer": "Sao Thổ (Saturn) với hơn 140 mặt trăng!",
        "reward": 5,
    },
    {
        "question": "Con vật nào có thể ngủ đứng?",
        "answer": "Ngựa! Chúng có cơ chế khóa chân khi đứng.",
        "reward": 3,
    },
    {
        "question": "Ngôn ngữ lập trình nào được đặt tên theo một loài rắn?",
        "answer": "Python! (dù thực ra đặt theo Monty Python)",
        "reward": 5,
    },
    {
        "question": "Đại dương nào lớn nhất Trái Đất?",
        "answer": "Thái Bình Dương (Pacific Ocean)!",
        "reward": 3,
    },
    {
        "question": "Ai là người đầu tiên đặt chân lên Mặt Trăng?",
        "answer": "Neil Armstrong vào năm 1969!",
        "reward": 5,
    },
]

RPG_SCENARIOS = [
    "Bạn đang đứng trước một cánh cổng bí ẩn giữa Vườn Kỷ Niệm. Trên cổng có dòng chữ: 'Chỉ ai nhớ được kỷ niệm đẹp nhất mới được đi qua.' Bạn sẽ chia sẻ kỷ niệm gì?",
    "Con mèo vũ trụ xuất hiện và tặng bạn 3 ngôi sao. Bạn có thể dùng chúng để: ⭐ Mở khóa một bí mật, ⭐⭐ Gọi một người bạn, ⭐⭐⭐ Du hành tới hành tinh mới. Bạn chọn gì?",
    "Bạn tìm thấy một cuốn nhật ký cũ trôi dạt trong không gian. Trang đầu tiên viết: 'Ngày mai sẽ tốt đẹp hơn nếu...' Bạn sẽ hoàn thành câu này như thế nào?",
]


class GamemasterAgent(BaseAgent):

    @property
    def agent_name(self) -> str:
        return "Thuyền Viên Bão Thú"

    @property
    def system_prompt(self) -> str:
        return (
            'Bạn là "Thuyền Viên Bão Thú" (Gamemaster), nhân vật vui nhộn và sáng tạo trong vũ trụ WildTails.\n'
            "Nhiệm vụ của bạn:\n"
            "1. Tổ chức các thử thách RPG mini, câu đố, hoặc trivia trong chat.\n"
            "2. Trao token thưởng cho người chơi hoàn thành thử thách.\n"
            "3. Giữ không khí vui vẻ, hào hứng.\n"
            "Phản hồi bằng tiếng Việt, ngắn gọn (3-4 câu), đầy năng lượng.\n"
            "Nếu đưa ra câu đố, format rõ ràng để người chơi dễ trả lời."
        )

    def event_filter(self, data: dict) -> bool:
        """Handle sun-planet joins (playful/positive mood) and GAME_REQUEST events."""
        event_type = data.get("type", "")
        if event_type == "GAME_REQUEST":
            return True
        # Positive mood users landing on Hành tinh mặt trời
        if event_type == "NEW_USER_JOINED" and data.get("planet") == "Hành tinh mặt trời":
            return True
        return False

    def handle_event(self, data: dict) -> None:
        user_name = data.get("user", "bạn")
        event_type = data.get("type")

        if event_type == "GAME_REQUEST":
            game_type = data.get("game_type", "trivia")
            if game_type == "rpg":
                self._serve_rpg(user_name)
            else:
                self._serve_trivia(user_name)
        else:
            # Welcome with a mini challenge
            self._welcome_with_challenge(user_name)

    def _serve_trivia(self, user_name: str) -> None:
        trivia = random.choice(TRIVIA_POOL)
        prompt = (
            f"Người chơi '{user_name}' muốn chơi trivia.\n"
            f"Câu hỏi: {trivia['question']}\n"
            f"Đáp án (để bạn biết): {trivia['answer']}\n"
            f"Phần thưởng: {trivia['reward']} token\n\n"
            "Hãy đưa ra câu hỏi này một cách vui nhộn và hấp dẫn. "
            "ĐỪNG tiết lộ đáp án. Nói họ trả lời trong chat."
        )
        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply)

    def _serve_rpg(self, user_name: str) -> None:
        scenario = random.choice(RPG_SCENARIOS)
        prompt = (
            f"Người chơi '{user_name}' muốn chơi RPG mini.\n"
            f"Kịch bản: {scenario}\n\n"
            "Hãy dẫn dắt kịch bản này một cách sống động và mời họ tham gia."
        )
        reply = self.generate_reply(prompt)
        if reply:
            self.send_reply(reply)

    def _welcome_with_challenge(self, user_name: str) -> None:
        # 50/50 trivia or RPG
        if random.random() < 0.5:
            trivia = random.choice(TRIVIA_POOL)
            prompt = (
                f"Người dùng '{user_name}' vừa đến Hành tinh Mặt Trời với tâm trạng vui vẻ!\n"
                "Hãy chào đón họ và đưa ra một câu đố vui: "
                f"'{trivia['question']}'\n"
                "ĐỪNG tiết lộ đáp án. Mời họ thử trả lời."
            )
        else:
            scenario = random.choice(RPG_SCENARIOS)
            prompt = (
                f"Người dùng '{user_name}' vừa đến Hành tinh Mặt Trời!\n"
                f"Hãy chào đón họ bằng kịch bản RPG mini này: {scenario}"
            )
        reply = self.generate_reply(prompt)
        if not reply:
            reply = f"Chào {user_name}! Chào mừng đến Hành tinh Mặt Trời! Sẵn sàng cho một thử thách vui không? 🎮"
        self.send_reply(reply)
