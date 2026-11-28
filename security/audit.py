"""Security log: every blocked request, dropped injection, email draft, approval and rejection.

Stored in the `security_events` table of data/memory.db and printed to the terminal.
"""
from backend.database import connect, now


def log_event(kind: str, detail: str = "") -> None:
    print(f"[security] {kind}: {detail}", flush=True)
    try:
        with connect() as conn:
            conn.execute("INSERT INTO security_events (kind, detail, created_at) VALUES (?, ?, ?)",
                         (kind, detail[:500], now()))
    except Exception as e:  # logging must never break Momo
        print(f"[security] could not log: {e}")


def recent_events(limit: int = 20) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT kind, detail, created_at FROM security_events ORDER BY id DESC LIMIT ?", (limit,))]
