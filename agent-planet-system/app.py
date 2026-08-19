# app.py
import asyncio
import json
import sqlite3
import os
import uuid
import logging
from contextlib import contextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import chromadb

load_dotenv()

logger = logging.getLogger("wildtails")

app = FastAPI(title="WildTails Multi-Agent Hub")

# --- Environment config ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

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
    """Tạo bảng messages và token_transactions nếu chưa tồn tại."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('private', 'public')),
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add visibility column to existing tables (safe migration)
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('private', 'public'))")
        except sqlite3.OperationalError:
            pass  # Column already exists

        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reference_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress', 'completed', 'abandoned')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


@app.on_event("startup")
async def startup():
    init_db()
    init_chromadb()

# Ollama OpenAI-compatible client
ollama_client = AsyncOpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
)

# --- ChromaDB persistent vector store ---
CHROMA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
chroma_client = None
journal_collection = None


def init_chromadb():
    """Initialize persistent ChromaDB store with journal_embeddings collection."""
    global chroma_client, journal_collection
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        journal_collection = chroma_client.get_or_create_collection(
            name="journal_embeddings",
            metadata={"description": "User journal entry embeddings for semantic search"},
        )
        logger.info("ChromaDB initialized at %s", CHROMA_DB_PATH)
    except Exception as e:
        logger.warning("ChromaDB initialization failed (non-fatal): %s", e)


async def embed_text(text: str) -> list[float] | None:
    """Generate embedding for text using local Ollama nomic-embed-text model."""
    try:
        response = await ollama_client.embeddings.create(
            model=OLLAMA_EMBED_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning("Embedding generation failed (non-fatal): %s", e)
        return None

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
    visibility: str = "public"  # "public" (Planet Feed) or "private" (Captain's Cabin)


class KnowledgeIngestRequest(BaseModel):
    url: str
    user_id: str
    user_name: str = "anonymous"


class GoalCreate(BaseModel):
    user_id: str
    user_name: str
    title: str


class GoalUpdate(BaseModel):
    status: str  # "completed" or "abandoned"

# 1. Phân tích cảm xúc & Đề xuất Planet (LLM-powered via Ollama)
async def mood_and_planet_recommender(text: str) -> dict:
    fallback = {
        "mood": "Trầm lắng / Cần kết nối",
        "planet": "Vườn kỷ niệm",
        "action": "connect_others",
    }
    try:
        response = await ollama_client.chat.completions.create(
            model=OLLAMA_CHAT_MODEL,
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

    # Validate and normalize visibility
    vis = payload.visibility if payload.visibility in ("public", "private") else "public"

    # Lưu cả tin nhắn user và phản hồi System Agent vào DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (sender_name, role, content, visibility) VALUES (?, ?, ?, ?)",
            (payload.user_name, "user", payload.message, vis),
        )
        conn.execute(
            "INSERT INTO messages (sender_name, role, content, visibility) VALUES (?, ?, ?, ?)",
            ("System Agent", "assistant", agent_reply, vis),
        )

    # Embed journal entry into ChromaDB (non-blocking, failure-safe)
    try:
        if journal_collection is not None:
            embedding = await embed_text(payload.message)
            if embedding is not None:
                doc_id = str(uuid.uuid4())
                journal_collection.add(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[payload.message],
                    metadatas=[{
                        "user_id": payload.user_id,
                        "user_name": payload.user_name,
                        "mood": analysis["mood"],
                        "planet": analysis["planet"],
                        "visibility": vis,
                    }],
                )
    except Exception as e:
        logger.warning("ChromaDB embedding storage failed (non-fatal): %s", e)

    response_data = {
        "user_name": payload.user_name,
        "mood": analysis["mood"],
        "assigned_planet": analysis["planet"],
        "agent_reply": agent_reply,
        "visibility": vis,
    }

    # Private entries (Captain's Cabin) MUST NOT trigger SSE broadcast
    # Only public entries go to the Planet Feed event bridge
    if vis == "public":
        event_payload = {
            "type": "NEW_USER_JOINED",
            "planet": analysis["planet"],
            "user": payload.user_name,
            "message": f"Agent của {payload.user_name} vừa tham gia {analysis['planet']}.",
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
async def get_messages(scope: str = "public"):
    """Return message history.

    scope:
      - "public"  (default) — only public Planet Feed messages.
      - "owner:<user_id>" — public + private messages belonging to that user.
      - "system"  — all messages (for internal/admin use).
    """
    with get_db() as conn:
        if scope == "system":
            rows = conn.execute(
                "SELECT sender_name, role, content, visibility, timestamp FROM messages ORDER BY id"
            ).fetchall()
        elif scope.startswith("owner:"):
            owner_name = scope.split(":", 1)[1]
            rows = conn.execute(
                "SELECT sender_name, role, content, visibility, timestamp FROM messages "
                "WHERE visibility = 'public' OR sender_name = ? ORDER BY id",
                (owner_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sender_name, role, content, visibility, timestamp FROM messages "
                "WHERE visibility = 'public' ORDER BY id"
            ).fetchall()
    return {
        "messages": [
            {
                "role": r["role"],
                "sender": r["sender_name"],
                "content": r["content"],
                "visibility": r["visibility"],
            }
            for r in rows
        ]
    }

# 6. Knowledge Ingestion API (Phase D - Local RAG)
@app.post("/api/knowledge/ingest")
async def ingest_knowledge(payload: KnowledgeIngestRequest):
    """Fetch a public URL, extract text, chunk it, embed & store in ChromaDB."""
    from mcp_tools import fetch_and_extract, chunk_text

    if journal_collection is None:
        return {"status": "error", "detail": "ChromaDB not initialized"}

    # Extract text from URL
    extracted = fetch_and_extract(payload.url)
    if extracted is None:
        return {"status": "error", "detail": "Failed to extract content from URL"}

    title = extracted["title"]
    text = extracted["text"]
    source_type = extracted["source_type"]

    if not text or len(text.strip()) < 20:
        return {"status": "error", "detail": "Extracted content too short or empty"}

    # Chunk and embed
    chunks = chunk_text(text)
    stored_count = 0
    for i, chunk in enumerate(chunks):
        try:
            embedding = await embed_text(chunk)
            if embedding is not None:
                doc_id = str(uuid.uuid4())
                journal_collection.add(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[chunk],
                    metadatas=[{
                        "user_id": payload.user_id,
                        "user_name": payload.user_name,
                        "source_url": payload.url,
                        "source_type": source_type,
                        "title": title,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "visibility": "public",
                    }],
                )
                stored_count += 1
        except Exception as e:
            logger.warning("Failed to embed chunk %d: %s", i, e)

    return {
        "status": "success",
        "title": title,
        "source_type": source_type,
        "total_chunks": len(chunks),
        "stored_chunks": stored_count,
    }


# 7. Goals API (Phase F - Discipline Boss support)
@app.post("/api/goals")
async def create_goal(payload: GoalCreate):
    """Create a new goal and broadcast GOAL_UPDATE event."""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO goals (user_id, user_name, title) VALUES (?, ?, ?)",
            (payload.user_id, payload.user_name, payload.title),
        )
        goal_id = cursor.lastrowid

    # Broadcast to Discipline Boss agent
    event_payload = {
        "type": "GOAL_UPDATE",
        "user": payload.user_name,
        "goal_id": goal_id,
        "goal_title": payload.title,
        "status": "in_progress",
    }
    for queue in subscribers:
        await queue.put(json.dumps(event_payload))

    return {"status": "success", "goal_id": goal_id}


@app.put("/api/goals/{goal_id}")
async def update_goal(goal_id: int, payload: GoalUpdate):
    """Update goal status and broadcast event."""
    if payload.status not in ("completed", "abandoned"):
        return {"status": "error", "detail": "Invalid status"}

    with get_db() as conn:
        row = conn.execute("SELECT user_name, title FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return {"status": "error", "detail": "Goal not found"}
        conn.execute(
            "UPDATE goals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (payload.status, goal_id),
        )

    event_payload = {
        "type": "GOAL_UPDATE",
        "user": row["user_name"],
        "goal_id": goal_id,
        "goal_title": row["title"],
        "status": payload.status,
    }
    for queue in subscribers:
        await queue.put(json.dumps(event_payload))

    return {"status": "success"}


@app.get("/api/goals/{user_id}")
async def get_user_goals(user_id: str):
    """List all goals for a user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, status, created_at, updated_at FROM goals WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return {
        "goals": [
            {"id": r["id"], "title": r["title"], "status": r["status"],
             "created_at": r["created_at"], "updated_at": r["updated_at"]}
            for r in rows
        ]
    }


@app.post("/api/goals/{user_id}/remind")
async def remind_goals(user_id: str):
    """Trigger a GOAL_REMINDER SSE event for all pending goals of a user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, user_name FROM goals WHERE user_id = ? AND status = 'in_progress'",
            (user_id,),
        ).fetchall()

    if not rows:
        return {"status": "no_pending_goals"}

    user_name = rows[0]["user_name"]
    pending = [r["title"] for r in rows]

    event_payload = {
        "type": "GOAL_REMINDER",
        "user": user_name,
        "pending_goals": pending,
    }
    for queue in subscribers:
        await queue.put(json.dumps(event_payload))

    return {"status": "reminder_sent", "pending_count": len(pending)}


# 8. Token Balance API (Phase G - Gamification)
@app.get("/api/tokens/{user_id}")
async def get_token_balance(user_id: str):
    """Return total Catalyst Points for a user."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as balance FROM token_transactions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return {"user_id": user_id, "balance": row["balance"]}


# 9. Wildcats Events API (Phase E)
@app.get("/api/events")
async def get_events():
    """Return cached Wildcats events."""
    from services.wildcats_events import event_cache
    events = event_cache.get_events()
    if not events:
        events = event_cache.get_events(use_fixture=True)
    return {"events": [e.to_dict() for e in events]}


@app.post("/api/events/refresh")
async def refresh_events():
    """Force-refresh events from wildcats.io."""
    from services.wildcats_events import event_cache
    events = event_cache.refresh(use_fixture=False)
    return {"status": "refreshed", "count": len(events)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)