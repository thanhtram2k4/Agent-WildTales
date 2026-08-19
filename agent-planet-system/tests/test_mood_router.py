# tests/test_mood_router.py — Mood analysis & fallback tests
"""
Tests for the mood_and_planet_recommender function:
valid responses, invalid JSON, missing keys, wrong values,
and complete LLM failure.
"""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_valid_positive_mood():
    """Valid positive mood JSON should return sun planet + stay."""
    from app import mood_and_planet_recommender

    mock_resp = AsyncMock()
    mock_resp.choices = [AsyncMock(message=AsyncMock(
        content='{"mood": "Vui vẻ", "planet": "Hành tinh mặt trời", "action": "stay"}'
    ))]

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        result = await mood_and_planet_recommender("Hôm nay tôi rất vui!")

    assert result["mood"] == "Vui vẻ"
    assert result["planet"] == "Hành tinh mặt trời"
    assert result["action"] == "stay"


@pytest.mark.asyncio
async def test_valid_sad_mood():
    """Valid sad mood JSON should return memory garden + connect_others."""
    from app import mood_and_planet_recommender

    mock_resp = AsyncMock()
    mock_resp.choices = [AsyncMock(message=AsyncMock(
        content='{"mood": "Buồn bã", "planet": "Vườn kỷ niệm", "action": "connect_others"}'
    ))]

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        result = await mood_and_planet_recommender("Tôi nhớ nhà quá")

    assert result["planet"] == "Vườn kỷ niệm"
    assert result["action"] == "connect_others"


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback():
    """If LLM returns non-JSON text, fallback should activate."""
    from app import mood_and_planet_recommender

    mock_resp = AsyncMock()
    mock_resp.choices = [AsyncMock(message=AsyncMock(
        content="I think the user is feeling happy!"
    ))]

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        result = await mood_and_planet_recommender("test")

    assert result["planet"] == "Vườn kỷ niệm"
    assert result["action"] == "connect_others"
    assert "Trầm lắng" in result["mood"]


@pytest.mark.asyncio
async def test_wrong_planet_value_returns_fallback():
    """If LLM returns a planet not in the allowed set, fallback should activate."""
    from app import mood_and_planet_recommender

    mock_resp = AsyncMock()
    mock_resp.choices = [AsyncMock(message=AsyncMock(
        content='{"mood": "ok", "planet": "Mars", "action": "stay"}'
    ))]

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        result = await mood_and_planet_recommender("test")

    assert result["planet"] == "Vườn kỷ niệm"  # fallback


@pytest.mark.asyncio
async def test_missing_mood_key_returns_fallback():
    """If mood key is empty, fallback should activate."""
    from app import mood_and_planet_recommender

    mock_resp = AsyncMock()
    mock_resp.choices = [AsyncMock(message=AsyncMock(
        content='{"mood": "", "planet": "Hành tinh mặt trời", "action": "stay"}'
    ))]

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        result = await mood_and_planet_recommender("test")

    assert result["planet"] == "Vườn kỷ niệm"  # fallback


@pytest.mark.asyncio
async def test_llm_exception_returns_fallback():
    """If the LLM call throws an exception, fallback should activate."""
    from app import mood_and_planet_recommender

    with patch("app.ollama_client.chat.completions.create", new_callable=AsyncMock,
               side_effect=ConnectionError("Ollama not running")):
        result = await mood_and_planet_recommender("test")

    assert result["planet"] == "Vườn kỷ niệm"
    assert result["action"] == "connect_others"
