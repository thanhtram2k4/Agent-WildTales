# tests/test_knowledge_rag.py — RAG pipeline & URL validation tests
"""
Tests for:
- URL validation (SSRF prevention)
- /api/knowledge/search endpoint
- /api/knowledge/ask endpoint (RAG)
- Blocked URL rejection on ingest
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_ollama():
    """Mock the Ollama LLM."""
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content='{"mood": "vui vẻ", "planet": "Hành tinh mặt trời", "action": "stay"}'))
    ]
    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_response) as m:
        yield m


@pytest.fixture
def mock_embed():
    """Mock embedding."""
    with patch("app.embed_text", new_callable=AsyncMock, return_value=None):
        yield


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    """Temporary SQLite DB per test."""
    import app as app_mod
    test_db = str(tmp_path / "test.db")
    original = app_mod.DB_PATH
    app_mod.DB_PATH = test_db
    app_mod.init_db()
    yield
    app_mod.DB_PATH = original


# --- URL Validation Tests ---

class TestUrlValidation:
    def test_valid_https_url(self):
        from mcp_tools import validate_url
        assert validate_url("https://example.com/article") is not None

    def test_valid_http_url(self):
        from mcp_tools import validate_url
        assert validate_url("http://example.com/page") is not None

    def test_rejects_ftp_scheme(self):
        from mcp_tools import validate_url
        assert validate_url("ftp://example.com/file") is None

    def test_rejects_file_scheme(self):
        from mcp_tools import validate_url
        assert validate_url("file:///etc/passwd") is None

    def test_rejects_empty_url(self):
        from mcp_tools import validate_url
        assert validate_url("") is None

    def test_rejects_overly_long_url(self):
        from mcp_tools import validate_url
        assert validate_url("https://example.com/" + "a" * 5000) is None

    def test_rejects_localhost(self):
        from mcp_tools import validate_url
        result = validate_url("http://127.0.0.1/admin")
        assert result is None

    def test_rejects_private_ip_10(self):
        from mcp_tools import validate_url
        result = validate_url("http://10.0.0.1/internal")
        assert result is None

    def test_rejects_private_ip_192(self):
        from mcp_tools import validate_url
        result = validate_url("http://192.168.1.1/router")
        assert result is None

    def test_rejects_no_hostname(self):
        from mcp_tools import validate_url
        assert validate_url("https://") is None


# --- Knowledge Search Endpoint Tests ---

@pytest.mark.asyncio
async def test_knowledge_search_no_vector_memory(mock_ollama, mock_embed):
    """Search should return empty when vector memory is not initialized."""
    import app as app_mod
    from app import app

    original_vm = app_mod.vector_memory
    app_mod.vector_memory = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/knowledge/search", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    app_mod.vector_memory = original_vm


@pytest.mark.asyncio
async def test_knowledge_search_with_results(mock_ollama):
    """Search should return formatted results from ChromaDB."""
    import app as app_mod
    from app import app

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["chunk about AI"]],
        "metadatas": [[{"title": "AI Article", "source_url": "https://example.com", "source_type": "article", "visibility": "public"}]],
        "distances": [[0.2]],
    }

    original_collection = app_mod.journal_collection
    original_vm = app_mod.vector_memory
    app_mod.journal_collection = mock_collection

    with patch("app.embed_text", new_callable=AsyncMock, return_value=[0.1, 0.2]):
        from services.vector_memory import VectorMemory
        app_mod.vector_memory = VectorMemory(collection=mock_collection, embed_fn=app_mod.embed_text)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/knowledge/search", json={"query": "AI"})
            data = resp.json()
            assert len(data["results"]) == 1
            assert data["results"][0]["document"] == "chunk about AI"

    app_mod.journal_collection = original_collection
    app_mod.vector_memory = original_vm


# --- Knowledge Ask (RAG) Endpoint Tests ---

@pytest.mark.asyncio
async def test_knowledge_ask_no_vector_memory(mock_ollama, mock_embed):
    """Ask should return error when vector memory is not initialized."""
    import app as app_mod
    from app import app

    original_vm = app_mod.vector_memory
    app_mod.vector_memory = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/knowledge/ask", json={"question": "What is AI?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []

    app_mod.vector_memory = original_vm


# --- Ingest URL Validation Tests ---

@pytest.mark.asyncio
async def test_ingest_rejects_blocked_url(mock_ollama, mock_embed):
    """Ingest should reject URLs pointing to private IPs."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/knowledge/ingest", json={
            "url": "http://127.0.0.1/admin",
            "user_id": "u1",
            "user_name": "test",
        })
        data = resp.json()
        assert data["status"] == "error"
        assert "blocked" in data["detail"].lower() or "invalid" in data["detail"].lower()


@pytest.mark.asyncio
async def test_ingest_rejects_file_scheme(mock_ollama, mock_embed):
    """Ingest should reject non-http/https URLs."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/knowledge/ingest", json={
            "url": "file:///etc/passwd",
            "user_id": "u1",
            "user_name": "test",
        })
        data = resp.json()
        assert data["status"] == "error"
