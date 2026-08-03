"""Plain-text renderers for thermal printers (Star et al.) and browser print.

42 columns is the standard width for 80mm thermal paper. The same order data
produces two documents: a KITCHEN TICKET (bong) for the cooks — what to make,
where it goes — and a GUEST SLIP carrying the order number the guest is called
by. Both are the payloads served to a Star CloudPRNT printer or shown on the
printable receipt page.

One legal line runs through this file: for a card payment taken in the
restaurant, the *receipt* is the one Zettle prints — Zettle is the certified
kassaregister. Our slip for those orders is a ticket, not a receipt, and says so.
"""

WIDTH = 42

# Paper is read by guests, and a lot of them walk over from the Liseberg hotels
# without a word of Swedish. Every line a guest acts on is printed in both
# languages; the kitchen's own ticket stays short and English.
MODE_LABEL = {"pickup": "TA MED / TAKE AWAY",
              "delivery": "LEVERANS / DELIVERY",
              "dine_in": "ÄTA HÄR / EAT IN"}


def _line(char: str = "-") -> str:
    return char * WIDTH


def _row(left: str, right: str) -> str:
    space = WIDTH - len(left) - len(right)
    if space < 1:
        left = left[: WIDTH - len(right) - 1]
        space = WIDTH - len(left) - len(right)
    return left + " " * space + right


def _center(text: str) -> str:
    return text.center(WIDTH)


def order_no(order: dict) -> str:
    """What the guest is called by. Falls back to the id for pre-numbering rows."""
    no = order.get("order_no")
    return str(no) if no else order["id"][:4].upper()


def _big_number(order: dict) -> list[str]:
    """The number, unmissable across a room, on paper the guest is holding."""
    return [_center("NUMMER / NUMBER"), _center(order_no(order)), _line("=")]


def kitchen_ticket(order: dict, business_name: str) -> str:
    c = order["customer"]
    mode = c.get("mode", "pickup")
    lines = [
        _center("*** KÖK / KITCHEN ***"),
        _center(business_name),
        _line("="),
        *_big_number(order),
        _row("", MODE_LABEL.get(mode, mode.upper())),
    ]
    if mode == "dine_in" and c.get("table"):
        lines.append(_row("Table:", c["table"]))
    elif mode == "delivery":
        lines.append("Delivery: " + c.get("address", ""))
    lines.append(_row("Time:", c.get("pickup_time", "ASAP")))
    lines.append(_line())
    for it in order["items"]:
        if it["id"] == "_delivery":
            continue
        lines.append(f"{it['qty']} x {it['name']}")
    lines.append(_line())
    if c.get("name"):
        lines.append(_row("Guest:", c["name"]))
    if c.get("phone"):
        lines.append(_row("Phone:", c["phone"]))
    if order.get("status") == "paid":
        via = {"stripe": "PAID ONLINE", "zettle": "PAID ON CARD READER"}
        lines.append(_center(via.get(order.get("paid_via", ""), "PAID")))
    else:
        lines.append(_center("NOT PAID — PAYS ON THE CARD READER"))
    return "\n".join(lines) + "\n\n\n"


def guest_slip(order: dict, business_name: str, contact: dict) -> str:
    """The paper the guest carries to their table. For an online-paid order this
    IS the receipt (a distance sale we registered ourselves). For a card payment
    in the restaurant it is only the order ticket — Zettle prints the receipt."""
    cur = order["currency"]
    paid_online = order.get("status") == "paid" and order.get("paid_via") != "zettle"
    lines = [_center(business_name)]
    if contact.get("address"):
        lines.append(_center(contact["address"]))
    if contact.get("phone"):
        lines.append(_center(contact["phone"]))
    lines += [_line("="), *_big_number(order)]
    lines.append(_center(MODE_LABEL.get(order["customer"].get("mode", "pickup"), "")))
    lines.append(_line())
    lines.append(_center("KVITTO / RECEIPT" if paid_online else "BESTÄLLNING / ORDER"))
    lines.append(_line())
    for it in order["items"]:
        name = "Leverans" if it["id"] == "_delivery" else it["name"]
        lines.append(_row(f"{it['qty']} x {name}", f"{it['price'] * it['qty']:.0f}"))
    lines.append(_line())
    lines.append(_row("SUMMA / TOTAL", f"{order['total']:.0f} {cur}"))
    if paid_online:
        # We took this money at a distance, so we account for the VAT here.
        lines.append(_row("varav moms / incl. VAT 12%", f"{order['total'] * 12 / 112:.2f} {cur}"))
        lines.append(_line())
        lines.append(_center("Betald online / Paid online"))
    else:
        lines.append(_line())
        lines.append(_center("BETALA I KORTTERMINALEN"))
        lines.append(_center("PAY ON THE CARD READER"))
        lines.append(_center("Kvitto får du därifrån"))
        lines.append(_center("Your receipt comes from the reader"))
    lines.append(_line())
    lines.append(_center(f"Vi ropar nummer {order_no(order)} när maten är klar"))
    lines.append(_center(f"We'll call number {order_no(order)} when it's ready"))
    lines.append(_center("Tack! / Thank you!"))
    return "\n".join(lines) + "\n\n\n"


def bag_label(order: dict) -> str:
    """Sticks on the takeaway bag. Reception hands bags over off this label
    alone, so it carries only what identifies the bag: number, name, and that
    it is going out the door rather than to a table."""
    c = order["customer"]
    lines = [
        _line("="),
        _center("TAKE AWAY BAG / PÅSE"),
        *_big_number(order),
    ]
    if c.get("name"):
        lines.append(_center(c["name"].upper()))
    if c.get("phone"):
        lines.append(_center(c["phone"]))
    when = c.get("pickup_time", "ASAP")
    if when and when != "ASAP":
        lines.append(_center(f"Hämtas / Pickup {when}"))
    lines.append(_line("="))
    return "\n".join(lines) + "\n\n\n"


# Kept so older callers/tests keep working; the guest slip replaced it.
customer_receipt = guest_slip
