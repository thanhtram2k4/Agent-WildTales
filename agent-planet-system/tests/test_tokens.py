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
