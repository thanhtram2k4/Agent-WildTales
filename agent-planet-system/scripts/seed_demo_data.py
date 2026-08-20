"""
seed_demo_data.py — Pre-populate the WildTails SQLite DB with demo users,
goals, and starter Catalyst Points for the Beta Test Demo.

Usage:
    python scripts/seed_demo_data.py

Safe to run multiple times — uses INSERT OR IGNORE so existing data is not
duplicated or overwritten.
"""

import os
import sqlite3
import sys

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "wildtails_memory.db"
)

DEMO_USERS = [
    {"id": "u1", "name": "Mina"},
    {"id": "u2", "name": "Alex"},
    {"id": "u3", "name": "Luna"},
]

DEMO_GOALS = {
    "u1": "Learn AI Product Development",
    "u2": "Build a Personal Knowledge Base",
    "u3": "Complete 7-Day Journaling Challenge",
}

STARTER_POINTS = 50


def seed():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    for user in DEMO_USERS:
        uid, name = user["id"], user["name"]

        # 1. Upsert user
        cursor.execute(
            "INSERT INTO users (id, display_name) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name",
            (uid, name),
        )
        print(f"[+] User '{name}' ({uid}) upserted.")

        # 2. Seed one active goal (skip if user already has an active goal)
        existing_goal = cursor.execute(
            "SELECT id FROM goals WHERE user_id = ? AND status = 'in_progress' LIMIT 1",
            (uid,),
        ).fetchone()

        if not existing_goal:
            cursor.execute(
                "INSERT INTO goals (user_id, user_name, title) VALUES (?, ?, ?)",
                (uid, name, DEMO_GOALS[uid]),
            )
            print(f"    Goal: '{DEMO_GOALS[uid]}'")
        else:
            print(f"    Goal: already has active goal (id={existing_goal['id']}), skipped.")

        # 3. Seed starter Catalyst Points (skip if user already has transactions)
        existing_txn = cursor.execute(
            "SELECT id FROM token_transactions WHERE user_id = ? LIMIT 1",
            (uid,),
        ).fetchone()

        if not existing_txn:
            cursor.execute(
                "INSERT INTO token_transactions (user_id, amount, reason, reference_type) "
                "VALUES (?, ?, ?, ?)",
                (uid, STARTER_POINTS, "Beta tester welcome bonus", "seed"),
            )
            print(f"    Points: +{STARTER_POINTS} Catalyst Points (welcome bonus)")
        else:
            print(f"    Points: already has transactions, skipped.")

    conn.commit()
    conn.close()
    print("\nDone! Demo data is ready.")


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Start the backend first (`python app.py`) to create the DB, then re-run this script.")
        sys.exit(1)
    seed()
