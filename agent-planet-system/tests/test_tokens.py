# tests/test_tokens.py — Token ledger & balance tests
"""
Tests for the Catalyst Points (token_transactions) system:
correct balance calculation, zero-balance for new users, and
multiple transaction aggregation.
"""
import pytest
from httpx import AsyncClient, ASGITransport


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


@pytest.mark.asyncio
async def test_zero_balance_for_new_user():
    """A user with no transactions should have balance 0."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/u_new")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "u_new"
        assert data["balance"] == 0


@pytest.mark.asyncio
async def test_positive_balance():
    """Adding positive transactions should sum correctly."""
    from app import app, get_db

    # Directly insert transactions
    with get_db() as conn:
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", 10, "trivia_correct"))
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", 5, "journal_entry"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/u1")
        assert resp.json()["balance"] == 15


@pytest.mark.asyncio
async def test_mixed_transactions():
    """Positive and negative transactions should net correctly."""
    from app import app, get_db

    with get_db() as conn:
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", 20, "bonus"))
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", -8, "rpg_loss"))
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", 3, "daily_login"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/u1")
        assert resp.json()["balance"] == 15  # 20 - 8 + 3


@pytest.mark.asyncio
async def test_user_isolation():
    """User A's tokens should not affect User B's balance."""
    from app import app, get_db

    with get_db() as conn:
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u1", 100, "big_bonus"))
        conn.execute("INSERT INTO token_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                      ("u2", 5, "small_bonus"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/tokens/u1")
        r2 = await client.get("/api/tokens/u2")
        assert r1.json()["balance"] == 100
        assert r2.json()["balance"] == 5


# --- Token Award Endpoint Tests ---

@pytest.mark.asyncio
async def test_award_tokens_via_api():
    """POST /api/tokens/award should create a transaction and return balance."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tokens/award", json={
            "user_id": "u1",
            "amount": 10,
            "reason": "trivia_correct",
            "reference_type": "trivia",
            "reference_id": "q001",
        })
        data = resp.json()
        assert data["status"] == "awarded"
        assert data["balance"] == 10


@pytest.mark.asyncio
async def test_award_idempotency():
    """Duplicate award with same reference should return 'duplicate' and not add tokens."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First award
        resp1 = await client.post("/api/tokens/award", json={
            "user_id": "u1",
            "amount": 10,
            "reason": "trivia_correct",
            "reference_type": "trivia",
            "reference_id": "q001",
        })
        assert resp1.json()["status"] == "awarded"
        assert resp1.json()["balance"] == 10

        # Duplicate award — same reference
        resp2 = await client.post("/api/tokens/award", json={
            "user_id": "u1",
            "amount": 10,
            "reason": "trivia_correct",
            "reference_type": "trivia",
            "reference_id": "q001",
        })
        assert resp2.json()["status"] == "duplicate"
        assert resp2.json()["balance"] == 10  # unchanged


@pytest.mark.asyncio
async def test_award_different_reference_ids_allowed():
    """Different reference_ids for the same type should both be awarded."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": 5, "reason": "trivia",
            "reference_type": "trivia", "reference_id": "q001",
        })
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": 5, "reason": "trivia",
            "reference_type": "trivia", "reference_id": "q002",
        })

        resp = await client.get("/api/tokens/u1")
        assert resp.json()["balance"] == 10


@pytest.mark.asyncio
async def test_award_without_reference_not_idempotent():
    """Awards without reference_type/reference_id should always go through (no idempotency)."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": 5, "reason": "bonus",
        })
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": 5, "reason": "bonus",
        })

        resp = await client.get("/api/tokens/u1")
        assert resp.json()["balance"] == 10  # both went through


# --- Transaction History Tests ---

@pytest.mark.asyncio
async def test_transaction_history():
    """GET /api/tokens/{user_id}/transactions should return history."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": 10, "reason": "quest_complete",
            "reference_type": "quest", "reference_id": "quest_1",
        })
        await client.post("/api/tokens/award", json={
            "user_id": "u1", "amount": -3, "reason": "rpg_loss",
        })

        resp = await client.get("/api/tokens/u1/transactions")
        data = resp.json()
        assert data["user_id"] == "u1"
        assert len(data["transactions"]) == 2
        # Most recent first
        assert data["transactions"][0]["amount"] == -3
        assert data["transactions"][1]["amount"] == 10


@pytest.mark.asyncio
async def test_empty_transaction_history():
    """New user should have empty transaction history."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/u_new/transactions")
        data = resp.json()
        assert data["transactions"] == []
