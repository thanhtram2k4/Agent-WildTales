# tests/test_goals_expanded.py — Expanded goals schema tests
"""
Tests for:
- Goal creation with target_date
- Progress updates (0-100)
- Auto-completion at 100%
- Expanded goal listing with new fields
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
async def test_create_goal_with_target_date():
    """Goal creation should accept and store target_date."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/goals", json={
            "user_id": "u1", "user_name": "Mina",
            "title": "Learn Python", "target_date": "2026-09-01",
        })
        assert resp.json()["status"] == "success"
        goal_id = resp.json()["goal_id"]

        goals_resp = await client.get("/api/goals/u1")
        goals = goals_resp.json()["goals"]
        goal = [g for g in goals if g["id"] == goal_id][0]
        assert goal["target_date"] == "2026-09-01"
        assert goal["progress"] == 0


@pytest.mark.asyncio
async def test_update_progress():
    """PUT should update progress without changing status."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/goals", json={
            "user_id": "u1", "user_name": "Mina", "title": "Read 10 books",
        })
        goal_id = resp.json()["goal_id"]

        # Update progress to 50%
        await client.put(f"/api/goals/{goal_id}", json={"progress": 50})

        goals_resp = await client.get("/api/goals/u1")
        goal = goals_resp.json()["goals"][0]
        assert goal["progress"] == 50
        assert goal["status"] == "in_progress"


@pytest.mark.asyncio
async def test_auto_complete_at_100():
    """Setting progress to 100 should auto-complete the goal."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/goals", json={
            "user_id": "u1", "user_name": "Mina", "title": "Finish project",
        })
        goal_id = resp.json()["goal_id"]

        await client.put(f"/api/goals/{goal_id}", json={"progress": 100})

        goals_resp = await client.get("/api/goals/u1")
        goal = goals_resp.json()["goals"][0]
        assert goal["progress"] == 100
        assert goal["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_progress_rejected():
    """Progress outside 0-100 should be rejected."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/goals", json={
            "user_id": "u1", "user_name": "Mina", "title": "Test",
        })
        goal_id = resp.json()["goal_id"]

        resp = await client.put(f"/api/goals/{goal_id}", json={"progress": 150})
        assert resp.json()["status"] == "error"


@pytest.mark.asyncio
async def test_goal_listing_includes_new_fields():
    """Goal listing should include progress and target_date."""
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/goals", json={
            "user_id": "u1", "user_name": "Mina",
            "title": "Ship feature", "target_date": "2026-12-31",
        })

        resp = await client.get("/api/goals/u1")
        goal = resp.json()["goals"][0]
        assert "progress" in goal
        assert "target_date" in goal
        assert goal["target_date"] == "2026-12-31"
