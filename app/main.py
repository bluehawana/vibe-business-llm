import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import db, llm, receipt, stripe_pay
from .schema import DEFAULT_SPEC, find_menu_item

app = FastAPI(title="Vibe Business")
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

db.init_db()


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
    customer_name: str
    customer_phone: str
    mode: str  # "pickup" | "delivery" | "dine_in"
    address: str = ""
    table: str = ""  # dine_in: table number from QR code / in-store iPad
    pickup_time: str = ""  # pickup/delivery: requested time, e.g. "18:30" or "ASAP"


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
    return templates.TemplateResponse(request, "landing.html", {})


@app.post("/api/projects")
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


@app.get("/builder/{project_id}", response_class=HTMLResponse)
def builder(request: Request, project_id: str):
    project = _project_or_404(project_id)
    messages = db.get_messages(project_id)
    return templates.TemplateResponse(request, "builder.html", {
        "project": project,
        "messages": messages,
    })


@app.post("/api/projects/{project_id}/chat")
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
        if not body.table.strip():
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

    # Prepayment is mandatory. No order is ever accepted without it — an unpaid
    # order is a no-show risk the kitchen should never cook for.
    if not stripe_pay.payments_configured():
        raise HTTPException(503, "Online payments are not set up yet for this shop")

    if stripe_pay.stripe_enabled():
        # Real Stripe: order stays 'pending' and is INVISIBLE to the kitchen
        # until Stripe's webhook confirms payment (see mark_order_paid).
        order_id = db.create_order(project_id, order_items, customer, total, currency, "pending")
        url = stripe_pay.create_checkout_session(project_id, order_id, line_items, currency)
        return {"url": url}

    # Local demo stub (VIBE_DEMO_PAYMENTS=1 only): simulates a successful payment
    # so the full chain can be tested without real Stripe keys.
    order_id = db.create_order(project_id, order_items, customer, total, currency, "paid")
    return {"url": f"/site/{project_id}/success?order={order_id}&demo=1"}


@app.get("/site/{project_id}/success", response_class=HTMLResponse)
def success(request: Request, project_id: str, order: str = "", demo: str = ""):
    project = _project_or_404(project_id)
    order_data = db.get_order(order) if order else None
    return templates.TemplateResponse(request, "success.html", {
        "project_id": project_id,
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
        db.mark_order_paid(order_id)
    return {"ok": True}


# ---------- Kitchen display (KDS) ----------

@app.get("/kitchen/{project_id}", response_class=HTMLResponse)
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


@app.get("/api/kitchen/{project_id}/orders")
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


@app.get("/display/{project_id}", response_class=HTMLResponse)
def display(request: Request, project_id: str):
    """Customer-facing order-status board for a TV (open in Safari on Apple TV):
    shows order numbers moving from 'Tillagas' to 'Klar för avhämtning'."""
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "display.html", {"project": project})


@app.post("/api/kitchen/{project_id}/orders/{order_id}/status")
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


# ---------- In-store iPad kiosk ----------

@app.get("/kiosk/{project_id}", response_class=HTMLResponse)
def kiosk(request: Request, project_id: str):
    """Counter iPad: the same ordering UI framed for staff or self-serve use.
    Reuses the site page; ?kiosk=1 tells the front-end to run in kiosk mode."""
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

@app.post("/api/cloudprnt/{project_id}")
async def cloudprnt_poll(project_id: str):
    _project_or_404(project_id)
    order = db.get_next_unprinted_order(project_id)
    return {"jobReady": order is not None,
            "mediaTypes": ["text/plain"] if order else [],
            "jobToken": order["id"] if order else ""}


@app.get("/api/cloudprnt/{project_id}", response_class=PlainTextResponse)
def cloudprnt_job(project_id: str):
    project = _project_or_404(project_id)
    order = db.get_next_unprinted_order(project_id)
    if order is None:
        return Response(status_code=204)
    ticket = receipt.kitchen_ticket(order, project["name"])
    return PlainTextResponse(ticket, media_type="text/plain; charset=utf-8")


@app.delete("/api/cloudprnt/{project_id}")
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
    text = receipt.customer_receipt(order, spec["business_name"], spec.get("contact", {}))
    kitchen = receipt.kitchen_ticket(order, project["name"])
    return templates.TemplateResponse(request, "receipt.html", {
        "receipt_text": text, "kitchen_text": kitchen, "order_id": order_id,
    })


# ---------- Owner admin ----------

@app.get("/admin/{project_id}/orders", response_class=HTMLResponse)
def orders(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "orders.html", {
        "project": project,
        "orders": db.get_orders(project_id),
    })


@app.get("/admin/{project_id}/customers", response_class=HTMLResponse)
def customers(request: Request, project_id: str):
    project = _project_or_404(project_id)
    return templates.TemplateResponse(request, "customers.html", {
        "project": project,
        "customers": db.get_customers(project_id),
    })
