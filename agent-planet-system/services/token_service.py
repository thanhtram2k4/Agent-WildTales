# services/token_service.py — Catalyst Points token service
"""
Manages Catalyst Points (token_transactions) with idempotency support.
Uses (user_id, reference_type, reference_id) as a unique key to prevent
duplicate rewards for the same action.
"""
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger("wildtails.token_service")


class TokenService:
    """Idempotent token transaction service."""

    def __init__(self, get_db_fn):
        """
        Args:
            get_db_fn: Context manager callable that yields a sqlite3.Connection.
        """
        self._get_db = get_db_fn

    def award(
        self,
        user_id: str,
        amount: int,
        reason: str,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
    ) -> dict:
        """Award (or deduct) tokens with optional idempotency.

        If reference_type AND reference_id are both provided, the transaction
        is idempotent — a second call with the same triple is a no-op.

        Args:
            user_id: The user receiving tokens.
            amount: Points to add (positive) or deduct (negative).
            reason: Human-readable reason for the transaction.
            reference_type: Category of the source event (e.g., "trivia", "goal", "journal").
            reference_id: Unique ID within that category (e.g., goal_id, question hash).

        Returns:
            dict with status ("awarded", "duplicate", or "error") and new balance.
        """
        with self._get_db() as conn:
            try:
                conn.execute(
                    "INSERT INTO token_transactions (user_id, amount, reason, reference_type, reference_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, amount, reason, reference_type, reference_id),
                )
            except sqlite3.IntegrityError:
                # Idempotency: duplicate (user_id, reference_type, reference_id)
                balance = self._get_balance(conn, user_id)
                return {"status": "duplicate", "balance": balance}

            balance = self._get_balance(conn, user_id)
            return {"status": "awarded", "balance": balance}

    def get_balance(self, user_id: str) -> int:
        """Get the current token balance for a user."""
        with self._get_db() as conn:
            return self._get_balance(conn, user_id)

    def get_transactions(self, user_id: str, limit: int = 50) -> list[dict]:
        """Get transaction history for a user, most recent first."""
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT id, amount, reason, reference_type, reference_id, created_at "
                "FROM token_transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "amount": r["amount"],
                "reason": r["reason"],
                "reference_type": r["reference_type"],
                "reference_id": r["reference_id"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def _get_balance(self, conn, user_id: str) -> int:
        """Internal: get balance using an existing connection."""
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as balance FROM token_transactions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["balance"]
