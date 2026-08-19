# app.py
import asyncio
import json
import sqlite3
import os
from contextlib import contextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from openai import AsyncOpenAI

app = FastAPI(title="WildTails Multi-Agent Hub")

# --- SQLite persistent memory ---
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wildtails_memory.db")


@contextmanager
def get_db():
    """Context manager for safe SQLite connections."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Tạo bảng messages nếu chưa tồn tại."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


@app.on_event("startup")
async def startup():
    init_db()

# Ollama OpenAI-compatible client
ollama_client = AsyncOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

MOOD_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích tâm lý. Nhiệm vụ của bạn là đọc nhật ký của người dùng (viết bằng tiếng Việt), phân tích trạng thái cảm xúc, và phân loại họ vào một trong hai hành tinh.

Quy tắc phân loại:
- Nếu cảm xúc là tích cực, vui vẻ, năng động, hào hứng, hoặc muốn vui chơi → planet = "Hành tinh mặt trời", action = "stay"
- Nếu cảm xúc là cô đơn, hoài niệm, buồn bã, nhớ nhung, hoặc cần kết nối → planet = "Vườn kỷ niệm", action = "connect_others"

Bạn PHẢI trả về DUY NHẤT một JSON object hợp lệ, KHÔNG có markdown, KHÔNG có giải thích, KHÔNG có text nào khác ngoài JSON.

Format bắt buộc:
{"mood": "<mô tả ngắn cảm xúc bằng tiếng Việt>", "planet": "<Hành tinh mặt trời hoặc Vườn kỷ niệm>", "action": "<stay hoặc connect_others>"}"""

@app.get("/")
async def home():
    return {"message": "Chào mừng đến với WildTails Multi-Agent Hub! Server đang hoạt động tốt."}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lưu danh sách Event Queue cho SSE
subscribers = []

class UserMessage(BaseModel):
    user_id: str
    user_name: str
    message: str

# 1. Phân tích cảm xúc & Đề xuất Planet (LLM-powered via Ollama)
async def mood_and_planet_recommender(text: str) -> dict:
    fallback = {
        "mood": "Trầm lắng / Cần kết nối",
        "planet": "Vườn kỷ niệm",
        "action": "connect_others",
    }
    try:
        response = await ollama_client.chat.completions.create(
            model="llama3",
            messages=[
                {"role": "system", "content": MOOD_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Validate required keys and allowed values
        if result.get("planet") not in ("Hành tinh mặt trời", "Vườn kỷ niệm"):
            return fallback
        if result.get("action") not in ("stay", "connect_others"):
            return fallback
        if not result.get("mood"):
            return fallback

        return {
            "mood": result["mood"],
            "planet": result["planet"],
            "action": result["action"],
        }
    except Exception:
        return fallback

# 2. API nhận chat từ User
@app.post("/api/chat")
async def chat_interaction(payload: UserMessage):
    # Phân tích qua MoodTracker
    analysis = await mood_and_planet_recommender(payload.message)

    agent_reply = (
        f"Chào {payload.user_name}, hệ thống nhận thấy cảm xúc của bạn là "
        f"'{analysis['mood']}'. Bạn đã được đưa tới [{analysis['planet']}]."
    )

    # Lưu cả tin nhắn user và phản hồi System Agent vào DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (sender_name, role, content) VALUES (?, ?, ?)",
            (payload.user_name, "user", payload.message),
        )
        conn.execute(
            "INSERT INTO messages (sender_name, role, content) VALUES (?, ?, ?)",
            ("System Agent", "assistant", agent_reply),
        )

    response_data = {
        "user_name": payload.user_name,
        "mood": analysis["mood"],
        "assigned_planet": analysis["planet"],
        "agent_reply": agent_reply,
    }

    # Nếu vào Vườn kỷ niệm -> Phát tín hiệu SSE để kết nối Agent khác
    if analysis["action"] == "connect_others":
        event_payload = {
            "type": "NEW_USER_JOINED",
            "planet": "Vườn kỷ niệm",
            "user": payload.user_name,
            "message": f"Agent của {payload.user_name} vừa tham gia. Sẵn sàng kết bạn!",
        }
        for queue in subscribers:
            await queue.put(json.dumps(event_payload))

    return response_data

# 3. SSE Server Endpoint để các Agent của người khác lắng nghe
@app.get("/api/sse/events")
async def sse_events(request: Request):
    queue = asyncio.Queue()
    subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield {"event": "agent_message", "data": data}
        finally:
            subscribers.remove(queue)

    return EventSourceResponse(event_generator())

# 4. API để External Agent gửi tin nhắn vào hội thoại chung
class ExternalAgentReply(BaseModel):
    agent_name: str
    message: str

@app.post("/api/external_agent_reply")
async def receive_external_agent_reply(payload: ExternalAgentReply):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (sender_name, role, content) VALUES (?, ?, ?)",
            (payload.agent_name, "assistant", payload.message),
        )
    return {"status": "success"}

# 5. API trả về toàn bộ lịch sử hội thoại
@app.get("/api/messages")
async def get_messages():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sender_name, role, content, timestamp FROM messages ORDER BY id"
        ).fetchall()
    return {
        "messages": [
            {"role": r["role"], "sender": r["sender_name"], "content": r["content"]}
            for r in rows
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)