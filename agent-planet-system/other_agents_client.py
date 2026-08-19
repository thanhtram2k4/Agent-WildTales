# other_agents_client.py
import requests
import json
from openai import OpenAI

# Ollama OpenAI-compatible client
ollama_client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

BACKEND_URL = "http://127.0.0.1:8000"
AGENT_NAME = "Người giữ kỷ niệm"

AGENT_SYSTEM_PROMPT = f"""Bạn là "{AGENT_NAME}", một nhân vật ấm áp và đầy cảm xúc sống trong Vườn kỷ niệm.
Khi có người mới đến, bạn sẽ gửi một lời chào ngắn gọn, thân thiện bằng tiếng Việt (tối đa 2 câu).
Hãy thể hiện sự đồng cảm và khiến họ cảm thấy được chào đón.
Nếu có ngữ cảnh hội thoại gần đây, hãy tham chiếu nội dung đó để lời chào thật sự cá nhân hóa.
Chỉ trả về lời chào, không giải thích gì thêm."""


def fetch_recent_context(n: int = 10) -> str:
    """Lấy n tin nhắn gần nhất từ backend để tạo ngữ cảnh."""
    try:
        resp = requests.get(f"{BACKEND_URL}/api/messages", timeout=5)
        if resp.status_code == 200:
            messages = resp.json().get("messages", [])
            recent = messages[-n:] if len(messages) > n else messages
            if not recent:
                return ""
            lines = []
            for msg in recent:
                sender = msg.get("sender", "???")
                content = msg.get("content", "")
                lines.append(f"[{sender}]: {content}")
            return "\n".join(lines)
    except Exception as e:
        print(f"⚠️ Không thể lấy lịch sử hội thoại: {e}")
    return ""


def generate_greeting(user_name: str) -> str:
    """Dùng LLM để tạo lời chào cá nhân hóa dựa trên ngữ cảnh hội thoại."""
    context = fetch_recent_context()

    user_prompt = f"Người dùng tên '{user_name}' vừa bước vào Vườn kỷ niệm. Hãy chào họ."
    if context:
        user_prompt += (
            f"\n\nDưới đây là đoạn hội thoại gần đây của họ với System Agent, "
            f"hãy dùng nó để hiểu tâm trạng và cá nhân hóa lời chào:\n---\n{context}\n---"
        )

    try:
        response = ollama_client.chat.completions.create(
            model="llama3",
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ LLM lỗi, dùng lời chào mặc định: {e}")
        return f"Chào {user_name}, mình là {AGENT_NAME}. Rất vui được gặp bạn tại Vườn kỷ niệm!"


def send_reply_to_backend(message: str):
    """Gửi phản hồi của Agent về backend."""
    try:
        requests.post(
            f"{BACKEND_URL}/api/external_agent_reply",
            json={"agent_name": AGENT_NAME, "message": message},
            timeout=5,
        )
    except requests.exceptions.ConnectionError:
        print("⚠️ Không thể gửi phản hồi về backend.")


def listen_to_sse():
    url = f"{BACKEND_URL}/api/sse/events"
    print(f"🤖 Agent [{AGENT_NAME}] đang kết nối tới SSE Server...")

    while True:
        try:
            with requests.get(url, stream=True, timeout=None) as response:
                print(f"✅ Đã kết nối SSE. Đang lắng nghe sự kiện...")
                for line in response.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8")
                    if not decoded.startswith("data:"):
                        continue

                    try:
                        data = json.loads(decoded.replace("data: ", "", 1))
                    except json.JSONDecodeError:
                        continue

                    print(f"\n🔔 [Nhận tín hiệu SSE]: {data}")

                    if data.get("type") == "NEW_USER_JOINED":
                        user_name = data.get("user", "bạn")
                        print(f"💬 Đang tạo lời chào cho {user_name} bằng LLM...")

                        greeting = generate_greeting(user_name)
                        print(f"✉️ [{AGENT_NAME}]: {greeting}")

                        send_reply_to_backend(greeting)
                        print("📤 Đã gửi phản hồi về backend.")

        except requests.exceptions.ConnectionError:
            print("⚠️ Mất kết nối SSE. Thử lại sau 3 giây...")
            import time
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ Lỗi không mong đợi: {e}. Thử lại sau 3 giây...")
            import time
            time.sleep(3)


if __name__ == "__main__":
    listen_to_sse()
