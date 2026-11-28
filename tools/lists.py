"""To-do, shopping and any other named list (Tier 0: SQLite only)."""
import re

from rapidfuzz import fuzz, process

from backend.database import connect, now

ALIASES = {"todo": "to-do", "to do": "to-do", "to-do": "to-do", "tasks": "to-do", "task": "to-do", "todos": "to-do",
           "shopping": "shopping", "grocery": "shopping", "groceries": "shopping", "shopping list": "shopping"}


def _list_name(name: str) -> str:
    n = re.sub(r"^(my|the)\s+", "", (name or "").strip().lower())
    n = re.sub(r"\s+list$", "", n).strip()
    return ALIASES.get(n, n) or "to-do"


def _split_items(item: str) -> list[str]:
    parts = re.split(r",|\band\b|&", item or "")
    return [re.sub(r"^(some|a|an|the)\s+", "", p.strip(" .!?").lower()) for p in parts if p.strip(" .!?")]


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _items(name):
    with connect() as conn:
        return [r["item"] for r in conn.execute("SELECT item FROM list_items WHERE list_name = ? ORDER BY id", (name,))]


def manage_list(action: str, list_name: str = "to-do", item: str = "") -> str:
    name = _list_name(list_name)
    if action == "show":
        items = _items(name)
        if not items:
            return f"Your {name} list is empty."
        shown = _join(items) if len(items) <= 10 else ", ".join(items[:10]) + f", and {len(items) - 10} more"
        return f"Your {name} list has {len(items)} item{'s' if len(items) != 1 else ''}: {shown}."
    if action == "clear":
        with connect() as conn:
            n = conn.execute("DELETE FROM list_items WHERE list_name = ?", (name,)).rowcount
        return f"Cleared your {name} list ({n} items)." if n else f"Your {name} list was already empty."
    new = _split_items(item)
    if not new:
        return "Which item?"
    if action == "add":
        with connect() as conn:
            added = [i for i in new if conn.execute(
                "INSERT OR IGNORE INTO list_items (list_name, item, created_at) VALUES (?,?,?)",
                (name, i, now())).rowcount]
        if not added:
            return f"{_join(new).capitalize()} {'is' if len(new) == 1 else 'are'} already on your {name} list."
        return f"Added {_join(added)} to your {name} list."
    if action == "remove":
        current = _items(name)
        removed = []
        for i in new:
            m = process.extractOne(i, current, scorer=fuzz.WRatio) if current else None
            if m and m[1] >= 70:
                with connect() as conn:
                    conn.execute("DELETE FROM list_items WHERE list_name = ? AND item = ?", (name, m[0]))
                removed.append(m[0]); current.remove(m[0])
        return f"Removed {_join(removed)} from your {name} list." if removed else \
            f"I couldn't find that on your {name} list."
    return "I can't do that with lists."


def list_summary() -> list[str]:
    """'3 things on your to-do list' style lines for routines."""
    with connect() as conn:
        rows = conn.execute("SELECT list_name, COUNT(*) n FROM list_items GROUP BY list_name").fetchall()
    return [f"{r['n']} thing{'s' if r['n'] != 1 else ''} on your {r['list_name']} list" for r in rows]
