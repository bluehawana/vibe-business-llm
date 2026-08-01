import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "vibe.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            spec TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            items TEXT NOT NULL,
            customer TEXT NOT NULL,
            total REAL NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            stripe_session_id TEXT,
            created_at REAL NOT NULL
        );
        """)
        # fulfillment: new -> preparing -> ready -> completed (kitchen display flow)
        for col, ddl in [
            ("fulfillment", "ALTER TABLE orders ADD COLUMN fulfillment TEXT NOT NULL DEFAULT 'new'"),
            # printed: has this order's kitchen ticket been sent to a thermal printer yet
            ("printed", "ALTER TABLE orders ADD COLUMN printed INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists


def create_project(name: str, spec: dict) -> str:
    project_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, spec, created_at) VALUES (?, ?, ?, ?)",
            (project_id, name, json.dumps(spec, ensure_ascii=False), time.time()),
        )
    return project_id


def get_project(project_id: str):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "spec": json.loads(row["spec"])}


def update_spec(project_id: str, spec: dict):
    with _connect() as conn:
        conn.execute(
            "UPDATE projects SET spec = ? WHERE id = ?",
            (json.dumps(spec, ensure_ascii=False), project_id),
        )


def add_message(project_id: str, role: str, content: str):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (project_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (project_id, role, content, time.time()),
        )


def get_messages(project_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE project_id = ? ORDER BY id",
            (project_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def create_order(project_id: str, items: list, customer: dict, total: float,
                 currency: str, status: str, stripe_session_id: str | None = None) -> str:
    order_id = uuid.uuid4().hex[:10]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO orders (id, project_id, items, customer, total, currency, status, stripe_session_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, project_id, json.dumps(items, ensure_ascii=False),
             json.dumps(customer, ensure_ascii=False), total, currency, status,
             stripe_session_id, time.time()),
        )
    return order_id


def mark_order_paid(order_id: str):
    with _connect() as conn:
        conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))


FULFILLMENT_STATES = ("new", "preparing", "ready", "completed")


def set_fulfillment(order_id: str, state: str):
    if state not in FULFILLMENT_STATES:
        raise ValueError(f"invalid fulfillment state: {state}")
    with _connect() as conn:
        conn.execute("UPDATE orders SET fulfillment = ? WHERE id = ?", (state, order_id))


def get_active_orders(project_id: str) -> list[dict]:
    """What the kitchen display shows: prepaid online orders (status 'paid') plus
    dine-in orders being settled in-store on Zettle (status 'in_store') — the
    latter are cooked immediately because the guest is seated."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE project_id = ? AND status IN ('paid', 'in_store')"
            " AND fulfillment != 'completed' ORDER BY created_at",
            (project_id,),
        ).fetchall()
    return [_order_dict(r) for r in rows]


def get_unsettled_orders(project_id: str) -> list[dict]:
    """Dine-in orders awaiting payment at the counter (settle on Zettle)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE project_id = ? AND status = 'in_store' ORDER BY created_at",
            (project_id,),
        ).fetchall()
    return [_order_dict(r) for r in rows]


def get_next_unprinted_order(project_id: str):
    """Oldest active order whose kitchen ticket hasn't printed yet (Star CloudPRNT).
    Covers prepaid online orders and in-store dine-in orders alike."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE project_id = ? AND status IN ('paid', 'in_store')"
            " AND printed = 0 ORDER BY created_at LIMIT 1",
            (project_id,),
        ).fetchone()
    return _order_dict(row) if row else None


def mark_order_printed(order_id: str):
    with _connect() as conn:
        conn.execute("UPDATE orders SET printed = 1 WHERE id = ?", (order_id,))


def get_customers(project_id: str) -> list[dict]:
    """CRM: aggregate paid orders by phone number into a repeat-customer view."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM orders WHERE project_id = ? AND status = 'paid'",
                            (project_id,)).fetchall()
    by_phone: dict[str, dict] = {}
    for row in rows:
        o = _order_dict(row)
        phone = (o["customer"].get("phone") or "").strip() or "—"
        c = by_phone.setdefault(phone, {
            "phone": phone, "name": o["customer"].get("name", ""),
            "orders": 0, "total_spent": 0.0, "last_order": 0.0,
            "currency": o["currency"],
        })
        c["orders"] += 1
        c["total_spent"] += o["total"]
        c["last_order"] = max(c["last_order"], o["created_at"])
        if o["created_at"] >= c["last_order"]:
            c["name"] = o["customer"].get("name", "") or c["name"]
    return sorted(by_phone.values(), key=lambda c: c["total_spent"], reverse=True)


def get_order(order_id: str):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return _order_dict(row) if row else None


def get_orders(project_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    return [_order_dict(r) for r in rows]


def _order_dict(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "items": json.loads(row["items"]),
        "customer": json.loads(row["customer"]),
        "total": row["total"],
        "currency": row["currency"],
        "status": row["status"],
        "fulfillment": row["fulfillment"] if "fulfillment" in keys else "new",
        "printed": bool(row["printed"]) if "printed" in keys else False,
        "created_at": row["created_at"],
    }
