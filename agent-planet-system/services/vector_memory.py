# services/vector_memory.py — Privacy-aware semantic vector retrieval over ChromaDB
"""
Provides semantic search over journal_embeddings with strict privacy enforcement:
- Owner queries: search both public + private entries belonging to that user_id
- Community/agent queries: search ONLY public entries (no private data leaks)
"""
import logging
from typing import Optional

logger = logging.getLogger("wildtails.vector_memory")


class VectorMemory:
    """Privacy-aware wrapper around a ChromaDB collection for semantic retrieval."""

    def __init__(self, collection, embed_fn):
        """
        Args:
            collection: A ChromaDB collection (journal_embeddings).
            embed_fn: Async callable(text) -> list[float] | None.
        """
        self.collection = collection
        self.embed_fn = embed_fn

    async def search(
        self,
        query: str,
        n_results: int = 5,
        user_id: Optional[str] = None,
        include_private: bool = False,
        planet: Optional[str] = None,
        owner_only: bool = False,
    ) -> list[dict]:
        """Semantic search with privacy enforcement.

        Args:
            query: Natural language search query.
            n_results: Max results to return.
            user_id: If provided, scopes results. Required when include_private=True.
            include_private: If True, also return the user's private entries.
                             Only allowed when user_id is set (owner query).
            planet: If provided, restrict results to this planet (e.g., "Hành tinh mặt trời").
            owner_only: If True AND user_id is set, restrict to entries owned by this user.

        Returns:
            List of dicts with keys: document, metadata, distance.
        """
        if self.collection is None:
            logger.warning("VectorMemory.search called but collection is None")
            return []

        embedding = await self.embed_fn(query)
        if embedding is None:
            return []

        # Build ChromaDB where filter for privacy enforcement
        where_filter = self._build_where_filter(
            user_id, include_private, planet=planet, owner_only=owner_only,
        )

        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where_filter,
            )
        except Exception as e:
            logger.warning("VectorMemory search failed: %s", e)
            return []

        return self._format_results(results)

    def _build_where_filter(
        self,
        user_id: Optional[str],
        include_private: bool,
        planet: Optional[str] = None,
        owner_only: bool = False,
    ) -> dict:
        """Build ChromaDB where clause enforcing privacy rules.

        Rules:
        - No user_id (community/agent): only public
        - user_id + include_private=False: only public
        - user_id + include_private=True: public OR (private AND owned by user_id)
        - owner_only + user_id: restrict to entries owned by this user
        - planet filter: restrict to a specific planet (e.g., "Hành tinh mặt trời")
        """
        conditions: list[dict] = []

        # Privacy gate (always applied)
        if include_private and user_id:
            conditions.append({
                "$or": [
                    {"visibility": "public"},
                    {"$and": [
                        {"visibility": "private"},
                        {"user_id": user_id},
                    ]},
                ]
            })
        else:
            conditions.append({"visibility": "public"})

        # Owner scope
        if owner_only and user_id:
            conditions.append({"user_id": user_id})

        # Planet filter
        if planet:
            conditions.append({"planet": planet})

        # Combine conditions
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _format_results(self, results: dict) -> list[dict]:
        """Convert ChromaDB query results into a flat list of dicts."""
        if not results or not results.get("documents"):
            return []

        documents = results["documents"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(documents)

        return [
            {
                "document": doc,
                "metadata": meta,
                "distance": dist,
            }
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]
