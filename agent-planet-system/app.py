# app.py
import asyncio
import json
import re
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
from services.vector_memory import VectorMemory
from services.token_service import TokenService
from services.event_bridge import event_bridge

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


token_service = TokenService(get_db)


def init_db():
    """Create tables and run safe migrations."""
    with get_db() as conn:
        # --- Users table (P0-1) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- Messages table ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('private', 'public')),
                conversation_id TEXT NOT NULL DEFAULT '',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migrations for existing databases
        for col_sql in [
            "ALTER TABLE messages ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('private', 'public'))",
            "ALTER TABLE messages ADD COLUMN user_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Backfill user_id from sender_name for legacy rows
        conn.execute("""
            UPDATE messages SET user_id = sender_name
            WHERE user_id = '' AND role = 'user'
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reference_type TEXT,
                reference_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migration: add reference_id column to existing tables
        try:
            conn.execute("ALTER TABLE token_transactions ADD COLUMN reference_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Unique index for idempotency: same (user_id, reference_type, reference_id) = no duplicate reward
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_token_idempotency
            ON token_transactions (user_id, reference_type, reference_id)
            WHERE reference_type IS NOT NULL AND reference_id IS NOT NULL
        """)

        # --- Game rooms table (P1-2: Trivia game loop) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                game_type TEXT NOT NULL DEFAULT 'trivia',
                question_index INTEGER NOT NULL,
                correct_answer TEXT NOT NULL,
                reward INTEGER NOT NULL DEFAULT 5,
                status TEXT NOT NULL DEFAULT 'WAITING'
                    CHECK(status IN ('WAITING', 'IN_PROGRESS', 'FINISHED')),
                result TEXT DEFAULT NULL
                    CHECK(result IS NULL OR result IN ('correct', 'wrong', 'timeout')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME DEFAULT NULL
            )
        """)

        # Safe migration for game_rooms
        for col_sql in [
            "ALTER TABLE game_rooms ADD COLUMN result TEXT DEFAULT NULL",
            "ALTER TABLE game_rooms ADD COLUMN finished_at DATETIME DEFAULT NULL",
            # --- Ma Sói RPG state machine migration ---
            "ALTER TABLE game_rooms ADD COLUMN phase TEXT NOT NULL DEFAULT 'WAITING'",
            "ALTER TABLE game_rooms ADD COLUMN round_number INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE game_rooms ADD COLUMN conversation_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE game_rooms ADD COLUMN game_state TEXT NOT NULL DEFAULT '{}'",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass

        # Backfill phase from status for legacy trivia rows
        conn.execute("""
            UPDATE game_rooms SET phase = status
            WHERE phase = 'WAITING' AND status != 'WAITING' AND game_type = 'trivia'
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress', 'completed', 'abandoned')),
                progress INTEGER NOT NULL DEFAULT 0,
                target_date TEXT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe migration: add progress and target_date to existing goals tables
        for col_sql in [
            "ALTER TABLE goals ADD COLUMN progress INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE goals ADD COLUMN target_date TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass


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
vector_memory: VectorMemory | None = None


def init_chromadb():
    """Initialize persistent ChromaDB store with journal_embeddings collection."""
    global chroma_client, journal_collection, vector_memory
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        journal_collection = chroma_client.get_or_create_collection(
            name="journal_embeddings",
            metadata={"description": "User journal entry embeddings for semantic search"},
        )
        vector_memory = VectorMemory(collection=journal_collection, embed_fn=embed_text)
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

MOOD_SYSTEM_PROMPT = """\
You are a sentiment classifier. Read the user's Vietnamese journal entry and classify it.

RULES:
- Positive, happy, excited, energetic, playful → planet = "sun"
- Lonely, nostalgic, sad, missing someone, needing connection → planet = "garden"
- Neutral, informational, unclear → planet = "sun"

You MUST reply with ONLY this JSON and nothing else — no markdown, no explanation:
{"mood": "<short Vietnamese mood description>", "planet": "<sun or garden>", "action": "<stay or connect_others>"}

EXAMPLES:
User: Hôm nay tôi rất vui vì được gặp bạn bè!
{"mood": "Vui vẻ, hào hứng", "planet": "sun", "action": "stay"}

User: Tôi nhớ mẹ quá, muốn về nhà...
{"mood": "Nhớ nhung, cô đơn", "planet": "garden", "action": "connect_others"}

User: Hôm nay tôi đi học bình thường.
{"mood": "Bình thường", "planet": "sun", "action": "stay"}"""

# Canonical planet names — the LLM returns short keys ("sun"/"garden"),
# the normaliser maps them to the full Vietnamese strings used everywhere else.
_PLANET_MAP = {
    "sun":    "Hành tinh mặt trời",
    "garden": "Vườn kỷ niệm",
}
_ACTION_MAP = {
    "sun":    "stay",
    "garden": "connect_others",
}

@app.get("/")
async def home():
    return {"message": "Chào mừng đến với WildTails Multi-Agent Hub! Server đang hoạt động tốt."}


@app.get("/api/health")
async def health_check():
    """Health endpoint: checks SQLite, ChromaDB, Ollama chat, and Ollama embed."""
    services = {}

    # SQLite
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        services["sqlite"] = {"ok": True}
    except Exception as e:
        services["sqlite"] = {"ok": False, "error": str(e)}

    # ChromaDB
    try:
        if journal_collection is not None:
            journal_collection.count()
            services["chromadb"] = {"ok": True}
        else:
            services["chromadb"] = {"ok": False, "error": "Not initialized"}
    except Exception as e:
        services["chromadb"] = {"ok": False, "error": str(e)}

    # Ollama Chat
    try:
        resp = await ollama_client.chat.completions.create(
            model=OLLAMA_CHAT_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        services["ollama_chat"] = {"ok": True, "model": OLLAMA_CHAT_MODEL}
    except Exception as e:
        services["ollama_chat"] = {"ok": False, "model": OLLAMA_CHAT_MODEL, "error": str(e)}

    # Ollama Embed
    try:
        resp = await ollama_client.embeddings.create(
            model=OLLAMA_EMBED_MODEL,
            input="ping",
        )
        services["ollama_embed"] = {"ok": True, "model": OLLAMA_EMBED_MODEL}
    except Exception as e:
        services["ollama_embed"] = {"ok": False, "model": OLLAMA_EMBED_MODEL, "error": str(e)}

    all_ok = all(s.get("ok") for s in services.values())
    return {"status": "healthy" if all_ok else "degraded", "services": services}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SSE subscriber management via EventBridge (bounded queues, graceful cleanup)
# Legacy alias kept for test compatibility
subscribers = []  # NOTE: kept for backward compat in tests; real path uses event_bridge

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
    target_date: str = ""  # optional ISO date string e.g. "2026-09-01"


class GoalUpdate(BaseModel):
    status: str = ""  # "completed" or "abandoned" (optional if only updating progress)
    progress: int = -1  # 0-100, -1 means don't update

# 1. Phân tích cảm xúc & Đề xuất Planet (LLM-powered via Ollama)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def _extract_json(raw: str) -> dict | None:
    """Best-effort JSON extraction from LLM output.

    Handles three common failure modes:
    1. Clean JSON  → parse directly
    2. Markdown-fenced JSON (```json ... ```)  → strip fences first
    3. JSON buried in conversational text  → regex extract first { ... }
    """
    text = raw.strip()

    # 1. Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try stripping markdown code fences
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Try extracting first JSON object from freeform text
    m = _JSON_OBJECT_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _normalise_planet(raw_planet: str) -> str | None:
    """Map any reasonable LLM planet output to a canonical Vietnamese name.

    Accepts: "sun", "garden", or the full Vietnamese strings with any
    casing/whitespace.  Returns the canonical name or None on failure.
    """
    p = raw_planet.strip().lower()

    # Short keys (preferred — the new prompt uses these)
    if p in _PLANET_MAP:
        return _PLANET_MAP[p]

    # Full Vietnamese names (legacy / fallback)
    if "mặt trời" in p or "mat troi" in p:
        return _PLANET_MAP["sun"]
    if "kỷ niệm" in p or "ky niem" in p or "garden" in p:
        return _PLANET_MAP["garden"]

    return None


async def mood_and_planet_recommender(text: str) -> dict:
    fallback = {
        "mood": "Bình thường",
        "planet": "Hành tinh mặt trời",
        "action": "stay",
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
        logger.info("[MoodRouter] LLM raw output: %s", raw)

        result = _extract_json(raw)
        if result is None:
            logger.warning("[MoodRouter] JSON extraction failed for: %s", raw)
            return fallback

        # Normalise planet with fuzzy matching
        raw_planet = result.get("planet", "")
        planet = _normalise_planet(str(raw_planet))
        if planet is None:
            logger.warning("[MoodRouter] Unknown planet value: %r", raw_planet)
            return fallback

        # Normalise action
        raw_action = str(result.get("action", "")).strip().lower()
        if raw_action not in ("stay", "connect_others"):
            # Infer action from planet
            raw_action = _ACTION_MAP.get(
                "sun" if planet == _PLANET_MAP["sun"] else "garden",
                "stay",
            )

        mood = str(result.get("mood", "")).strip()
        if not mood:
            mood = fallback["mood"]

        final = {"mood": mood, "planet": planet, "action": raw_action}
        logger.info("[MoodRouter] Resolved: %s", final)
        return final

    except Exception as e:
        logger.warning("[MoodRouter] Exception during mood analysis: %s", e)
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

    # Generate a conversation_id for this interaction
    conversation_id = str(uuid.uuid4())

    # Upsert user record
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, display_name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name",
            (payload.user_id, payload.user_name),
        )

    # Save user message and system reply to DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (sender_name, user_id, role, content, visibility, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
            (payload.user_name, payload.user_id, "user", payload.message, vis, conversation_id),
        )
        conn.execute(
            "INSERT INTO messages (sender_name, user_id, role, content, visibility, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("System Agent", payload.user_id, "assistant", agent_reply, vis, conversation_id),
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
            "event_id": str(uuid.uuid4()),
            "type": "NEW_USER_JOINED",
            "user_id": payload.user_id,
            "conversation_id": conversation_id,
            "planet": analysis["planet"],
            "user": payload.user_name,
            "message": f"Agent của {payload.user_name} vừa tham gia {analysis['planet']}.",
        }
        await event_bridge.broadcast(event_payload)

        # Real-time SSE: broadcast NEW_MESSAGE so the UI component can
        # inject the user's entry without a full Streamlit rerun.
        new_msg_event = {
            "event_id": str(uuid.uuid4()),
            "type": "NEW_MESSAGE",
            "user_id": payload.user_id,
            "conversation_id": conversation_id,
            "sender": payload.user_name,
            "content": payload.message,
            "visibility": "public",
        }
        await event_bridge.broadcast(new_msg_event)

        # Legacy subscriber support (tests)
        for queue in subscribers:
            await queue.put(json.dumps(event_payload))

    response_data["conversation_id"] = conversation_id
    return response_data

# 3. SSE Server Endpoint để các Agent của người khác lắng nghe
@app.get("/api/sse/events")
async def sse_events(request: Request):
    queue = event_bridge.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield {"event": "agent_message", "data": data}
        finally:
            event_bridge.unsubscribe(queue)

    return EventSourceResponse(event_generator())

# 4. API để External Agent gửi tin nhắn vào hội thoại chung
class ExternalAgentReply(BaseModel):
    agent_name: str
    message: str
    user_id: str = ""
    conversation_id: str = ""
    depth: int = 0  # inter-agent reply depth (0 = direct reply to user)

@app.post("/api/external_agent_reply")
async def receive_external_agent_reply(payload: ExternalAgentReply):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (sender_name, user_id, role, content, visibility, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
            (payload.agent_name, payload.user_id, "assistant", payload.message, "public", payload.conversation_id),
        )

    # Real-time SSE: broadcast AGENT_REPLY so the UI component can
    # inject the agent's response without a full Streamlit rerun.
    # The depth field enables inter-agent collaboration while preventing
    # infinite loops — agents refuse to reply when depth >= MAX_AGENT_DEPTH.
    agent_reply_event = {
        "event_id": str(uuid.uuid4()),
        "type": "AGENT_REPLY",
        "user_id": payload.user_id,
        "conversation_id": payload.conversation_id,
        "sender": payload.agent_name,
        "content": payload.message,
        "visibility": "public",
        "depth": payload.depth,
    }
    await event_bridge.broadcast(agent_reply_event)

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
                "SELECT sender_name, user_id, role, content, visibility, conversation_id, timestamp FROM messages ORDER BY id"
            ).fetchall()
        elif scope.startswith("owner:"):
            owner_id = scope.split(":", 1)[1]
            rows = conn.execute(
                "SELECT sender_name, user_id, role, content, visibility, conversation_id, timestamp FROM messages "
                "WHERE visibility = 'public' OR user_id = ? ORDER BY id",
                (owner_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sender_name, user_id, role, content, visibility, conversation_id, timestamp FROM messages "
                "WHERE visibility = 'public' ORDER BY id"
            ).fetchall()
    return {
        "messages": [
            {
                "role": r["role"],
                "sender": r["sender_name"],
                "user_id": r["user_id"],
                "content": r["content"],
                "visibility": r["visibility"],
                "conversation_id": r["conversation_id"],
            }
            for r in rows
        ]
    }

# 6. Knowledge Ingestion API (Phase D - Local RAG)
@app.post("/api/knowledge/ingest")
async def ingest_knowledge(payload: KnowledgeIngestRequest):
    """Fetch a public URL, extract text, chunk it, embed & store in ChromaDB."""
    from mcp_tools import fetch_and_extract, chunk_text, validate_url

    # Validate URL before any network access (SSRF prevention) — checked FIRST
    if validate_url(payload.url) is None:
        return {"status": "error", "detail": "Invalid or blocked URL. Only public http/https URLs are allowed."}

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


# 6a. Knowledge Search & RAG Ask API (Phase 5 - P0-7)
class KnowledgeSearchRequest(BaseModel):
    query: str
    n_results: int = 5
    source_type: str = ""  # optional filter: "article", "youtube_transcript", or ""


@app.post("/api/knowledge/search")
async def search_knowledge(payload: KnowledgeSearchRequest):
    """Semantic search over ingested knowledge chunks."""
    if vector_memory is None:
        return {"results": [], "detail": "Vector memory not initialized"}

    embedding = await embed_text(payload.query)
    if embedding is None:
        return {"results": [], "detail": "Embedding generation failed"}

    # Build where filter: public knowledge only, optional source_type
    where_filter: dict = {"visibility": "public"}
    if payload.source_type:
        where_filter = {
            "$and": [
                {"visibility": "public"},
                {"source_type": payload.source_type},
            ]
        }

    try:
        results = journal_collection.query(
            query_embeddings=[embedding],
            n_results=payload.n_results,
            where=where_filter,
        )
    except Exception as e:
        logger.warning("Knowledge search failed: %s", e)
        return {"results": [], "detail": str(e)}

    formatted = []
    if results and results.get("documents"):
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
        for doc, meta, dist in zip(docs, metas, dists):
            formatted.append({
                "document": doc,
                "metadata": meta,
                "distance": dist,
            })

    return {"results": formatted}


class KnowledgeAskRequest(BaseModel):
    question: str
    n_context: int = 5
    source_type: str = ""


@app.post("/api/knowledge/ask")
async def ask_knowledge(payload: KnowledgeAskRequest):
    """RAG endpoint: retrieve relevant knowledge, then generate an LLM answer.

    Pipeline: Question -> Embed -> ChromaDB search -> Context assembly -> LLM answer
    """
    if vector_memory is None:
        return {"answer": "", "sources": [], "detail": "Vector memory not initialized"}

    # Step 1: Retrieve relevant context chunks
    search_resp = await search_knowledge(KnowledgeSearchRequest(
        query=payload.question,
        n_results=payload.n_context,
        source_type=payload.source_type,
    ))
    results = search_resp.get("results", [])

    if not results:
        return {"answer": "Không tìm thấy thông tin liên quan trong cơ sở kiến thức.", "sources": []}

    # Step 2: Assemble context for LLM
    context_parts = []
    sources = []
    for r in results:
        context_parts.append(r["document"])
        meta = r.get("metadata", {})
        source_info = {
            "title": meta.get("title", ""),
            "source_url": meta.get("source_url", ""),
            "source_type": meta.get("source_type", ""),
        }
        if source_info not in sources:
            sources.append(source_info)

    context_text = "\n\n---\n\n".join(context_parts)

    # Step 3: Generate answer with LLM
    rag_prompt = (
        "Dựa trên các đoạn trích kiến thức bên dưới, hãy trả lời câu hỏi của người dùng bằng tiếng Việt.\n"
        "Chỉ sử dụng thông tin từ các đoạn trích được cung cấp. Nếu không đủ thông tin, hãy nói rõ.\n\n"
        f"--- KIẾN THỨC ---\n{context_text}\n--- HẾT KIẾN THỨC ---\n\n"
        f"Câu hỏi: {payload.question}"
    )

    try:
        response = await ollama_client.chat.completions.create(
            model=OLLAMA_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Bạn là trợ lý thông minh trong hệ thống WildTails. Trả lời chính xác dựa trên kiến thức được cung cấp."},
                {"role": "user", "content": rag_prompt},
            ],
            temperature=0.3,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("RAG LLM generation failed: %s", e)
        answer = "Xin lỗi, không thể tạo câu trả lời lúc này."

    return {"answer": answer, "sources": sources}


# 6b. Semantic Vector Search API (Phase 5 - P0-4)
class VectorSearchRequest(BaseModel):
    query: str
    n_results: int = 5
    user_id: str = ""
    include_private: bool = False


@app.post("/api/memory/search")
async def search_memory(payload: VectorSearchRequest):
    """Privacy-aware semantic search over journal embeddings."""
    if vector_memory is None:
        return {"results": [], "detail": "Vector memory not initialized"}

    results = await vector_memory.search(
        query=payload.query,
        n_results=payload.n_results,
        user_id=payload.user_id,
        include_private=payload.include_private,
    )
    return {"results": results}


# 7. Goals API (Phase F - Discipline Boss support)
@app.post("/api/goals")
async def create_goal(payload: GoalCreate):
    """Create a new goal and broadcast GOAL_UPDATE event."""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO goals (user_id, user_name, title, target_date) VALUES (?, ?, ?, ?)",
            (payload.user_id, payload.user_name, payload.title, payload.target_date or None),
        )
        goal_id = cursor.lastrowid

    # Broadcast to Discipline Boss agent
    event_payload = {
        "event_id": str(uuid.uuid4()),
        "type": "GOAL_UPDATE",
        "user_id": payload.user_id,
        "conversation_id": "",
        "user": payload.user_name,
        "goal_id": goal_id,
        "goal_title": payload.title,
        "status": "in_progress",
    }
    await event_bridge.broadcast(event_payload)

    return {"status": "success", "goal_id": goal_id}


@app.put("/api/goals/{goal_id}")
async def update_goal(goal_id: int, payload: GoalUpdate):
    """Update goal status and/or progress, then broadcast event."""
    if payload.status and payload.status not in ("completed", "abandoned"):
        return {"status": "error", "detail": "Invalid status"}

    if payload.progress != -1 and not (0 <= payload.progress <= 100):
        return {"status": "error", "detail": "Progress must be 0-100"}

    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, user_name, title, progress, target_date FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not row:
            return {"status": "error", "detail": "Goal not found"}

        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params = []

        if payload.status:
            updates.append("status = ?")
            params.append(payload.status)

        if payload.progress != -1:
            updates.append("progress = ?")
            params.append(payload.progress)
            # Auto-complete if progress reaches 100
            if payload.progress >= 100 and not payload.status:
                updates.append("status = 'completed'")

        params.append(goal_id)
        conn.execute(f"UPDATE goals SET {', '.join(updates)} WHERE id = ?", params)

    new_status = payload.status or ("completed" if payload.progress >= 100 else "in_progress")
    event_payload = {
        "event_id": str(uuid.uuid4()),
        "type": "GOAL_UPDATE",
        "user_id": row["user_id"],
        "conversation_id": "",
        "user": row["user_name"],
        "goal_id": goal_id,
        "goal_title": row["title"],
        "status": new_status,
        "progress": payload.progress if payload.progress != -1 else row["progress"],
        "target_date": row["target_date"] or "",
    }
    await event_bridge.broadcast(event_payload)

    return {"status": "success"}


@app.get("/api/goals/{user_id}")
async def get_user_goals(user_id: str):
    """List all goals for a user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, status, progress, target_date, created_at, updated_at "
            "FROM goals WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return {
        "goals": [
            {
                "id": r["id"], "title": r["title"], "status": r["status"],
                "progress": r["progress"], "target_date": r["target_date"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    }


@app.post("/api/goals/{user_id}/remind")
async def remind_goals(user_id: str):
    """Trigger a GOAL_REMINDER SSE event for all pending goals of a user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, user_name, progress, target_date FROM goals WHERE user_id = ? AND status = 'in_progress'",
            (user_id,),
        ).fetchall()

    if not rows:
        return {"status": "no_pending_goals"}

    user_name = rows[0]["user_name"]
    pending = [
        {"title": r["title"], "progress": r["progress"], "target_date": r["target_date"] or ""}
        for r in rows
    ]

    event_payload = {
        "event_id": str(uuid.uuid4()),
        "type": "GOAL_REMINDER",
        "user_id": user_id,
        "conversation_id": "",
        "user": user_name,
        "pending_goals": pending,
    }
    await event_bridge.broadcast(event_payload)

    return {"status": "reminder_sent", "pending_count": len(pending)}


# 7b. Game Room API (P1-2: Trivia game loop)
TRIVIA_POOL = [
    {"question": "Hành tinh nào trong hệ Mặt Trời có nhiều mặt trăng nhất?", "answer": "sao thổ", "reward": 5},
    {"question": "Con vật nào có thể ngủ đứng?", "answer": "ngựa", "reward": 3},
    {"question": "Ngôn ngữ lập trình nào được đặt tên theo một loài rắn?", "answer": "python", "reward": 5},
    {"question": "Đại dương nào lớn nhất Trái Đất?", "answer": "thái bình dương", "reward": 3},
    {"question": "Ai là người đầu tiên đặt chân lên Mặt Trăng?", "answer": "neil armstrong", "reward": 5},
]


class GameStartRequest(BaseModel):
    user_id: str
    user_name: str
    game_type: str = "trivia"


class GameAnswerRequest(BaseModel):
    room_id: int
    user_id: str
    answer: str


@app.post("/api/game/start")
async def start_game(payload: GameStartRequest):
    """Start a new trivia game room. Returns question and room_id.

    State machine: WAITING -> IN_PROGRESS (on start) -> FINISHED (on answer)
    """
    import random

    # Pick a random question
    q_index = random.randint(0, len(TRIVIA_POOL) - 1)
    trivia = TRIVIA_POOL[q_index]

    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO game_rooms (user_id, user_name, game_type, question_index, correct_answer, reward, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'IN_PROGRESS')",
            (payload.user_id, payload.user_name, payload.game_type, q_index, trivia["answer"], trivia["reward"]),
        )
        room_id = cursor.lastrowid

    return {
        "status": "started",
        "room_id": room_id,
        "question": trivia["question"],
        "reward": trivia["reward"],
    }


@app.post("/api/game/answer")
async def answer_game(payload: GameAnswerRequest):
    """Submit an answer to an active game room.

    Validates the answer on the backend. Awards tokens exactly ONCE
    via idempotent TokenService (reference_type='trivia', reference_id=room_id).
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, correct_answer, reward, status, question_index FROM game_rooms WHERE id = ?",
            (payload.room_id,),
        ).fetchone()

    if not row:
        return {"status": "error", "detail": "Game room not found"}

    if row["status"] == "FINISHED":
        return {"status": "error", "detail": "Game already finished"}

    if row["user_id"] != payload.user_id:
        return {"status": "error", "detail": "Not your game room"}

    # Normalize and compare answer
    user_answer = payload.answer.strip().lower()
    correct_answer = row["correct_answer"].strip().lower()
    is_correct = correct_answer in user_answer or user_answer in correct_answer

    result = "correct" if is_correct else "wrong"
    reward = row["reward"] if is_correct else 0

    # Transition to FINISHED
    with get_db() as conn:
        conn.execute(
            "UPDATE game_rooms SET status = 'FINISHED', result = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (result, payload.room_id),
        )

    # Award tokens ONCE via idempotent service
    token_result = None
    if is_correct:
        token_result = token_service.award(
            user_id=payload.user_id,
            amount=reward,
            reason=f"Trivia correct (Q{row['question_index']})",
            reference_type="trivia",
            reference_id=str(payload.room_id),
        )

    return {
        "status": "answered",
        "result": result,
        "correct_answer": row["correct_answer"],
        "reward": reward,
        "token_status": token_result["status"] if token_result else "no_reward",
    }


@app.get("/api/game/{user_id}/active")
async def get_active_game(user_id: str):
    """Get the user's currently active game room (trivia or RPG)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, game_type, question_index, reward, status, phase, round_number, game_state "
            "FROM game_rooms "
            "WHERE user_id = ? AND status != 'FINISHED' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()

    if not row:
        return {"active": False}

    if row["game_type"] == "masoi":
        game_state = json.loads(row["game_state"]) if row["game_state"] else {}
        alive_npcs = [n for n in game_state.get("alive_npcs", []) if n.get("alive", True)]
        return {
            "active": True,
            "room_id": row["id"],
            "game_type": "masoi",
            "phase": row["phase"],
            "round_number": row["round_number"],
            "player_role": game_state.get("player_role", ""),
            "alive_npcs": [n["name"] for n in alive_npcs],
            "reward": row["reward"],
        }

    # Trivia (original)
    trivia = TRIVIA_POOL[row["question_index"]] if row["question_index"] < len(TRIVIA_POOL) else None
    return {
        "active": True,
        "room_id": row["id"],
        "game_type": "trivia",
        "question": trivia["question"] if trivia else "Unknown question",
        "reward": row["reward"],
    }


# ---------------------------------------------------------------------------
# 7c. Ma Sói RPG API — multi-turn narrative Werewolf game
# ---------------------------------------------------------------------------
class RPGStartRequest(BaseModel):
    user_id: str
    user_name: str


class RPGActionRequest(BaseModel):
    room_id: int
    user_id: str
    target: str  # NPC name or action target


class RPGAdvanceRequest(BaseModel):
    phase: str
    narrative: str = ""
    game_state: dict | None = None


@app.post("/api/game/rpg/start")
async def start_rpg_game(payload: RPGStartRequest):
    """Create a new Ma Sói RPG room with role assignment.

    State machine: ROLE_ASSIGNMENT → NIGHT_PHASE → DAY_DISCUSSION → VOTING → (loop or FINISHED)
    """
    import random

    # Build cast: 1 player + 5 NPCs from DEFAULT_CAST
    from agents.gamemaster import DEFAULT_CAST, NPC_NAMES, MASOI_ROLES

    roles = list(DEFAULT_CAST)
    random.shuffle(roles)

    player_role = roles[0]
    npc_roles = roles[1:]

    # Pick unique NPC names
    npc_names = random.sample(NPC_NAMES, len(npc_roles))
    alive_npcs = [
        {"name": name, "role": role, "alive": True}
        for name, role in zip(npc_names, npc_roles)
    ]

    game_state = {
        "player_role": player_role,
        "alive_npcs": alive_npcs,
        "narrative_log": [],
        "night_target": "",
        "vote_target": "",
        "last_victim": None,
        "last_protected": False,
        "seer_reveal": None,
        "vote_eliminated": None,
        "winner": None,
    }

    conversation_id = str(uuid.uuid4())

    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO game_rooms "
            "(user_id, user_name, game_type, question_index, correct_answer, reward, status, phase, round_number, conversation_id, game_state) "
            "VALUES (?, ?, 'masoi', 0, '', 15, 'IN_PROGRESS', 'ROLE_ASSIGNMENT', 1, ?, ?)",
            (payload.user_id, payload.user_name, conversation_id, json.dumps(game_state)),
        )
        room_id = cursor.lastrowid

    # Broadcast RPG event so the Gamemaster agent narrates the intro
    rpg_event = {
        "event_id": str(uuid.uuid4()),
        "type": "GAME_REQUEST",
        "game_type": "masoi",
        "room_id": room_id,
        "user_id": payload.user_id,
        "user": payload.user_name,
        "conversation_id": conversation_id,
    }
    await event_bridge.broadcast(rpg_event)

    role_info = MASOI_ROLES.get(player_role, MASOI_ROLES["dân"])
    return {
        "status": "started",
        "room_id": room_id,
        "game_type": "masoi",
        "player_role": player_role,
        "role_emoji": role_info["emoji"],
        "role_label": role_info["label"],
        "role_desc": role_info["desc"],
        "npc_names": [n["name"] for n in alive_npcs],
        "conversation_id": conversation_id,
    }


@app.get("/api/game/rpg/{room_id}")
async def get_rpg_room(room_id: int):
    """Get full RPG room state (used by the Gamemaster agent)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, user_name, game_type, status, phase, round_number, "
            "conversation_id, game_state, reward, created_at, finished_at "
            "FROM game_rooms WHERE id = ? AND game_type = 'masoi'",
            (room_id,),
        ).fetchone()

    if not row:
        return {"error": "Room not found"}

    return {
        "room_id": row["id"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "status": row["status"],
        "phase": row["phase"],
        "round_number": row["round_number"],
        "conversation_id": row["conversation_id"],
        "game_state": row["game_state"],
        "reward": row["reward"],
    }


@app.post("/api/game/rpg/{room_id}/advance")
async def advance_rpg_phase(room_id: int, payload: RPGAdvanceRequest):
    """Advance the RPG room to a new phase (called by the Gamemaster agent).

    Valid phase transitions:
        ROLE_ASSIGNMENT → NIGHT_PHASE
        NIGHT_PHASE     → DAY_DISCUSSION
        DAY_DISCUSSION  → VOTING
        VOTING          → NIGHT_PHASE (next round)
        any             → FINISHED
    """
    VALID_PHASES = ("ROLE_ASSIGNMENT", "NIGHT_PHASE", "DAY_DISCUSSION", "VOTING", "FINISHED")
    if payload.phase not in VALID_PHASES:
        return {"error": f"Invalid phase: {payload.phase}"}

    with get_db() as conn:
        row = conn.execute(
            "SELECT phase, round_number, game_state FROM game_rooms WHERE id = ? AND game_type = 'masoi'",
            (room_id,),
        ).fetchone()
        if not row:
            return {"error": "Room not found"}

        current_phase = row["phase"]
        round_number = row["round_number"]

        # Increment round when cycling back to NIGHT_PHASE from VOTING
        if payload.phase == "NIGHT_PHASE" and current_phase == "VOTING":
            round_number += 1

        new_state = json.dumps(payload.game_state) if payload.game_state is not None else row["game_state"]
        new_status = "FINISHED" if payload.phase == "FINISHED" else "IN_PROGRESS"

        conn.execute(
            "UPDATE game_rooms SET phase = ?, round_number = ?, game_state = ?, status = ?, "
            "finished_at = CASE WHEN ? = 'FINISHED' THEN CURRENT_TIMESTAMP ELSE finished_at END "
            "WHERE id = ?",
            (payload.phase, round_number, new_state, new_status, payload.phase, room_id),
        )

    return {"status": "advanced", "phase": payload.phase, "round_number": round_number}


@app.post("/api/game/rpg/{room_id}/action")
async def rpg_player_action(room_id: int, payload: RPGActionRequest):
    """Submit a player's night action or vote.

    The backend stores the target and broadcasts an RPG_ACTION event
    so the Gamemaster agent can resolve it and narrate the outcome.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, phase, game_state FROM game_rooms WHERE id = ? AND game_type = 'masoi' AND status = 'IN_PROGRESS'",
            (room_id,),
        ).fetchone()

    if not row:
        return {"error": "Room not found or game finished"}
    if row["user_id"] != payload.user_id:
        return {"error": "Not your game room"}

    phase = row["phase"]
    game_state = json.loads(row["game_state"]) if row["game_state"] else {}

    if phase == "NIGHT_PHASE":
        action_type = "night_action"
        game_state["night_target"] = payload.target
    elif phase == "VOTING":
        action_type = "vote"
        game_state["vote_target"] = payload.target
    else:
        return {"error": f"No action allowed in phase: {phase}"}

    # Persist the action
    with get_db() as conn:
        conn.execute(
            "UPDATE game_rooms SET game_state = ? WHERE id = ?",
            (json.dumps(game_state), room_id),
        )

    # Broadcast RPG_ACTION for the Gamemaster agent to resolve
    rpg_action_event = {
        "event_id": str(uuid.uuid4()),
        "type": "RPG_ACTION",
        "room_id": room_id,
        "user_id": payload.user_id,
        "action": action_type,
        "target": payload.target,
    }
    await event_bridge.broadcast(rpg_action_event)

    return {"status": "action_received", "action": action_type, "target": payload.target}


# 8. Token / Catalyst Points API (Phase G - Gamification)
class TokenAwardRequest(BaseModel):
    user_id: str
    amount: int
    reason: str
    reference_type: str = ""
    reference_id: str = ""


@app.get("/api/tokens/{user_id}")
async def get_token_balance(user_id: str):
    """Return total Catalyst Points for a user."""
    balance = token_service.get_balance(user_id)
    return {"user_id": user_id, "balance": balance}


@app.get("/api/tokens/{user_id}/transactions")
async def get_token_transactions(user_id: str, limit: int = 50):
    """Return transaction history for a user, most recent first."""
    transactions = token_service.get_transactions(user_id, limit=limit)
    return {"user_id": user_id, "transactions": transactions}


@app.post("/api/tokens/award")
async def award_tokens(payload: TokenAwardRequest):
    """Award or deduct Catalyst Points with idempotency.

    If reference_type and reference_id are both provided, duplicate
    awards for the same (user_id, reference_type, reference_id) are
    silently ignored (returns status='duplicate').
    """
    result = token_service.award(
        user_id=payload.user_id,
        amount=payload.amount,
        reason=payload.reason,
        reference_type=payload.reference_type or None,
        reference_id=payload.reference_id or None,
    )
    return result


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


# 9b. Semantic Event Matching API (P1-3)
@app.post("/api/events/embed")
async def embed_events():
    """Embed all cached Wildcats events into ChromaDB for semantic matching.

    Each event is stored with source_type='wildcats_event' metadata.
    Uses event title as the ChromaDB document ID prefix to avoid duplicates.
    """
    from services.wildcats_events import event_cache

    if journal_collection is None:
        return {"status": "error", "detail": "ChromaDB not initialized"}

    events = event_cache.get_events()
    if not events:
        events = event_cache.get_events(use_fixture=True)

    embedded_count = 0
    for ev in events:
        text = f"{ev.title}. {ev.description}. Tags: {', '.join(ev.tags)}"
        embedding = await embed_text(text)
        if embedding is not None:
            doc_id = f"event_{ev.title.lower().replace(' ', '_')[:50]}"
            try:
                journal_collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[{
                        "source_type": "wildcats_event",
                        "title": ev.title,
                        "event_date": ev.event_date or "",
                        "location": ev.location or "",
                        "event_url": ev.event_url or "",
                        "tags": ", ".join(ev.tags),
                        "visibility": "public",
                    }],
                )
                embedded_count += 1
            except Exception as e:
                logger.warning("Failed to embed event '%s': %s", ev.title, e)

    return {"status": "success", "embedded": embedded_count, "total": len(events)}


class SemanticEventMatchRequest(BaseModel):
    query: str
    n_results: int = 3


@app.post("/api/events/match")
async def match_events_semantic(payload: SemanticEventMatchRequest):
    """Semantic event matching: find events most relevant to a user query.

    Uses ChromaDB vector similarity. Returns ONLY real event data, never fabricated.
    """
    if journal_collection is None:
        return {"matches": [], "detail": "ChromaDB not initialized"}

    embedding = await embed_text(payload.query)
    if embedding is None:
        return {"matches": [], "detail": "Embedding failed"}

    try:
        results = journal_collection.query(
            query_embeddings=[embedding],
            n_results=payload.n_results,
            where={"source_type": "wildcats_event"},
        )
    except Exception as e:
        logger.warning("Semantic event match failed: %s", e)
        return {"matches": [], "detail": str(e)}

    matches = []
    if results and results.get("documents"):
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
        for doc, meta, dist in zip(docs, metas, dists):
            matches.append({
                "title": meta.get("title", ""),
                "event_date": meta.get("event_date", ""),
                "location": meta.get("location", ""),
                "event_url": meta.get("event_url", ""),
                "tags": meta.get("tags", ""),
                "distance": dist,
            })

    return {"matches": matches}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)