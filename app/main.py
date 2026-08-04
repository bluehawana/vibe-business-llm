import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import auth, db, llm, receipt, stripe_pay
from .schema import DEFAULT_SPEC, find_menu_item

app = FastAPI(title="Vibe Business")
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# A single-restaurant install serves that restaurant at "/" instead of the
# platform landing page. Empty = multi-tenant, as before.
HOME_PROJECT = os.environ.get("VIBE_HOME_PROJECT", "")

db.init_db()


def require_staff(request: Request):
    """Guards everything that isn't for guests. Public by design and deliberately
    left open: the guest site, the success page, the printable slip (its order id
    is unguessable), and the TV board, which shows nothing but order numbers and
    has no keyboard to log in from."""
    if not auth.configured():
        raise HTTPException(503, "Set VIBE_STAFF_PASSWORD in .env to use the staff screens")
    if auth.valid_session(request.cookies.get(auth.COOKIE)):
        return
    if request.url.path.startswith("/api/"):
        raise HTTPException(401, "Staff login required")
    raise HTTPException(307, "Staff login required",
                        headers={"Location": f"/login?next={quote(request.url.path)}"})


STAFF = [Depends(require_staff)]


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", bad: str = ""):
    return templates.TemplateResponse(request, "login.html", {
        "next": next, "bad": bool(bad), "configured": auth.configured(),
    })


@app.post("/login")
def login(next: str = Form("/"), password: str = Form("")):
    if not auth.check_password(password):
        return RedirectResponse(f"/login?next={quote(next)}&bad=1", status_code=303)
    response = RedirectResponse(next or "/", status_code=303)
    response.set_cookie(auth.COOKIE, auth.session_token(), max_age=auth.COOKIE_MAX_AGE,
                        httponly=True, samesite="lax")
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE)
    return response


class CreateProject(BaseModel):
    name: str
    description: str


class ChatMessage(BaseModel):
    message: str


class CartItem(BaseModel):
    id: str
    qty: int


class CheckoutRequest(BaseModel):
    items: list[CartItem]
    customer_name: str = ""
    customer_phone: str = ""
    mode: str  # "pickup" | "delivery" | "dine_in"
    address: str = ""
    table: str = ""  # dine_in: table number from QR code / in-store iPad
    pickup_time: str = ""  # pickup/delivery: requested time, e.g. "18:30" or "ASAP"
    payment: str = ""  # "online" (Stripe) | "in_store" (Zettle card reader)
    kiosk: bool = False  # placed on the restaurant's own iPad, guest standing there


class FulfillmentUpdate(BaseModel):
    state: str  # new | preparing | ready | completed


def _project_or_404(project_id: str) -> dict:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


# ---------- Builder ----------

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    """On a shop's own domain, "/" should be that shop's menu — order.ichiban.biz
    is what goes on a QR code and in an Instagram bio, not a project id nobody
    can read out loud. Unset, this stays the platform landing page."""
    if HOME_PROJECT and db.get_project(HOME_PROJECT):
        return RedirectResponse(f"/site/{HOME_PROJECT}", status_code=307)
    return templates.TemplateResponse(request, "landing.html", {})


@app.post("/api/projects", dependencies=STAFF)
def create_project(body: CreateProject):
    seed = (
        "Create the first version of my website. Here is my business:\n"
        f"Name: {body.name}\n"
        f"Description: {body.description}"
    )
    try:
        reply, spec = llm.chat_update([], DEFAULT_SPEC, seed)
    except llm.BuilderRefused as e:
        raise HTTPException(422, str(e))
    project_id = db.create_project(body.name, spec)
    db.add_message(project_id, "user", seed)
    db.add_message(project_id, "assistant", reply)
    return {"project_id": project_id, "reply": reply}


@app.get("/builder/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def builder(request: Request, project_id: str):
    project = _project_or_404(project_id)
    messages = db.get_messages(project_id)
    return templates.TemplateResponse(request, "builder.html", {
        "project": project,
        "messages": messages,
    })


@app.post("/api/projects/{project_id}/chat", dependencies=STAFF)
def chat(project_id: str, body: ChatMessage):
    project = _project_or_404(project_id)
    history = db.get_messages(project_id)
    try:
        reply, spec = llm.chat_update(history, project["spec"], body.message)
    except llm.BuilderRefused as e:
        raise HTTPException(422, str(e))
    db.update_spec(project_id, spec)
    db.add_message(project_id, "user", body.message)
    db.add_message(project_id, "assistant", reply)
    return {"reply": reply}


# ---------- Published site ----------

@app.get("/site/{project_id}", response_class=HTMLResponse)
def site(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "site.html", {
        "project_id": project_id,
        "spec": project["spec"],
        "spec_json": json.dumps(project["spec"], ensure_ascii=False),
        "payments_ready": stripe_pay.payments_configured(),
        "page_url": f"{stripe_pay.BASE_URL}/site/{project_id}",
    })


@app.post("/api/site/{project_id}/checkout")
def checkout(project_id: str, body: CheckoutRequest):
    project = _project_or_404(project_id)
    spec = project["spec"]
    services = spec.get("services", {})

    if body.mode == "delivery" and not services.get("delivery"):
        raise HTTPException(400, "Delivery is not offered")
    if body.mode == "pickup" and not services.get("pickup"):
        raise HTTPException(400, "Pickup is not offered")
    if body.mode == "dine_in":
        if not services.get("dine_in"):
            raise HTTPException(400, "Dine-in ordering is not offered")
        # A table number is how a waiter finds you. At the counter iPad there is
        # no waiter — the guest is called by order number, so no table needed.
        if not body.kiosk and not body.table.strip():
            raise HTTPException(400, "Table number is required for dine-in orders")

    line_items, order_items, total = [], [], 0.0
    for cart_item in body.items:
        if cart_item.qty < 1:
            continue
        menu_item = find_menu_item(spec, cart_item.id)
        if menu_item is None:
            raise HTTPException(400, f"Unknown menu item: {cart_item.id}")
        if "in-store-only" in menu_item.get("tags", []):
            raise HTTPException(400, f"{menu_item['name']} can only be bought in store")
        total += menu_item["price"] * cart_item.qty
        line_items.append({
            "name": menu_item["name"],
            "unit_amount_minor": int(round(menu_item["price"] * 100)),
            "quantity": cart_item.qty,
        })
        order_items.append({"id": cart_item.id, "name": menu_item["name"],
                            "price": menu_item["price"], "qty": cart_item.qty})

    if not order_items:
        raise HTTPException(400, "Cart is empty")

    if body.mode == "delivery":
        min_order = services.get("min_order_for_delivery", 0)
        if total < min_order:
            raise HTTPException(400, f"Minimum order for delivery is {min_order}")
        fee = services.get("delivery_fee", 0)
        if fee:
            total += fee
            line_items.append({"name": "Delivery", "unit_amount_minor": int(round(fee * 100)),
                               "quantity": 1})
            order_items.append({"id": "_delivery", "name": "Delivery", "price": fee, "qty": 1})

    customer = {"name": body.customer_name, "phone": body.customer_phone,
                "mode": body.mode, "address": body.address, "table": body.table,
                "pickup_time": body.pickup_time or "ASAP"}
    currency = spec.get("currency", "SEK")

    # The guest is standing in the restaurant: at a table (QR) or at the counter
    # iPad. That is what decides whether the kitchen may start before the money
    # lands — not whether it's eat-here or takeaway.
    serve_now = body.kiosk or body.mode == "dine_in"

    # One flow, two payment lanes — the guest picks, the same for every mode:
    #  - "online"   -> Stripe, taken at the moment of ordering. Nobody at a till.
    #  - "in_store" -> the Zettle card reader, which is the certified Swedish
    #    kassaregister. Zettle stays in the loop precisely so an on-premises card
    #    payment is registered where the law requires it.
    payment = body.payment or "online"
    if payment not in ("online", "in_store"):
        raise HTTPException(400, f"Unknown payment method: {payment}")

    # Delivery has nobody to hand a card reader to — it is always prepaid.
    if body.mode == "delivery" and payment != "online":
        raise HTTPException(400, "Delivery orders are paid online")
    if payment == "online" and not services.get("pay_online", True):
        raise HTTPException(400, "Online payment is not offered here")
    if payment == "in_store" and not services.get("pay_in_store", True):
        raise HTTPException(400, "Paying in the restaurant is not offered here")
    # A remote order that pays on arrival is just a stranger who might turn up —
    # let it be placed, but the kitchen won't see it until the reader confirms.
    customer["payment"] = payment

    if payment == "in_store":
        order_id = db.create_order(project_id, order_items, customer, total, currency,
                                   "unpaid", serve_now=serve_now)
        order = db.get_order(order_id)
        # The kiosk app drives a paired Zettle reader with exactly these fields —
        # amount from the server, never from anything the guest's browser computed.
        return {"url": f"/site/{project_id}/success?order={order_id}&instore=1",
                "order_id": order_id,
                "order_no": str(order["order_no"]),
                "amount_minor": int(round(total * 100)),
                "currency": currency}

    if not stripe_pay.payments_configured():
        raise HTTPException(503, "Online payments are not set up yet for this shop")

    if stripe_pay.stripe_enabled():
        # Real Stripe: order stays 'pending' and is INVISIBLE to the kitchen
        # until Stripe's webhook confirms payment (see mark_order_paid).
        order_id = db.create_order(project_id, order_items, customer, total, currency,
                                   "pending", serve_now=serve_now)
        url = stripe_pay.create_checkout_session(project_id, order_id, line_items, currency)
        return {"url": url}

    # Local demo stub (VIBE_DEMO_PAYMENTS=1 only): simulates a successful payment
    # so the full chain can be tested without real Stripe keys.
    order_id = db.create_order(project_id, order_items, customer, total, currency,
                               "paid", serve_now=serve_now)
    db.mark_order_paid(order_id, paid_via="stripe")
    return {"url": f"/site/{project_id}/success?order={order_id}&demo=1"}


@app.get("/site/{project_id}/success", response_class=HTMLResponse)
def success(request: Request, project_id: str, order: str = "", demo: str = "", instore: str = ""):
    project = _project_or_404(project_id)
    order_data = db.get_order(order) if order else None
    return templates.TemplateResponse(request, "success.html", {
        "project_id": project_id,
        "instore": bool(instore),
        "spec": project["spec"],
        "order": order_data,
        "demo": bool(demo),
    })


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        order_id = stripe_pay.parse_webhook(payload, sig)
    except Exception:
        return JSONResponse({"error": "invalid signature"}, status_code=400)
    if order_id:
        db.mark_order_paid(order_id, paid_via="stripe")
    return {"ok": True}


# ---------- Kitchen display (KDS) ----------

@app.get("/kitchen/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def kitchen(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "kitchen.html", {
        "project": project,
    })


def _station_of(spec: dict) -> dict:
    """Map each menu item id -> its kitchen station (from the current spec)."""
    out = {}
    for cat in spec.get("menu", []):
        for it in cat.get("items", []):
            out[it["id"]] = it.get("station", "kitchen")
    return out


@app.get("/counter/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def counter(request: Request, project_id: str):
    """The Zettle hand-off screen: every order waiting to be charged, with the
    exact amount to key into the reader. Two taps, no till, and whoever is
    nearest can do it — a runner, a cook, nobody dedicated."""
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "counter.html", {"project": project})


@app.get("/pass/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def pass_screen(request: Request, project_id: str):
    """Reception iPad. No till any more, but somebody still has to carry plates
    to the right table and put the right food in the right bag — this screen
    answers only that, for orders the kitchen has marked ready."""
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "pass.html", {"project": project})


@app.get("/api/counter/{project_id}/unsettled", dependencies=STAFF)
def counter_unsettled(project_id: str):
    _project_or_404(project_id)
    return {"orders": db.get_unsettled_orders(project_id)}


@app.get("/api/kitchen/{project_id}/orders", dependencies=STAFF)
def kitchen_orders(project_id: str, station: str = ""):
    project = _project_or_404(project_id)
    orders = db.get_active_orders(project_id)
    if not station:
        return {"orders": orders}
    # Station routing: each station iPad sees only orders containing its items,
    # and only those items on the ticket. Unknown/unrouted items (e.g. legacy
    # menus with no station) show everywhere so nothing is silently dropped.
    station_of = _station_of(project["spec"])
    routed = []
    for o in orders:
        mine = [i for i in o["items"]
                if i["id"] != "_delivery"
                and station_of.get(i["id"], station) == station]
        if mine:
            routed.append({**o, "items": mine})
    return {"orders": routed}


@app.get("/api/display/{project_id}")
def display_board(project_id: str):
    """Public feed for the guest board — deliberately only what a room full of
    strangers may see: a number and whether it's cooking or ready. The staff feed
    carries names, phone numbers and addresses, which is why it needs a login and
    why the board must not simply reuse it."""
    _project_or_404(project_id)
    # Always a string, never sometimes-int: a typed client (the tvOS board)
    # cannot decode a field that changes shape between rows.
    return {"orders": [{"order_no": str(o["order_no"] or o["id"][:4].upper()),
                        "fulfillment": o["fulfillment"]}
                       for o in db.get_active_orders(project_id)]}


@app.get("/display/{project_id}", response_class=HTMLResponse)
def display(request: Request, project_id: str):
    """Customer-facing order-status board for a TV (open in Safari on Apple TV):
    shows order numbers moving from 'Tillagas' to 'Klar för avhämtning'."""
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "display.html", {"project": project})


@app.post("/api/kitchen/{project_id}/orders/{order_id}/status", dependencies=STAFF)
def kitchen_status(project_id: str, order_id: str, body: FulfillmentUpdate):
    _project_or_404(project_id)
    order = db.get_order(order_id)
    if order is None or order["project_id"] != project_id:
        raise HTTPException(404, "Order not found")
    try:
        db.set_fulfillment(order_id, body.state)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------- Restaurant control panel (the operational hub) ----------

@app.get("/panel/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def panel(request: Request, project_id: str):
    project = _project_or_404(project_id)
    stations = sorted({it.get("station", "kitchen")
                       for cat in project["spec"].get("menu", [])
                       for it in cat.get("items", [])})
    return templates.TemplateResponse(request, "panel.html", {
        "project": project,
        "stations": stations or ["kitchen"],
        "printer_key": auth.printer_key(),
    })


# ---------- In-store iPad kiosk ----------

@app.get("/kiosk/{project_id}", response_class=HTMLResponse, dependencies=STAFF)
def kiosk(request: Request, project_id: str):
    """Reception iPad in self-hosting mode: the guest orders and pays themselves,
    eat-here or takeaway, and walks away with a number. Same ordering UI as the
    public site — kiosk=True only changes framing and defaults."""
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "site.html", {
        "project_id": project_id,
        "spec": project["spec"],
        "spec_json": json.dumps(project["spec"], ensure_ascii=False),
        "payments_ready": stripe_pay.payments_configured(),
        "kiosk": True,
    })


# ---------- Star CloudPRNT (thermal receipt / kitchen printer) ----------
# A Star printer is configured to poll POST /api/cloudprnt/{project_id}. When a
# paid order is waiting, we tell it a job is ready; it GETs the ticket text and
# DELETEs to confirm. No local driver, no printer IP — cloud-native printing.

def require_printer(key: str = ""):
    """The printer polls a fixed URL and can't hold a cookie, so it carries its
    own key (shown on the control panel). Without it these endpoints would leak
    every order's contents to anyone who found the URL."""
    if not auth.configured():
        raise HTTPException(503, "Set VIBE_STAFF_PASSWORD in .env before printing")
    if not auth.valid_printer_key(key):
        raise HTTPException(401, "Bad printer key")


PRINTER = [Depends(require_printer)]


@app.post("/api/cloudprnt/{project_id}", dependencies=PRINTER)
async def cloudprnt_poll(project_id: str):
    _project_or_404(project_id)
    order = db.get_next_unprinted_order(project_id)
    return {"jobReady": order is not None,
            "mediaTypes": ["text/plain"] if order else [],
            "jobToken": order["id"] if order else ""}


@app.get("/api/cloudprnt/{project_id}", response_class=PlainTextResponse, dependencies=PRINTER)
def cloudprnt_job(project_id: str, role: str = "both"):
    """One printer at the reception iPad prints both documents per order: the
    guest's number slip (they carry it to their table) and the kitchen ticket.
    A second printer in the kitchen can poll with ?role=kitchen instead."""
    project = _project_or_404(project_id)
    order = db.get_next_unprinted_order(project_id)
    if order is None:
        return Response(status_code=204)
    spec = project["spec"]
    docs = []
    if role in ("both", "guest"):
        docs.append(receipt.guest_slip(order, spec["business_name"], spec.get("contact", {})))
    if role in ("both", "kitchen"):
        docs.append(receipt.kitchen_ticket(order, project["name"]))
        # Takeaway also needs a label for the bag itself — reception hands bags
        # over by number and name, and can't read the guest's own slip.
        if order["customer"].get("mode") != "dine_in":
            docs.append(receipt.bag_label(order))
    return PlainTextResponse("".join(docs), media_type="text/plain; charset=utf-8")


@app.delete("/api/cloudprnt/{project_id}", dependencies=PRINTER)
async def cloudprnt_confirm(project_id: str, token: str = ""):
    _project_or_404(project_id)
    order = db.get_next_unprinted_order(project_id) if not token else db.get_order(token)
    if order:
        db.mark_order_printed(order["id"])
    return {"ok": True}


@app.get("/receipt/{order_id}", response_class=HTMLResponse)
def receipt_page(request: Request, order_id: str):
    """Browser-printable receipt — works today on any iPad/printer via the print
    dialog, before a thermal printer is connected."""
    order = db.get_order(order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    project = _project_or_404(order["project_id"])
    spec = project["spec"]
    return templates.TemplateResponse(request, "receipt.html", {
        "receipt_text": receipt.guest_slip(order, spec["business_name"], spec.get("contact", {})),
        "kitchen_text": receipt.kitchen_ticket(order, project["name"]),
        "order_no": receipt.order_no(order),
        "order_id": order_id,
    })


# ---------- Owner admin ----------

@app.get("/admin/{project_id}/orders", response_class=HTMLResponse, dependencies=STAFF)
def orders(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "orders.html", {
        "project": project,
        "orders": db.get_orders(project_id),
        "unsettled": db.get_unsettled_orders(project_id),
    })


@app.post("/api/admin/{project_id}/orders/{order_id}/settle", dependencies=STAFF)
def settle_order(project_id: str, order_id: str):
    """The order was charged on the Zettle reader → mark it paid here. Zettle is
    the certified register that records the sale; we only mirror the outcome so
    the kitchen and the TV board know the guest is good to go."""
    _project_or_404(project_id)
    order = db.get_order(order_id)
    if order is None or order["project_id"] != project_id:
        raise HTTPException(404, "Order not found")
    db.mark_order_paid(order_id, paid_via="zettle")
    return {"ok": True}


@app.get("/admin/{project_id}/customers", response_class=HTMLResponse, dependencies=STAFF)
def customers(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "customers.html", {
        "project": project,
        "customers": db.get_customers(project_id),
    })
