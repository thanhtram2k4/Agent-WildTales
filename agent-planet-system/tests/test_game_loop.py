# tests/test_game_loop.py — Trivia game loop state machine tests
"""
Tests for:
- Game room creation (WAITING -> IN_PROGRESS)
- Answer validation and state transition (IN_PROGRESS -> FINISHED)
- Idempotent token awarding (no double rewards)
- Error handling (wrong user, already finished, not found)
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
async def test_start_game_returns_question():
    """POST /api/game/start should return a question and room_id."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        data = resp.json()
        assert data["status"] == "started"
        assert "room_id" in data
        assert "question" in data
        assert data["reward"] > 0


@pytest.mark.asyncio
async def test_correct_answer_awards_tokens():
    """Correct answer should transition to FINISHED and award tokens."""
    from app import app, TRIVIA_POOL

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Start game
        start_resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        room_id = start_resp.json()["room_id"]

        # Find the correct answer from the pool
        q_index = None
        from app import get_db
        with get_db() as conn:
            row = conn.execute("SELECT correct_answer FROM game_rooms WHERE id = ?", (room_id,)).fetchone()
        correct = row["correct_answer"]

        # Answer correctly
        ans_resp = await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u1", "answer": correct,
        })
        data = ans_resp.json()
        assert data["status"] == "answered"
        assert data["result"] == "correct"
        assert data["reward"] > 0
        assert data["token_status"] == "awarded"

        # Verify balance
        bal_resp = await client.get("/api/tokens/u1")
        assert bal_resp.json()["balance"] == data["reward"]


@pytest.mark.asyncio
async def test_wrong_answer_no_tokens():
    """Wrong answer should finish the game but not award tokens."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        room_id = start_resp.json()["room_id"]

        ans_resp = await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u1", "answer": "completely wrong answer xyz",
        })
        data = ans_resp.json()
        assert data["result"] == "wrong"
        assert data["reward"] == 0
        assert data["token_status"] == "no_reward"

        # Balance should be 0
        bal_resp = await client.get("/api/tokens/u1")
        assert bal_resp.json()["balance"] == 0


@pytest.mark.asyncio
async def test_double_answer_rejected():
    """Answering a finished game should return an error."""
    from app import app, get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        room_id = start_resp.json()["room_id"]

        with get_db() as conn:
            row = conn.execute("SELECT correct_answer FROM game_rooms WHERE id = ?", (room_id,)).fetchone()
        correct = row["correct_answer"]

        # First answer
        await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u1", "answer": correct,
        })

        # Second answer — should be rejected
        resp2 = await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u1", "answer": correct,
        })
        assert resp2.json()["status"] == "error"
        assert "already finished" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wrong_user_rejected():
    """A different user cannot answer someone else's game."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        room_id = start_resp.json()["room_id"]

        resp = await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u_hacker", "answer": "anything",
        })
        assert resp.json()["status"] == "error"
        assert "not your" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_nonexistent_room():
    """Answering a non-existent room should return an error."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/game/answer", json={
            "room_id": 99999, "user_id": "u1", "answer": "anything",
        })
        assert resp.json()["status"] == "error"


@pytest.mark.asyncio
async def test_get_active_game():
    """GET /api/game/{user_id}/active should return the active game."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No active game initially
        resp = await client.get("/api/game/u1/active")
        assert resp.json()["active"] is False

        # Start a game
        await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })

        # Now should be active
        resp = await client.get("/api/game/u1/active")
        data = resp.json()
        assert data["active"] is True
        assert "question" in data


@pytest.mark.asyncio
async def test_token_idempotency_on_game():
    """Tokens should only be awarded once per game room (idempotent)."""
    from app import app, get_db, token_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_resp = await client.post("/api/game/start", json={
            "user_id": "u1", "user_name": "Mina",
        })
        room_id = start_resp.json()["room_id"]

        with get_db() as conn:
            row = conn.execute("SELECT correct_answer, reward FROM game_rooms WHERE id = ?", (room_id,)).fetchone()

        # Answer correctly
        await client.post("/api/game/answer", json={
            "room_id": room_id, "user_id": "u1", "answer": row["correct_answer"],
        })

        # Try to manually award again with same reference — should be duplicate
        result = token_service.award(
            user_id="u1", amount=row["reward"], reason="trivia again",
            reference_type="trivia", reference_id=str(room_id),
        )
        assert result["status"] == "duplicate"

        # Balance should be reward amount, not doubled
        assert result["balance"] == row["reward"]
