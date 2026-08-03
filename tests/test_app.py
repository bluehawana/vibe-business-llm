"""Unit tests for the full Vibe Business chain.

The LLM is mocked so tests are deterministic and free — what we verify here is
the platform contract: spec → rendered site → cart → checkout → order → webhook.
The one thing these tests can't cover is Claude's actual output quality; that
needs the live A/B run with an API key.
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import auth, db, llm, main, stripe_pay
from app.schema import DEFAULT_SPEC, find_menu_item

client = TestClient(main.app)
# A guest's browser — never logged in. Used to prove the staff screens are shut.
guest = TestClient(main.app)


@pytest.fixture(autouse=True)
def demo_payments(monkeypatch):
    """Tests run against the demo payment stub unless a test overrides it."""
    monkeypatch.setattr(stripe_pay, "DEMO_PAYMENTS", True)


@pytest.fixture(autouse=True)
def staff_session():
    """Most tests exercise staff screens, so `client` stays logged in."""
    client.cookies.set(auth.COOKIE, auth.session_token())


def signed_webhook(payload: str, secret: str) -> dict:
    """A real Stripe signature header, so webhook tests go through the same
    verification path production does instead of around it."""
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={ts},v1={sig}"}


def printed(project_id, **params):
    """The printer authenticates with its own key, not a staff cookie."""
    params.setdefault("key", auth.printer_key())
    return params


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
                 "min_order_for_delivery": 200, "dine_in": False,
                 "pay_online": True, "pay_in_store": True},
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


def order_id_of(response):
    """Both lanes redirect with ?order=<id>; real Stripe redirects to its own URL."""
    url = response.json()["url"]
    return url.split("order=")[1].split("&")[0] if "order=" in url else url.rsplit("/", 1)[1]


# ---------- schema ----------

def test_find_menu_item():
    assert find_menu_item(SPEC, "margherita")["price"] == 119
    assert find_menu_item(SPEC, "nope") is None


# ---------- site rendering ----------

def test_site_renders_from_spec(project_id):
    html = client.get(f"/site/{project_id}").text
    assert "Testkrogen" in html
    assert "Margherita" in html and "119" in html
    assert "Ta med" in html  # Swedish because spec.language == sv
    assert "Hur vill du ha din mat?" in html  # eat-here/take-away asked up front


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
    assert "Kitchen" in client.get(f"/kitchen/{project_id}").text


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
    """Simulate the REAL Stripe flow for the online (takeaway) lane: order
    created 'pending', kitchen sees nothing until the payment webhook fires."""
    # pretend real Stripe is active: create a pending order + fake the redirect
    monkeypatch.setattr(stripe_pay, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(stripe_pay, "create_checkout_session",
                        lambda pid, oid, li, cur: f"https://stripe.test/{oid}")
    r = checkout(project_id, mode="pickup")  # online lane
    assert r.status_code == 200
    order_id = r.json()["url"].rsplit("/", 1)[1]

    # BEFORE payment: pending, and absent from the kitchen board
    assert db.get_order(order_id)["status"] == "pending"
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert all(o["id"] != order_id for o in board)

    # Stripe confirms payment via a SIGNED webhook -> paid -> the kitchen cooks
    monkeypatch.setattr(stripe_pay, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    # "object": "event" is part of every real Stripe event; the SDK reads it to
    # tell v1 from v2 events, so a fixture without it never reaches our code.
    payload = json.dumps({"object": "event", "type": "checkout.session.completed",
                          "data": {"object": {"metadata": {"order_id": order_id}}}})
    assert client.post("/api/stripe/webhook", content=payload,
                       headers=signed_webhook(payload, "whsec_test")).status_code == 200
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
    r = checkout(project_id, mode="dine_in", table="12", payment="in_store")
    order_id = order_id_of(r)

    # printer polls -> job ready
    poll = client.post(f"/api/cloudprnt/{project_id}", params=printed(project_id)).json()
    assert poll["jobReady"] is True
    assert poll["jobToken"] == order_id

    # printer fetches the job -> plain text with table + items
    job = client.get(f"/api/cloudprnt/{project_id}", params=printed(project_id))
    assert job.status_code == 200
    assert "Table:" in job.text and "12" in job.text
    assert "Margherita" in job.text
    assert "NOT PAID" in job.text  # settles on the Zettle reader

    # a kitchen-only printer gets the ticket without the guest's slip
    kitchen_only = client.get(f"/api/cloudprnt/{project_id}", params=printed(project_id, role="kitchen")).text
    assert "KÖK" in kitchen_only and "BESTÄLLNING" not in kitchen_only
    # eat-here food goes on a plate, so no bag label is printed for it
    assert "TAKE AWAY BAG" not in kitchen_only

    # printer confirms -> job no longer offered
    assert client.delete(f"/api/cloudprnt/{project_id}", params=printed(project_id, token=order_id)).status_code == 200
    assert client.post(f"/api/cloudprnt/{project_id}", params=printed(project_id)).json()["jobReady"] is False


def test_takeaway_prints_a_bag_label_with_number_and_name(project_id):
    """Reception hands bags over off the label alone — it must carry both."""
    r = checkout(project_id, mode="pickup", payment="in_store", kiosk=True,
                 customer_name="Yan")
    no = str(db.get_order(order_id_of(r))["order_no"])
    job = client.get(f"/api/cloudprnt/{project_id}", params=printed(project_id)).text
    assert "TAKE AWAY BAG" in job
    label = job.split("TAKE AWAY BAG")[1]
    assert no in label and "YAN" in label


def test_reception_screen_splits_tables_from_bags(project_id):
    html = client.get(f"/pass/{project_id}").text
    assert "Carry to the table" in html and "Bag it" in html


def test_receipt_page_renders(project_id):
    r = checkout(project_id)
    order_id = r.json()["url"].split("order=")[1].split("&")[0]
    html = client.get(f"/receipt/{order_id}").text
    assert "Guest slip" in html and "Kitchen ticket" in html and "TOTAL" in html


# ---------- in-store iPad kiosk ----------

def test_kiosk_mode_renders(project_id):
    html = client.get(f"/kiosk/{project_id}").text
    assert "Beställ här" in html  # kiosk banner


# ---------- kitchen station routing (hot line vs sushi bar) ----------

def _sushi_spec(pid):
    project = db.get_project(pid)
    project["spec"]["menu"] = [{"category": "Mat", "items": [
        {"id": "ramen", "name": "Ramen", "description": "", "price": 139, "station": "kitchen", "tags": []},
        {"id": "nigiri", "name": "Nigiri 8", "description": "", "price": 129, "station": "sushi", "tags": []},
        {"id": "cola", "name": "Cola", "description": "", "price": 25, "station": "bar", "tags": []},
    ]}]
    project["spec"]["services"]["dine_in"] = True
    db.update_spec(pid, project["spec"])


def test_station_routing_splits_order(project_id):
    _sushi_spec(project_id)
    r = checkout(project_id, mode="dine_in", table="3",
                 items=[{"id": "ramen", "qty": 1}, {"id": "nigiri", "qty": 2}, {"id": "cola", "qty": 1}])
    assert r.status_code == 200

    # sushi station sees only the nigiri
    sushi = client.get(f"/api/kitchen/{project_id}/orders?station=sushi").json()["orders"]
    assert len(sushi) == 1
    assert [i["id"] for i in sushi[0]["items"]] == ["nigiri"]

    # hot kitchen sees only the ramen
    kitchen = client.get(f"/api/kitchen/{project_id}/orders?station=kitchen").json()["orders"]
    assert [i["id"] for i in kitchen[0]["items"]] == ["ramen"]

    # bar sees only the cola
    bar = client.get(f"/api/kitchen/{project_id}/orders?station=bar").json()["orders"]
    assert [i["id"] for i in bar[0]["items"]] == ["cola"]

    # unstationed view (no param) sees the whole order
    allv = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert len(allv[0]["items"]) == 3


def test_station_with_no_items_hides_order(project_id):
    _sushi_spec(project_id)
    checkout(project_id, mode="dine_in", table="4", items=[{"id": "nigiri", "qty": 1}])
    # a sushi-only order must not appear on the hot-kitchen screen
    kitchen = client.get(f"/api/kitchen/{project_id}/orders?station=kitchen").json()["orders"]
    assert kitchen == []


def test_tv_display_renders(project_id):
    # the TV is the one screen every guest reads — both languages, always
    tv = client.get(f"/display/{project_id}").text
    assert "Tillagas" in tv and "Preparing" in tv
    assert "Klar" in tv and "Ready — collect your food" in tv


# ---------- one flow, two payment lanes, for eat-here AND take-away ----------

@pytest.mark.parametrize("mode,table", [("dine_in", "6"), ("pickup", "")])
def test_either_mode_can_pay_online(project_id, mode, table):
    """The point of the unified flow: eat-here and take-away both reach Stripe."""
    _enable_dine_in(project_id)
    r = checkout(project_id, mode=mode, table=table, payment="online")
    assert r.status_code == 200
    order = db.get_order(order_id_of(r))
    assert order["status"] == "paid"  # demo stub completes instantly
    assert order["customer"]["payment"] == "online"


@pytest.mark.parametrize("mode,table", [("dine_in", "6"), ("pickup", "")])
def test_either_mode_can_pay_on_the_zettle_reader(project_id, mode, table):
    _enable_dine_in(project_id)
    r = checkout(project_id, mode=mode, table=table, payment="in_store")
    assert r.status_code == 200
    assert "instore=1" in r.json()["url"]
    order_id = order_id_of(r)
    assert db.get_order(order_id)["status"] == "unpaid"

    # it queues on the counter screen with the amount to key into the reader
    unsettled = client.get(f"/api/counter/{project_id}/unsettled").json()["orders"]
    assert any(o["id"] == order_id for o in unsettled)

    # staff charges it on Zettle and taps "Betald" -> paid, and recorded as such
    assert client.post(f"/api/admin/{project_id}/orders/{order_id}/settle").status_code == 200
    settled = db.get_order(order_id)
    assert settled["status"] == "paid"
    assert settled["paid_via"] == "zettle"
    assert client.get(f"/api/counter/{project_id}/unsettled").json()["orders"] == []


def test_delivery_cannot_be_paid_in_store(project_id):
    """Nobody to hand a card reader to at a doorstep."""
    r = checkout(project_id, mode="delivery", address="Gata 1", payment="in_store",
                 items=[{"id": "carbonara", "qty": 2}])
    assert r.status_code == 400


def test_owner_can_switch_off_a_payment_lane(project_id):
    project = db.get_project(project_id)
    project["spec"]["services"]["pay_in_store"] = False
    db.update_spec(project_id, project["spec"])
    assert checkout(project_id, payment="in_store").status_code == 400
    assert checkout(project_id, payment="online").status_code == 200


def test_unknown_payment_method_rejected(project_id):
    assert checkout(project_id, payment="bitcoin").status_code == 400


# ---------- who gets cooked before the money lands ----------

def test_guest_in_the_restaurant_is_cooked_before_paying(project_id):
    """Standing at the counter iPad: the kitchen starts, they pay on the reader."""
    r = checkout(project_id, mode="pickup", payment="in_store", kiosk=True)
    order_id = order_id_of(r)
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert any(o["id"] == order_id for o in board)


def test_remote_pay_on_arrival_order_waits_for_payment(project_id):
    """Ordered from a phone, paying on arrival: a stranger who might turn up.
    Placed, queued for the reader, but the kitchen must not see it yet."""
    r = checkout(project_id, mode="pickup", payment="in_store")
    order_id = order_id_of(r)
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert all(o["id"] != order_id for o in board)
    assert client.post(f"/api/cloudprnt/{project_id}", params=printed(project_id)).json()["jobReady"] is False

    # once it's charged on the reader, the kitchen picks it up
    client.post(f"/api/admin/{project_id}/orders/{order_id}/settle")
    board2 = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert any(o["id"] == order_id for o in board2)


# ---------- order numbers (paper + TV) ----------

def test_order_numbers_are_sequential_per_restaurant(project_id):
    other = db.create_project("Grannen", json.loads(json.dumps(SPEC)))
    a = db.get_order(order_id_of(checkout(project_id)))
    b = db.get_order(order_id_of(checkout(project_id)))
    c = db.get_order(order_id_of(checkout(other)))

    assert a["order_no"] == db.FIRST_ORDER_NO
    assert b["order_no"] == db.FIRST_ORDER_NO + 1
    # a neighbouring restaurant has its own series, not a shared counter
    assert c["order_no"] == db.FIRST_ORDER_NO


def test_order_number_reaches_paper_screen_and_tv(project_id):
    _enable_dine_in(project_id)
    order_id = order_id_of(checkout(project_id, mode="dine_in", table="4",
                                    payment="in_store", kiosk=True))
    no = str(db.get_order(order_id)["order_no"])

    # the success screen the guest sees at the kiosk
    assert no in client.get(f"/site/{project_id}/success?order={order_id}&instore=1").text
    # the printable slip
    assert no in client.get(f"/receipt/{order_id}").text
    # the thermal printer job: guest slip AND kitchen ticket, both numbered
    job = client.get(f"/api/cloudprnt/{project_id}", params=printed(project_id)).text
    assert job.count(no) >= 2
    assert "BESTÄLLNING" in job and "KÖK" in job
    # the TV reads the number straight off the kitchen feed
    board = client.get(f"/api/kitchen/{project_id}/orders").json()["orders"]
    assert str(next(o["order_no"] for o in board if o["id"] == order_id)) == no


def test_in_store_slip_is_not_presented_as_a_vat_receipt(project_id):
    """Zettle is the certified register; our slip for those sales is an order
    ticket. It must not print a VAT breakdown as if it were the real receipt."""
    order_id = order_id_of(checkout(project_id, payment="in_store", kiosk=True))
    slip = client.get(f"/receipt/{order_id}").text
    assert "BESTÄLLNING" in slip and "BETALA I KORTTERMINALEN" in slip
    assert "moms" not in slip

    # a prepaid online order is a distance sale we account for ourselves
    paid_id = order_id_of(checkout(project_id, payment="online"))
    assert "moms" in client.get(f"/receipt/{paid_id}").text


# ---------- staff login (the screens that aren't for guests) ----------

STAFF_ONLY = ["/panel/{p}", "/kitchen/{p}", "/counter/{p}", "/pass/{p}", "/kiosk/{p}",
              "/builder/{p}", "/admin/{p}/orders", "/admin/{p}/customers"]
STAFF_APIS = ["/api/kitchen/{p}/orders", "/api/counter/{p}/unsettled"]


@pytest.mark.parametrize("path", STAFF_ONLY)
def test_staff_pages_redirect_a_stranger_to_login(project_id, path):
    r = guest.get(path.format(p=project_id), follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize("path", STAFF_APIS)
def test_staff_apis_reject_a_stranger(project_id, path):
    assert guest.get(path.format(p=project_id)).status_code == 401


def test_a_stranger_cannot_mark_an_order_paid(project_id):
    """The one that costs money: settling an order is free food if it's open."""
    order_id = order_id_of(checkout(project_id, payment="in_store", kiosk=True))
    assert guest.post(f"/api/admin/{project_id}/orders/{order_id}/settle").status_code == 401
    assert db.get_order(order_id)["status"] == "unpaid"


GUEST_OK = ["/site/{p}", "/site/{p}/success", "/display/{p}", "/"]


@pytest.mark.parametrize("path", GUEST_OK)
def test_guest_facing_pages_stay_open(project_id, path):
    assert guest.get(path.format(p=project_id)).status_code == 200


def test_guests_can_order_and_print_their_own_slip(project_id):
    """Ordering must never require a login — that is the whole product."""
    r = guest.post(f"/api/site/{project_id}/checkout", json={
        "items": [{"id": "margherita", "qty": 1}], "mode": "pickup"})
    assert r.status_code == 200
    assert guest.get(f"/receipt/{order_id_of(r)}").status_code == 200


def test_login_round_trip(project_id):
    fresh = TestClient(main.app)
    assert fresh.post("/login", data={"password": "wrong", "next": f"/panel/{project_id}"},
                      follow_redirects=False).headers["location"].endswith("bad=1")
    assert fresh.get(f"/panel/{project_id}", follow_redirects=False).status_code == 307

    ok = fresh.post("/login", data={"password": "test-staff-pw", "next": f"/panel/{project_id}"},
                    follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == f"/panel/{project_id}"
    assert fresh.get(f"/panel/{project_id}").status_code == 200

    fresh.get("/logout")
    assert fresh.get(f"/panel/{project_id}", follow_redirects=False).status_code == 307


def test_printer_needs_its_own_key(project_id):
    checkout(project_id, payment="in_store", kiosk=True)
    assert guest.post(f"/api/cloudprnt/{project_id}").status_code == 401
    assert guest.get(f"/api/cloudprnt/{project_id}?key=guessed").status_code == 401
    # the real key works without any staff cookie, and rotates with the password
    ok = guest.post(f"/api/cloudprnt/{project_id}?key={auth.printer_key()}")
    assert ok.status_code == 200 and ok.json()["jobReady"] is True


def test_staff_screens_fail_closed_with_no_password(project_id, monkeypatch):
    """Better to be switched off than silently open behind a public URL."""
    monkeypatch.setattr(auth, "STAFF_PASSWORD", "")
    assert client.get(f"/panel/{project_id}").status_code == 503
    assert client.get(f"/api/kitchen/{project_id}/orders").status_code == 503
    # guests are unaffected — the shop keeps selling
    assert guest.get(f"/site/{project_id}").status_code == 200


def test_unsigned_webhook_refused_when_stripe_is_live(project_id, monkeypatch):
    """Without a signing secret the webhook is a free-food machine: forge a
    'paid' event and the kitchen cooks it. Live keys must refuse unsigned."""
    monkeypatch.setattr(stripe_pay, "DEMO_PAYMENTS", False)
    monkeypatch.setattr(stripe_pay, "STRIPE_SECRET_KEY", "sk_live_x")
    monkeypatch.setattr(stripe_pay, "STRIPE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(stripe_pay, "create_checkout_session",
                        lambda pid, oid, li, cur: f"https://stripe.test/{oid}")
    order_id = order_id_of(checkout(project_id, mode="pickup"))
    assert db.get_order(order_id)["status"] == "pending"

    forged = {"type": "checkout.session.completed",
              "data": {"object": {"metadata": {"order_id": order_id}}}}
    r = guest.post("/api/stripe/webhook", content=json.dumps(forged))
    assert r.status_code == 400
    assert db.get_order(order_id)["status"] == "pending"  # still not paid
