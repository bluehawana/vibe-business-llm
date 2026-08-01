"""Unit tests for the full Vibe Business chain.

The LLM is mocked so tests are deterministic and free — what we verify here is
the platform contract: spec → rendered site → cart → checkout → order → webhook.
The one thing these tests can't cover is Claude's actual output quality; that
needs the live A/B run with an API key.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import db, llm, main, stripe_pay
from app.schema import DEFAULT_SPEC, find_menu_item

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def demo_payments(monkeypatch):
    """Tests run against the demo payment stub unless a test overrides it."""
    monkeypatch.setattr(stripe_pay, "DEMO_PAYMENTS", True)


SPEC = json.loads(json.dumps(DEFAULT_SPEC))
SPEC.update({
    "business_name": "Testkrogen",
    "language": "sv",
    "currency": "SEK",
    "hero": {"headline": "Välkommen", "subheadline": "Test", "emoji": "🍕"},
    "menu": [{"category": "Pizza", "items": [
        {"id": "margherita", "name": "Margherita", "description": "Tomat, mozzarella",
         "price": 119, "tags": ["vegetarian"]},
        {"id": "carbonara", "name": "Carbonara", "description": "Pasta", "price": 149, "tags": []},
    ]}],
    "services": {"pickup": True, "delivery": True, "delivery_fee": 45,
                 "min_order_for_delivery": 200},
})


@pytest.fixture
def project_id():
    return db.create_project("Testkrogen", json.loads(json.dumps(SPEC)))


def checkout(pid, **overrides):
    body = {
        "items": [{"id": "margherita", "qty": 2}],
        "customer_name": "Anna", "customer_phone": "0701112233",
        "mode": "pickup", "address": "",
    }
    body.update(overrides)
    return client.post(f"/api/site/{pid}/checkout", json=body)


# ---------- schema ----------

def test_find_menu_item():
    assert find_menu_item(SPEC, "margherita")["price"] == 119
    assert find_menu_item(SPEC, "nope") is None


# ---------- site rendering ----------

def test_site_renders_from_spec(project_id):
    html = client.get(f"/site/{project_id}").text
    assert "Testkrogen" in html
    assert "Margherita" in html and "119" in html
    assert "Avhämtning" in html  # Swedish because spec.language == sv


def test_unknown_project_404():
    assert client.get("/site/doesnotexist").status_code == 404


# ---------- checkout: price integrity ----------

def test_checkout_uses_server_prices_not_client(project_id):
    """Client can only send item ids and quantities — totals come from the spec.
    A tampered price field must be ignored (Pydantic drops unknown fields)."""
    r = client.post(f"/api/site/{project_id}/checkout", json={
        "items": [{"id": "margherita", "qty": 1, "price": 0.01}],  # tampering attempt
        "customer_name": "Evil", "customer_phone": "1", "mode": "pickup", "address": "",
    })
    assert r.status_code == 200
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    assert db.get_order(order_id)["total"] == 119  # spec price, not 0.01


def test_checkout_totals_and_demo_paid(project_id):
    r = checkout(project_id)  # 2 × 119 pickup
    assert r.status_code == 200
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    order = db.get_order(order_id)
    assert order["total"] == 238
    assert order["status"] == "paid"  # demo mode completes instantly
    assert order["currency"] == "SEK"


def test_delivery_fee_added(project_id):
    r = checkout(project_id, items=[{"id": "carbonara", "qty": 2}], mode="delivery",
                 address="Gata 1")
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    order = db.get_order(order_id)
    assert order["total"] == 2 * 149 + 45
    assert any(i["id"] == "_delivery" for i in order["items"])


def test_min_order_for_delivery_rejected(project_id):
    r = checkout(project_id, items=[{"id": "margherita", "qty": 1}], mode="delivery",
                 address="Gata 1")  # 119 < 200
    assert r.status_code == 400
    assert "200" in r.json()["detail"]


def test_unknown_item_rejected(project_id):
    r = checkout(project_id, items=[{"id": "hacked-item", "qty": 1}])
    assert r.status_code == 400


def test_empty_cart_rejected(project_id):
    r = checkout(project_id, items=[])
    assert r.status_code == 400


def test_disabled_service_rejected(project_id):
    project = db.get_project(project_id)
    project["spec"]["services"]["delivery"] = False
    db.update_spec(project_id, project["spec"])
    r = checkout(project_id, mode="delivery", address="Gata 1")
    assert r.status_code == 400


# ---------- stripe webhook (unsigned demo parse) ----------

def test_webhook_marks_order_paid(project_id):
    order_id = db.create_order(project_id, [{"id": "margherita", "name": "M",
                               "price": 119, "qty": 1}], {"name": "A", "phone": "1",
                               "mode": "pickup", "address": ""}, 119, "SEK", "pending")
    payload = {"type": "checkout.session.completed",
               "data": {"object": {"metadata": {"order_id": order_id}}}}
    r = client.post("/api/stripe/webhook", content=json.dumps(payload))
    assert r.status_code == 200
    assert db.get_order(order_id)["status"] == "paid"


# ---------- builder chain with mocked LLM ----------

def test_create_project_and_chat_with_mocked_llm(monkeypatch):
    def fake_chat_update(history, site, message):
        spec = json.loads(json.dumps(SPEC))
        if "tiramisu" in message.lower():
            spec["menu"].append({"category": "Dessert", "items": [
                {"id": "tiramisu", "name": "Tiramisu", "description": "Hemgjord",
                 "price": 89, "tags": []}]})
        return "Klart! Jag har uppdaterat sidan.", spec

    monkeypatch.setattr(llm, "chat_update", fake_chat_update)

    r = client.post("/api/projects", json={"name": "Mockkrogen",
                                           "description": "italiensk restaurang"})
    assert r.status_code == 200
    pid = r.json()["project_id"]

    r2 = client.post(f"/api/projects/{pid}/chat",
                     json={"message": "Lägg till tiramisu för 89 kr"})
    assert r2.status_code == 200

    # the chat turn must be reflected on the live site immediately
    html = client.get(f"/site/{pid}").text
    assert "Tiramisu" in html and "89" in html
    # and chat history persisted
    assert len(db.get_messages(pid)) == 4  # 2 turns × (user + assistant)


# ---------- pages ----------

def test_success_and_orders_pages(project_id):
    r = checkout(project_id)
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    assert "Tack" in client.get(f"/site/{project_id}/success?order={order_id}&demo=1").text
    assert order_id in client.get(f"/admin/{project_id}/orders").text


# ---------- in-store-only items (tobacco/snus legal guardrail) ----------

def test_in_store_only_item_not_orderable(project_id):
    project = db.get_project(project_id)
    project["spec"]["menu"].append({"category": "Tobak", "items": [
        {"id": "snus-general", "name": "Snus", "description": "18+",
         "price": 55, "tags": ["in-store-only"]}]})
    db.update_spec(project_id, project["spec"])
    # displayed on the site without an order button
    html = client.get(f"/site/{project_id}").text
    assert "Snus" in html and "Endast i butik" in html
    # but ordering it online is rejected server-side
    r = checkout(project_id, items=[{"id": "snus-general", "qty": 1}])
    assert r.status_code == 400


# ---------- dine-in mode + kitchen display ----------

def _enable_dine_in(pid):
    project = db.get_project(pid)
    project["spec"]["services"]["dine_in"] = True
    db.update_spec(pid, project["spec"])


def test_dine_in_requires_table(project_id):
    _enable_dine_in(project_id)
    r = checkout(project_id, mode="dine_in", table="")
    assert r.status_code == 400
    r2 = checkout(project_id, mode="dine_in", table="5")
    assert r2.status_code == 200


def test_dine_in_rejected_when_disabled(project_id):
    r = checkout(project_id, mode="dine_in", table="5")  # default spec: dine_in off
    assert r.status_code == 400


def test_kitchen_flow(project_id):
    _enable_dine_in(project_id)
    r = checkout(project_id, mode="dine_in", table="7")
    order_id = r.json()["url"].split("order=")[1].split("&")[0]

    # order shows on the kitchen board as "new" with its table number
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    mine = next(o for o in board if o["id"] == order_id)
    assert mine["fulfillment"] == "new"
    assert mine["customer"]["table"] == "7"

    # kitchen advances it: preparing -> ready -> completed
    for state in ("preparing", "ready", "completed"):
        rs = client.post(f"/api/kitchen/{project_id}/orders/{order_id}/status",
                         json={"state": state})
        assert rs.status_code == 200

    # completed orders leave the board
    board2 = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert all(o["id"] != order_id for o in board2)

    # invalid state rejected
    rbad = client.post(f"/api/kitchen/{project_id}/orders/{order_id}/status",
                       json={"state": "burnt"})
    assert rbad.status_code == 400


def test_kitchen_page_renders(project_id):
    assert "kök" in client.get(f"/kitchen/{project_id}").text


# ---------- pickup time (tourist pre-order use case) ----------

def test_pickup_time_stored_and_defaults_asap(project_id):
    r = checkout(project_id, pickup_time="18:30")
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    assert db.get_order(order_id)["customer"]["pickup_time"] == "18:30"

    r2 = checkout(project_id)  # no time given
    order_id2 = r2.json()["url"].split("order=")[1].split("&")[0]
    assert db.get_order(order_id2)["customer"]["pickup_time"] == "ASAP"


# ---------- prepayment is mandatory (the core guarantee) ----------

def test_checkout_blocked_when_payments_not_configured(project_id, monkeypatch):
    """No Stripe key and no demo flag -> checkout must refuse. An order is never
    accepted without prepayment."""
    monkeypatch.setattr(stripe_pay, "DEMO_PAYMENTS", False)
    monkeypatch.setattr(stripe_pay, "STRIPE_SECRET_KEY", "")
    r = checkout(project_id)
    assert r.status_code == 503


def test_unpaid_order_never_reaches_kitchen(project_id, monkeypatch):
    """Simulate the REAL Stripe flow: order created 'pending', kitchen sees
    nothing; only after the payment webhook does it appear on the board."""
    _enable_dine_in(project_id)
    # pretend real Stripe is active: create a pending order + fake the redirect
    monkeypatch.setattr(stripe_pay, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(stripe_pay, "create_checkout_session",
                        lambda pid, oid, li, cur: f"https://stripe.test/{oid}")
    r = checkout(project_id, mode="dine_in", table="9")
    assert r.status_code == 200
    order_id = r.json()["url"].rsplit("/", 1)[1]

    # BEFORE payment: pending, and absent from the kitchen board
    assert db.get_order(order_id)["status"] == "pending"
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert all(o["id"] != order_id for o in board)

    # Stripe confirms payment via webhook -> now paid -> now the kitchen cooks
    payload = {"type": "checkout.session.completed",
               "data": {"object": {"metadata": {"order_id": order_id}}}}
    assert client.post("/api/stripe/webhook", content=json.dumps(payload)).status_code == 200
    assert db.get_order(order_id)["status"] == "paid"
    board2 = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert any(o["id"] == order_id for o in board2)


def test_site_hides_pay_button_when_payments_not_configured(project_id, monkeypatch):
    monkeypatch.setattr(stripe_pay, "DEMO_PAYMENTS", False)
    monkeypatch.setattr(stripe_pay, "STRIPE_SECRET_KEY", "")
    html = client.get(f"/site/{project_id}").text
    assert "inte aktiverad" in html  # "not enabled yet" notice, no pay button


# ---------- CRM (repeat customers) ----------

def test_crm_aggregates_by_phone(project_id):
    # same phone orders twice, another phone once
    checkout(project_id, customer_phone="0700000001", customer_name="Sara")
    checkout(project_id, customer_phone="0700000001", customer_name="Sara",
             items=[{"id": "carbonara", "qty": 1}])
    checkout(project_id, customer_phone="0700000002", customer_name="Ali")

    customers = db.get_customers(project_id)
    by_phone = {c["phone"]: c for c in customers}
    assert by_phone["0700000001"]["orders"] == 2
    assert by_phone["0700000001"]["total_spent"] == 238 + 149
    assert by_phone["0700000002"]["orders"] == 1
    # sorted by spend desc -> the 2-order customer is first
    assert customers[0]["phone"] == "0700000001"
    # page renders
    assert "0700000001" in client.get(f"/admin/{project_id}/customers").text


# ---------- Star CloudPRNT (thermal kitchen printer) ----------

def test_cloudprnt_poll_serve_confirm(project_id):
    _enable_dine_in(project_id)
    r = checkout(project_id, mode="dine_in", table="12")
    order_id = r.json()["url"].split("order=")[1].split("&")[0]

    # printer polls -> job ready
    poll = client.post(f"/api/cloudprnt/{project_id}").json()
    assert poll["jobReady"] is True
    assert poll["jobToken"] == order_id

    # printer fetches the ticket -> plain text with table + items + PAID
    job = client.get(f"/api/cloudprnt/{project_id}")
    assert job.status_code == 200
    assert "Bord:" in job.text and "12" in job.text
    assert "Margherita" in job.text and "BETALD" in job.text

    # printer confirms -> job no longer offered
    assert client.delete(f"/api/cloudprnt/{project_id}?token={order_id}").status_code == 200
    assert client.post(f"/api/cloudprnt/{project_id}").json()["jobReady"] is False


def test_receipt_page_renders(project_id):
    r = checkout(project_id)
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    html = client.get(f"/receipt/{order_id}").text
    assert "Kundkvitto" in html and "Köksbong" in html and "SUMMA" in html


# ---------- in-store iPad kiosk ----------

def test_kiosk_mode_renders(project_id):
    html = client.get(f"/kiosk/{project_id}").text
    assert "Beställ här" in html  # kiosk banner
