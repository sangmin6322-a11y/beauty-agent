import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "data/beauty_agent.db")

def _ensure_dir():
    d = os.path.dirname(DB_PATH)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def init_db():
    _ensure_dir()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT NOT NULL,
            state TEXT NOT NULL,
            message TEXT NOT NULL,
            reply TEXT NOT NULL,
            slots_json TEXT
        );
        """)
        con.commit()

@contextmanager
def get_con():
    _ensure_dir()
    con = sqlite3.connect(DB_PATH)
    try:
        yield con
    finally:
        con.close()

def insert_log(user_id: str, state: str, message: str, reply: str, slots_json: str | None):
    with get_con() as con:
        con.execute(
            "INSERT INTO chat_logs(user_id, state, message, reply, slots_json) VALUES (?,?,?,?,?)",
            (user_id, state, message, reply, slots_json),
        )
        con.commit()

def fetch_logs(user_id: str, limit: int = 20):
    with get_con() as con:
        cur = con.execute(
            "SELECT ts, state, message, reply, slots_json FROM chat_logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()
