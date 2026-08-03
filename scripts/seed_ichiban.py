"""Seed (or re-seed) Ichiban Sushi from the real à la carte menu on ichiban.biz.

Run:  .venv/bin/python -m scripts.seed_ichiban

Categories here are the "folders" the kiosk drills into, and the order they
appear in is the order guests see them, so the sellers come first.
"""

import sys

from app import db

SEK = "SEK"


def cat(name, station, items, image=""):
    return {"category": name, "image": image, "items": [
        {"id": i[0], "name": i[1], "description": i[2] if len(i) > 2 else "",
         "price": i[3] if len(i) > 3 else i[2], "station": station,
         "tags": list(i[4]) if len(i) > 4 else []}
        for i in items
    ]}


MENU = [
    cat("Sushi Combo", "sushi", [
        ("combo-8", "8 bitars sushi", "Blandad sushi, 8 bitar", 99, ["populär"]),
        ("combo-10", "10 bitars sushi", "Blandad sushi, 10 bitar", 119, ["populär"]),
        ("combo-12", "12 bitars sushi", "Blandad sushi, 12 bitar", 139),
        ("combo-15", "15 bitars sushi", "Blandad sushi, 15 bitar", 169),
        ("combo-familj-40", "Familjesushi 40 bitar", "Att dela på", 499),
    ]),
    cat("Vegetarisk sushi", "sushi", [
        ("veg-8", "8 bitars vegetarisk sushi", "", 99, ["vegetarisk"]),
        ("veg-10", "10 bitars vegetarisk sushi", "", 119, ["vegetarisk"]),
        ("veg-12", "12 bitars vegetarisk sushi", "", 139, ["vegetarisk"]),
    ]),
    cat("Poké Bowls", "sushi", [
        ("poke-lax", "Lax Poké", "Ris, lax, grönsaker", 149, ["populär"]),
        ("poke-veg", "Vegetarisk Poké", "Ris, tofu, grönsaker", 139, ["vegetarisk"]),
        ("poke-raka", "Prawn Poké", "Ris, räkor, grönsaker", 139),
        ("poke-kyckling", "Kyckling Poké", "Ris, kyckling, grönsaker", 149),
        ("poke-ebi", "Krispig Ebi Poké", "Ris, friterad räka, grönsaker", 159),
    ]),
    cat("Varmrätter", "kitchen", [
        ("yakitori", "Yakitori", "Grillade kycklingspett", 129),
        ("yakiniku", "Yakiniku", "Grillat kött", 135),
        ("dumpling-kyckling", "Kycklingdumplings", "", 135),
        ("dumpling-veg", "Vegetariska dumplings", "", 135, ["vegetarisk"]),
        ("bibimbap", "Bibimbap", "Koreansk risrätt", 139),
        ("bibimbap-veg", "Vegetarisk bibimbap", "", 139, ["vegetarisk"]),
        ("egen-kombo", "Egen kombo", "Välj dina favoriter", 139),
    ]),
    cat("Förrätter", "kitchen", [
        ("wakame", "Wakame sjögrässallad", "", 39, ["vegetarisk"]),
        ("kimchi", "Kimchi", "", 49, ["vegetarisk", "stark"]),
        ("edamame", "Edamame", "Saltade sojabönor", 49, ["vegetarisk"]),
        ("varrullar", "Mini vårrullar", "", 69, ["vegetarisk"]),
        ("ebi-fry", "Ebi fry", "Friterade räkor", 79),
        ("gyoza", "Krispig gyoza dumpling", "", 59),
        ("golden-chicken", "Golden chicken", "", 79),
        ("lax-sallad", "Laxsallad", "", 89),
        ("fry-mix", "Fry Mix", "Blandat friterat", 99),
    ]),
    cat("Nigiri Combo", "sushi", [
        ("nigiri-10-lax-avo", "10 bitar lax & avokado", "", 149),
        ("nigiri-12-lax-avo", "12 bitar lax & avokado", "", 169),
        ("nigiri-8-flamberad", "8 bitar flamberad lax", "", 139),
        ("nigiri-10-flamberad", "10 bitar flamberad lax", "", 169),
    ]),
    cat("Nigiri styckvis", "sushi", [
        ("nigiri-lax", "Lax", "", 17),
        ("nigiri-raka", "Räka", "", 17),
        ("nigiri-tilapia", "Tilapia", "", 17),
        ("nigiri-tonfisk", "Tonfisk", "", 17),
        ("nigiri-blackfisk", "Bläckfisk", "", 18),
        ("nigiri-flamberad-lax", "Flamberad lax", "", 18),
        ("nigiri-tofu", "Tofu", "", 16, ["vegetarisk"]),
        ("nigiri-avokado", "Avokado", "", 16, ["vegetarisk"]),
        ("nigiri-omelett", "Omelett", "", 16, ["vegetarisk"]),
        ("nigiri-portobello", "Portobello", "", 18, ["vegetarisk"]),
    ]),
    cat("Nori Maki", "sushi", [
        ("maki-lax", "Laxmaki", "", 129),
        ("maki-classic-lax", "Classic laxmaki", "", 129),
        ("maki-spicy-lax", "Spicy laxmaki", "", 129, ["stark"]),
    ]),
    cat("Uramaki", "sushi", [
        ("uramaki-california", "California roll", "", 129, ["populär"]),
        ("uramaki-boston", "Boston roll", "", 129),
        ("uramaki-newyork", "New York roll", "", 129),
        ("uramaki-veg", "Vegetarisk roll", "", 129, ["vegetarisk"]),
        ("uramaki-spicy-lax", "Spicy lax roll", "", 139, ["stark"]),
        ("uramaki-ebi", "Krispig Ebi", "", 139),
        ("uramaki-kyckling", "Krispig kyckling", "", 139),
    ]),
    cat("Deluxe Roll", "sushi", [
        ("deluxe-dragon", "Dragon roll", "", 145),
        ("deluxe-rainbow", "Rainbow roll", "", 145),
        ("deluxe-veggie", "Veggie roll", "", 145, ["vegetarisk"]),
        ("deluxe-nemo", "Nemo roll", "", 149),
        ("deluxe-alaska", "Alaska roll", "", 149),
        ("deluxe-super-kyckling", "Super krispig kyckling", "", 155),
        ("deluxe-orange-ebi", "Orange krispig Ebi", "", 159),
        ("deluxe-green-ebi", "Green krispig Ebi", "", 155),
        ("deluxe-sunshine", "Sunshine roll", "", 159),
        ("deluxe-super-lax", "Super lax roll", "", 169),
        ("deluxe-tiger", "Tiger roll", "", 169),
    ]),
    cat("Dryck", "bar", [
        ("dryck-lask", "Läsk", "Coca-Cola, Fanta, Sprite", 25),
        ("dryck-vatten", "Mineralvatten", "", 25),
        ("dryck-ramune", "Ramune", "Japansk läsk", 39),
        ("dryck-te", "Grönt te", "", 29),
    ]),
]

SPEC = {
    "business_name": "Ichiban Sushi",
    "tagline": "Färsk sushi, gjord för hand",
    "about": "Vi gör all sushi för hand, varje dag, av råvaror vi själva väljer ut. "
             "Beställ på skärmen eller i mobilen — du får ett nummer och vi ropar dig "
             "när maten är klar.",
    "language": "sv",
    "currency": SEK,
    "theme": {
        "primary_color": "#8c1c13",
        "accent_color": "#c9713a",
        "background_color": "#fbf6ee",
        "text_color": "#25211c",
        "font": "mixed",
    },
    "hero": {"headline": "Ichiban Sushi", "subheadline": "Handgjord sushi — äta här eller ta med",
             "emoji": "🍣"},
    "menu": MENU,
    "services": {
        "pickup": True, "delivery": False, "delivery_fee": 0, "min_order_for_delivery": 0,
        "dine_in": True, "pay_online": True, "pay_in_store": True,
    },
    "hours": [
        {"days": "Mån-Fre", "open": "11:00", "close": "21:00"},
        {"days": "Lör-Sön", "open": "12:00", "close": "21:00"},
    ],
    "contact": {"address": "", "phone": "", "email": ""},
    "announcements": [],
}


def main():
    db.init_db()
    existing = [p for p in _all_projects() if p["name"] == "Ichiban Sushi"]
    if existing:
        pid = existing[0]["id"]
        db.update_spec(pid, SPEC)
        print(f"updated existing project {pid}")
    else:
        pid = db.create_project("Ichiban Sushi", SPEC)
        print(f"created project {pid}")
    n = sum(len(c["items"]) for c in MENU)
    print(f"{len(MENU)} categories, {n} items")
    print(f"kiosk:   /kiosk/{pid}")
    print(f"counter: /counter/{pid}")
    print(f"tv:      /display/{pid}")
    print(f"panel:   /panel/{pid}")


def _all_projects():
    with db._connect() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM projects")]


if __name__ == "__main__":
    sys.exit(main())
