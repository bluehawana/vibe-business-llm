"""Plain-text renderers for thermal printers (Star et al.) and browser print.

42 columns is the standard width for 80mm thermal paper. The same order data
produces two documents: a KITCHEN TICKET (bong) for the cooks — what to make,
where it goes — and a CUSTOMER RECEIPT — what was paid. Both are the payloads
served to a Star CloudPRNT printer or shown on the printable receipt page.
"""

WIDTH = 42

MODE_LABEL = {"pickup": "AVHÄMTNING", "delivery": "LEVERANS", "dine_in": "BORD"}


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


def kitchen_ticket(order: dict, business_name: str) -> str:
    c = order["customer"]
    mode = c.get("mode", "pickup")
    lines = [
        _center("*** KÖK / KITCHEN ***"),
        _center(business_name),
        _line(),
        _row(f"#{order['id'][:6]}", MODE_LABEL.get(mode, mode.upper())),
    ]
    if mode == "dine_in":
        lines.append(_row("Bord:", c.get("table", "")))
    elif mode == "delivery":
        lines.append("Leverans: " + c.get("address", ""))
    when = c.get("pickup_time", "ASAP")
    lines.append(_row("Tid:", when))
    lines.append(_line())
    for it in order["items"]:
        if it["id"] == "_delivery":
            continue
        lines.append(f"{it['qty']} x {it['name']}")
    lines.append(_line())
    lines.append(_row("Kund:", c.get("name", "")))
    lines.append(_row("Tel:", c.get("phone", "")))
    paid = order.get("status") == "paid"
    lines.append(_center("BETALD / PAID" if paid else "BETALA I RESTAURANGEN"))
    return "\n".join(lines) + "\n\n\n"


def customer_receipt(order: dict, business_name: str, contact: dict) -> str:
    cur = order["currency"]
    lines = [
        _center(business_name),
    ]
    if contact.get("address"):
        lines.append(_center(contact["address"]))
    if contact.get("phone"):
        lines.append(_center(contact["phone"]))
    lines += [_line(), _row("Kvitto", f"#{order['id'][:6]}"), _line()]
    for it in order["items"]:
        name = "Leverans" if it["id"] == "_delivery" else it["name"]
        lines.append(_row(f"{it['qty']} x {name}", f"{it['price'] * it['qty']:.0f}"))
    lines.append(_line())
    lines.append(_row("SUMMA", f"{order['total']:.0f} {cur}"))
    lines.append(_row("varav moms 12%", f"{order['total'] * 12 / 112:.2f} {cur}"))
    lines.append(_line())
    lines.append(_center("Tack för ditt besök!"))
    lines.append(_center("Powered by Vibe Business"))
    return "\n".join(lines) + "\n\n\n"
