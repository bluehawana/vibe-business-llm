"""Zettle Purchase API integration (self-hosted app credentials).

What this buys: the counter flow loses its last manual step. Staff charges the
guest on the Zettle reader exactly as before — the sale lands in Zettle's
certified register as always — and within half a minute this poller sees the
purchase, matches it to the waiting order, and settles it. Nobody taps
"Paid on Zettle" any more; the counter screen simply clears itself.

Matching is deliberately conservative: exact amount, purchase made after the
order, each Zettle purchase spendable exactly once. Two same-priced unpaid
orders settle oldest-first — with equal amounts the pairing cannot be wrong in
any way that matters. Anything that doesn't match cleanly stays on the counter
screen for a human, which is the state we're in today anyway.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ZETTLE_CLIENT_ID = os.environ.get("ZETTLE_CLIENT_ID", "")
ZETTLE_API_KEY = os.environ.get("ZETTLE_API_KEY", "")

TOKEN_URL = "https://oauth.zettle.com/token"
PURCHASES_URL = "https://purchase.izettle.com/purchases/v2"

# How far back we look for a matching purchase. Long enough for a busy counter,
# short enough that yesterday's sale can never claim today's order.
MATCH_WINDOW_S = 30 * 60
# Clock skew allowance: the purchase must not predate its order by more than this.
SKEW_S = 120


def enabled() -> bool:
    return bool(ZETTLE_CLIENT_ID and ZETTLE_API_KEY)


_token: dict = {"value": "", "expires": 0.0}


def _access_token() -> str:
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "client_id": ZETTLE_CLIENT_ID,
        "assertion": ZETTLE_API_KEY,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 7200))
    return _token["value"]


def _parse_ts(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def recent_purchases() -> list[dict]:
    """Card purchases from the reader, newest first:
    [{uuid, amount_minor, currency, ts}]."""
    req = urllib.request.Request(
        f"{PURCHASES_URL}?descending=true&limit=50",
        headers={"Authorization": f"Bearer {_access_token()}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    now = time.time()
    out = []
    for p in data.get("purchases", []):
        try:
            ts = _parse_ts(p["timestamp"])
        except (KeyError, ValueError):
            continue
        if now - ts > MATCH_WINDOW_S:
            continue
        out.append({"uuid": p.get("purchaseUUID") or p.get("purchaseUUID1"),
                    "amount_minor": int(p.get("amount", 0)),
                    "currency": (p.get("currency") or "").upper(),
                    "ts": ts})
    return out


def auto_settle(db) -> int:
    """Match fresh Zettle purchases to unpaid orders. Returns how many settled."""
    orders = db.get_unsettled_orders_all()
    if not orders:
        return 0
    purchases = recent_purchases()
    if not purchases:
        return 0

    used = {u for u in db.get_used_zettle_purchase_uuids() if u}
    settled = 0
    # Oldest orders claim purchases first.
    for order in sorted(orders, key=lambda o: o["created_at"]):
        want = int(round(order["total"] * 100))
        candidates = [p for p in purchases
                      if p["uuid"] and p["uuid"] not in used
                      and p["amount_minor"] == want
                      and p["currency"] == order["currency"].upper()
                      and p["ts"] >= order["created_at"] - SKEW_S]
        if not candidates:
            continue
        match = min(candidates, key=lambda p: p["ts"])
        db.settle_order_from_zettle(order["id"], match["uuid"])
        used.add(match["uuid"])
        settled += 1
    return settled
