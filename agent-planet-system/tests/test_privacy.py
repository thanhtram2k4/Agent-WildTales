# tests/test_privacy.py — Database isolation & privacy tests
"""
Tests that private messages (Captain's Cabin) never leak to public or
external-agent scopes, and that owner scope correctly includes private
entries belonging to the requesting user.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.fixture
def mock_ollama():
    """Mock the Ollama LLM so tests don't need a running model."""
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content='{"mood": "vui vẻ", "planet": "Hành tinh mặt trời", "action": "stay"}'))
    ]
    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_response) as m:
        yield m


@pytest.fixture
def mock_embed():
    """Mock embedding to avoid needing nomic-embed-text."""
    with patch("app.embed_text", new_callable=AsyncMock, return_value=None):
        yield


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    """Use a temporary SQLite DB for each test to prevent cross-contamination."""
    import app as app_mod
    test_db = str(tmp_path / "test.db")
    original = app_mod.DB_PATH
    app_mod.DB_PATH = test_db
    app_mod.init_db()
    yield
    app_mod.DB_PATH = original


@pytest.mark.asyncio
async def test_private_message_not_in_public_scope(mock_ollama, mock_embed):
    """A private journal entry must NOT appear in the default public scope."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Send a private message
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "My secret diary entry", "visibility": "private",
        })

        # Public scope should return nothing
        resp = await client.get("/api/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert "My secret diary entry" not in contents


@pytest.mark.asyncio
async def test_private_message_visible_to_owner(mock_ollama, mock_embed):
    """A private message should be visible when using owner scope."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Private thoughts", "visibility": "private",
        })

        resp = await client.get("/api/messages", params={"scope": "owner:u1"})
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert "Private thoughts" in contents


@pytest.mark.asyncio
async def test_private_message_not_visible_to_other_owner(mock_ollama, mock_embed):
    """User A's private message must NOT appear in User B's owner scope."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Mina secret", "visibility": "private",
        })

        resp = await client.get("/api/messages", params={"scope": "owner:u2"})
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert "Mina secret" not in contents


@pytest.mark.asyncio
async def test_system_scope_sees_everything(mock_ollama, mock_embed):
    """System scope must return both public and private messages."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Public note", "visibility": "public",
        })
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Secret note", "visibility": "private",
        })

        resp = await client.get("/api/messages", params={"scope": "system"})
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert "Public note" in contents
        assert "Secret note" in contents


@pytest.mark.asyncio
async def test_private_message_does_not_trigger_sse(mock_ollama, mock_embed):
    """Private entries must NEVER broadcast SSE events to agents."""
    from app import app, subscribers
    import asyncio

    transport = ASGITransport(app=app)
    # Set up a spy queue to capture SSE events
    spy_queue = asyncio.Queue()
    subscribers.append(spy_queue)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/chat", json={
                "user_id": "u1", "user_name": "Mina",
                "message": "Super secret private entry", "visibility": "private",
            })

        # Queue must remain empty — no SSE was broadcast
        assert spy_queue.empty(), "Private message triggered SSE broadcast!"
    finally:
        subscribers.remove(spy_queue)


@pytest.mark.asyncio
async def test_public_message_does_trigger_sse(mock_ollama, mock_embed):
    """Public entries SHOULD broadcast SSE events."""
    from app import app, subscribers
    import asyncio

    transport = ASGITransport(app=app)
    spy_queue = asyncio.Queue()
    subscribers.append(spy_queue)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/chat", json={
                "user_id": "u1", "user_name": "Mina",
                "message": "Hello planet!", "visibility": "public",
            })

        assert not spy_queue.empty(), "Public message did NOT trigger SSE broadcast!"
    finally:
        subscribers.remove(spy_queue)


@pytest.mark.asyncio
async def test_agent_context_excludes_private_messages(mock_ollama, mock_embed):
    """Agent context (public scope) must never include private messages."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a private and a public message
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Private journal secret", "visibility": "private",
        })
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Public hello", "visibility": "public",
        })

        # Agents use public scope
        resp = await client.get("/api/messages", params={"scope": "public"})
        messages = resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert "Private journal secret" not in contents
        assert "Public hello" in contents


@pytest.mark.asyncio
async def test_public_message_visible_everywhere(mock_ollama, mock_embed):
    """A public message should appear in all scopes."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/chat", json={
            "user_id": "u1", "user_name": "Mina",
            "message": "Hello world", "visibility": "public",
        })

        for scope in ["public", "owner:u1", "owner:u2", "system"]:
            resp = await client.get("/api/messages", params={"scope": scope})
            contents = [m["content"] for m in resp.json()["messages"]]
            assert "Hello world" in contents, f"Missing in scope={scope}"
