"""Print Momo's stored conversations.

    python scripts/show_convos.py            # list sessions
    python scripts/show_convos.py <id|last>  # show one session's messages
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "memory.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

if len(sys.argv) == 1:
    for r in conn.execute(
        "SELECT s.session_id, s.started_at, COUNT(m.id) AS n FROM sessions s "
        "LEFT JOIN messages m USING(session_id) GROUP BY s.session_id ORDER BY s.started_at"
    ):
        print(f"{r['session_id']}  {r['started_at']}  {r['n']} messages")
else:
    sid = sys.argv[1]
    if sid == "last":
        sid = conn.execute("SELECT session_id FROM messages ORDER BY id DESC LIMIT 1").fetchone()[0]
    for r in conn.execute(
        "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id", (sid,)
    ):
        print(f"[{r['created_at']}] {r['role']:>9}: {r['content']}")
