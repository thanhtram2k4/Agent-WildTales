# tests/test_integration_privacy.py — Full privacy integration tests
"""
End-to-end privacy proof:

1. User A writes a PRIVATE journal entry.
2. That entry is embedded in ChromaDB with visibility='private'.
3. A PUBLIC agent semantic search (no user_id, include_private=False) CANNOT find it.
4. User A's OWN semantic search (user_id=A, include_private=True) CAN find it.
5. User B's semantic search (user_id=B, include_private=True) CANNOT find it.
6. Private entries never appear in public message scope.
7. Private entries never trigger SSE events.

These tests use a real (in-memory) ChromaDB collection and mock embeddings
to prove the full privacy pipeline end-to-end.
"""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import chromadb
from services.vector_memory import VectorMemory


@pytest.fixture
def chroma_collection():
    """Create a real in-memory ChromaDB collection for integration testing."""
    client = chromadb.Client()
    collection = client.get_or_create_collection(
        name="test_privacy_integration",
    )
    return collection


@pytest.fixture
def deterministic_embed():
    """Embed function that returns a fixed vector for consistent matching."""
    async def _embed(text: str):
        # Simple deterministic embedding: hash the text into a vector
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        return [int(c, 16) / 15.0 for c in h[:16]]  # 16-dim vector
    return _embed


@pytest.fixture
def vm(chroma_collection, deterministic_embed):
    return VectorMemory(collection=chroma_collection, embed_fn=deterministic_embed)


@pytest.fixture
def seeded_collection(chroma_collection, deterministic_embed):
    """Seed the collection with both private and public entries from different users."""
    import hashlib

    entries = [
        {
            "id": "private_a1",
            "doc": "My secret fear of deep water and drowning nightmares",
            "meta": {"user_id": "userA", "user_name": "Alice", "visibility": "private"},
        },
        {
            "id": "public_a1",
            "doc": "I love swimming in the ocean on sunny days",
            "meta": {"user_id": "userA", "user_name": "Alice", "visibility": "public"},
        },
        {
            "id": "private_b1",
            "doc": "I secretly dislike my job but I can't tell anyone",
            "meta": {"user_id": "userB", "user_name": "Bob", "visibility": "private"},
        },
        {
            "id": "public_b1",
            "doc": "Working on an exciting AI hackathon project this weekend",
            "meta": {"user_id": "userB", "user_name": "Bob", "visibility": "public"},
        },
    ]

    for entry in entries:
        h = hashlib.md5(entry["doc"].encode()).hexdigest()
        embedding = [int(c, 16) / 15.0 for c in h[:16]]
        chroma_collection.add(
            ids=[entry["id"]],
            embeddings=[embedding],
            documents=[entry["doc"]],
            metadatas=[entry["meta"]],
        )

    return chroma_collection


# --- Test 1: Public agent search CANNOT see private entries ---

@pytest.mark.asyncio
async def test_public_agent_search_excludes_private(seeded_collection, deterministic_embed):
    """A community agent (no user_id) must never see private entries."""
    vm = VectorMemory(collection=seeded_collection, embed_fn=deterministic_embed)

    # Search for something that would match Alice's private entry about fear
    results = await vm.search("fear water drowning", n_results=10, include_private=False)

    # All results must be public
    for r in results:
        assert r["metadata"]["visibility"] == "public", \
            f"PRIVACY VIOLATION: Private entry leaked to public search! doc={r['document'][:50]}"


# --- Test 2: Owner CAN see their own private entries ---

@pytest.mark.asyncio
async def test_owner_can_see_own_private_entries(seeded_collection, deterministic_embed):
    """User A searching with include_private=True should see their own private entries."""
    vm = VectorMemory(collection=seeded_collection, embed_fn=deterministic_embed)

    results = await vm.search(
        "fear water drowning nightmares",
        n_results=10,
        user_id="userA",
        include_private=True,
    )

    docs = [r["document"] for r in results]
    visibilities = [r["metadata"]["visibility"] for r in results]
    user_ids = [r["metadata"]["user_id"] for r in results]

    # Alice's private entry should be findable
    has_private_a = any(
        r["metadata"]["visibility"] == "private" and r["metadata"]["user_id"] == "userA"
        for r in results
    )
    assert has_private_a, "Owner should be able to find their own private entries"


# --- Test 3: User B CANNOT see User A's private entries ---

@pytest.mark.asyncio
async def test_other_user_cannot_see_private_entries(seeded_collection, deterministic_embed):
    """User B searching with include_private=True must NOT see User A's private entries."""
    vm = VectorMemory(collection=seeded_collection, embed_fn=deterministic_embed)

    results = await vm.search(
        "fear water drowning nightmares",
        n_results=10,
        user_id="userB",
        include_private=True,
    )

    # No result should be Alice's private entry
    for r in results:
        if r["metadata"]["visibility"] == "private":
            assert r["metadata"]["user_id"] == "userB", \
                f"PRIVACY VIOLATION: User B can see User A's private entry! doc={r['document'][:50]}"


# --- Test 4: Private entries never in public message scope (API level) ---

@pytest.fixture(autouse=False)
def isolate_db(tmp_path):
    import app as app_mod
    test_db = str(tmp_path / "test.db")
    original = app_mod.DB_PATH
    app_mod.DB_PATH = test_db
    app_mod.init_db()
    yield
    app_mod.DB_PATH = original


@pytest.fixture
def mock_ollama():
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content='{"mood": "buồn", "planet": "Vườn kỷ niệm", "action": "connect_others"}'))
    ]
    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_response):
        yield


@pytest.fixture
def mock_embed_noop():
    with patch("app.embed_text", new_callable=AsyncMock, return_value=None):
        yield


@pytest.mark.asyncio
async def test_api_private_entry_invisible_to_public_scope(isolate_db, mock_ollama, mock_embed_noop):
    """Full API test: private entry must not appear in public scope."""
    from app import app
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A writes a private entry
        await client.post("/api/chat", json={
            "user_id": "userA", "user_name": "Alice",
            "message": "My deepest secret thought", "visibility": "private",
        })

        # Public scope must NOT include it
        resp = await client.get("/api/messages", params={"scope": "public"})
        public_contents = [m["content"] for m in resp.json()["messages"]]
        assert "My deepest secret thought" not in public_contents

        # User A's own scope MUST include it
        resp = await client.get("/api/messages", params={"scope": "owner:userA"})
        owner_contents = [m["content"] for m in resp.json()["messages"]]
        assert "My deepest secret thought" in owner_contents

        # User B's scope must NOT include it
        resp = await client.get("/api/messages", params={"scope": "owner:userB"})
        other_contents = [m["content"] for m in resp.json()["messages"]]
        assert "My deepest secret thought" not in other_contents


# --- Test 5: Private entries never trigger SSE ---

@pytest.mark.asyncio
async def test_api_private_entry_no_sse_broadcast(isolate_db, mock_ollama, mock_embed_noop):
    """Private entries must NEVER broadcast SSE events."""
    from app import app, subscribers
    from httpx import AsyncClient, ASGITransport

    spy_queue = asyncio.Queue()
    subscribers.append(spy_queue)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/chat", json={
                "user_id": "userA", "user_name": "Alice",
                "message": "Ultra secret private note", "visibility": "private",
            })

        assert spy_queue.empty(), "PRIVACY VIOLATION: Private entry triggered SSE broadcast!"
    finally:
        subscribers.remove(spy_queue)
