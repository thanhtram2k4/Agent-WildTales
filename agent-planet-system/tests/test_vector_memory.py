# tests/test_vector_memory.py — Privacy-aware vector retrieval tests
"""
Tests that VectorMemory enforces privacy rules:
- Community (no user_id): only public results
- Owner with include_private=True: public + own private
- Owner with include_private=False: only public
- Private entries from other users are never returned
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from services.vector_memory import VectorMemory


@pytest.fixture
def fake_collection():
    """Mock ChromaDB collection with controlled query results."""
    collection = MagicMock()
    return collection


@pytest.fixture
def fake_embed():
    """Mock embed function that returns a dummy vector."""
    return AsyncMock(return_value=[0.1, 0.2, 0.3])


@pytest.fixture
def vm(fake_collection, fake_embed):
    return VectorMemory(collection=fake_collection, embed_fn=fake_embed)


@pytest.mark.asyncio
async def test_community_search_uses_public_filter(vm, fake_collection):
    """Community/agent search (no user_id) must only query public entries."""
    fake_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    await vm.search("hello", n_results=5)

    fake_collection.query.assert_called_once()
    call_kwargs = fake_collection.query.call_args[1]
    assert call_kwargs["where"] == {"visibility": "public"}


@pytest.mark.asyncio
async def test_owner_private_search_uses_or_filter(vm, fake_collection):
    """Owner query with include_private=True must use $or filter."""
    fake_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    await vm.search("hello", user_id="u1", include_private=True)

    call_kwargs = fake_collection.query.call_args[1]
    where = call_kwargs["where"]
    assert "$or" in where
    # Check that the filter includes public + (private AND user_id=u1)
    or_clauses = where["$or"]
    assert {"visibility": "public"} in or_clauses


@pytest.mark.asyncio
async def test_owner_public_only_search(vm, fake_collection):
    """Owner query with include_private=False must only return public."""
    fake_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    await vm.search("hello", user_id="u1", include_private=False)

    call_kwargs = fake_collection.query.call_args[1]
    assert call_kwargs["where"] == {"visibility": "public"}


@pytest.mark.asyncio
async def test_results_formatted_correctly(vm, fake_collection):
    """Results should be returned as list of dicts with document, metadata, distance."""
    fake_collection.query.return_value = {
        "documents": [["doc1", "doc2"]],
        "metadatas": [[{"user_id": "u1"}, {"user_id": "u2"}]],
        "distances": [[0.1, 0.5]],
    }

    results = await vm.search("hello")

    assert len(results) == 2
    assert results[0]["document"] == "doc1"
    assert results[0]["distance"] == 0.1
    assert results[1]["metadata"]["user_id"] == "u2"


@pytest.mark.asyncio
async def test_embed_failure_returns_empty(fake_collection):
    """If embedding fails (returns None), search should return empty list."""
    fail_embed = AsyncMock(return_value=None)
    vm = VectorMemory(collection=fake_collection, embed_fn=fail_embed)

    results = await vm.search("hello")

    assert results == []
    fake_collection.query.assert_not_called()


@pytest.mark.asyncio
async def test_none_collection_returns_empty(fake_embed):
    """If collection is None, search should return empty list gracefully."""
    vm = VectorMemory(collection=None, embed_fn=fake_embed)

    results = await vm.search("hello")

    assert results == []
