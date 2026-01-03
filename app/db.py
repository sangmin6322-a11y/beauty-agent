import os
import json
import sqlite3
from typing import Any, Dict, List, Optional


def get_conn() -> sqlite3.Connection:
    """
    Render/로컬 모두에서 동작하도록 상대경로 SQLite 사용.
    row_factory를 Row로 두고, fetch 시 dict로 변환해서 반환한다.
    """
    db_path = os.getenv("DB_PATH", os.path.join("data", "app.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            user_id TEXT NOT NULL,
            state TEXT,
            message TEXT,
            reply TEXT,
            slots_json TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_user_ts ON logs(user_id, ts)")
    conn.commit()
    conn.close()


def insert_log(
    user_id: str,
    state: str,
    message: str,
    reply: str,
    slots_json: Optional[str] = None,
) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO logs (user_id, state, message, reply, slots_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, state, message, reply, slots_json),
    )
    conn.commit()
    conn.close()


def fetch_logs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts, state, message, reply, slots_json
        FROM logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, int(limit)),
    )
    rows = cur.fetchall()
    conn.close()

    # sqlite3.Row -> dict
    return [dict(r) for r in rows]
