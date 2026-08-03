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
        ("combo-8", "Sushi 8 pieces", "Mixed sushi, 8 pieces", 99, ["popular"]),
        ("combo-10", "Sushi 10 pieces", "Mixed sushi, 10 pieces", 119, ["popular"]),
        ("combo-12", "Sushi 12 pieces", "Mixed sushi, 12 pieces", 139),
        ("combo-15", "Sushi 15 pieces", "Mixed sushi, 15 pieces", 169),
        ("combo-familj-40", "Family sushi 40 pieces", "To share", 499),
    ]),
    cat("Vegetarian Sushi", "sushi", [
        ("veg-8", "Vegetarian sushi 8 pieces", "", 99, ["vegetarian"]),
        ("veg-10", "Vegetarian sushi 10 pieces", "", 119, ["vegetarian"]),
        ("veg-12", "Vegetarian sushi 12 pieces", "", 139, ["vegetarian"]),
    ]),
    cat("Poké Bowls", "sushi", [
        ("poke-lax", "Salmon Poké", "Rice, salmon, vegetables", 149, ["popular"]),
        ("poke-veg", "Vegetarian Poké", "Rice, tofu, vegetables", 139, ["vegetarian"]),
        ("poke-raka", "Prawn Poké", "Rice, prawns, vegetables", 139),
        ("poke-kyckling", "Chicken Poké", "Rice, chicken, vegetables", 149),
        ("poke-ebi", "Crispy Ebi Poké", "Rice, crispy prawn, vegetables", 159),
    ]),
    cat("Hot Dishes", "kitchen", [
        ("yakitori", "Yakitori", "Grilled chicken skewers", 129),
        ("yakiniku", "Yakiniku", "Grilled beef", 135),
        ("dumpling-kyckling", "Chicken dumplings", "", 135),
        ("dumpling-veg", "Vegetarian dumplings", "", 135, ["vegetarian"]),
        ("bibimbap", "Bibimbap", "Korean rice bowl", 139),
        ("bibimbap-veg", "Vegetarian bibimbap", "", 139, ["vegetarian"]),
        ("egen-kombo", "Build your own combo", "Pick your own combination", 139),
    ]),
    cat("Starters", "kitchen", [
        ("wakame", "Wakame seaweed salad", "", 39, ["vegetarian"]),
        ("kimchi", "Kimchi", "", 49, ["vegetarian", "spicy"]),
        ("edamame", "Edamame", "Salted soy beans", 49, ["vegetarian"]),
        ("varrullar", "Mini spring rolls", "", 69, ["vegetarian"]),
        ("ebi-fry", "Ebi fry", "Crispy fried prawns", 79),
        ("gyoza", "Crispy gyoza dumplings", "", 59),
        ("golden-chicken", "Golden chicken", "", 79),
        ("lax-sallad", "Salmon salad", "", 89),
        ("fry-mix", "Fry Mix", "Mixed fried selection", 99),
    ]),
    cat("Nigiri Combo", "sushi", [
        ("nigiri-10-lax-avo", "Salmon & avocado, 10 pieces", "", 149),
        ("nigiri-12-lax-avo", "Salmon & avocado, 12 pieces", "", 169),
        ("nigiri-8-flamberad", "Flamed salmon, 8 pieces", "", 139),
        ("nigiri-10-flamberad", "Flamed salmon, 10 pieces", "", 169),
    ]),
    cat("Nigiri by the piece", "sushi", [
        ("nigiri-lax", "Salmon", "", 17),
        ("nigiri-raka", "Prawn", "", 17),
        ("nigiri-tilapia", "Tilapia", "", 17),
        ("nigiri-tonfisk", "Tuna", "", 17),
        ("nigiri-blackfisk", "Octopus", "", 18),
        ("nigiri-flamberad-lax", "Flamed salmon", "", 18),
        ("nigiri-tofu", "Tofu", "", 16, ["vegetarian"]),
        ("nigiri-avokado", "Avocado", "", 16, ["vegetarian"]),
        ("nigiri-omelett", "Omelette", "", 16, ["vegetarian"]),
        ("nigiri-portobello", "Portobello", "", 18, ["vegetarian"]),
    ]),
    cat("Nori Maki", "sushi", [
        ("maki-lax", "Salmon maki", "", 129),
        ("maki-classic-lax", "Classic salmon maki", "", 129),
        ("maki-spicy-lax", "Spicy salmon maki", "", 129, ["spicy"]),
    ]),
    cat("Uramaki", "sushi", [
        ("uramaki-california", "California roll", "", 129, ["popular"]),
        ("uramaki-boston", "Boston roll", "", 129),
        ("uramaki-newyork", "New York roll", "", 129),
        ("uramaki-veg", "Vegetarian roll", "", 129, ["vegetarian"]),
        ("uramaki-spicy-lax", "Spicy salmon roll", "", 139, ["spicy"]),
        ("uramaki-ebi", "Crispy ebi", "", 139),
        ("uramaki-kyckling", "Crispy chicken", "", 139),
    ]),
    cat("Deluxe Roll", "sushi", [
        ("deluxe-dragon", "Dragon roll", "", 145),
        ("deluxe-rainbow", "Rainbow roll", "", 145),
        ("deluxe-veggie", "Veggie roll", "", 145, ["vegetarian"]),
        ("deluxe-nemo", "Nemo roll", "", 149),
        ("deluxe-alaska", "Alaska roll", "", 149),
        ("deluxe-super-kyckling", "Super crispy chicken", "", 155),
        ("deluxe-orange-ebi", "Orange crispy ebi", "", 159),
        ("deluxe-green-ebi", "Green crispy ebi", "", 155),
        ("deluxe-sunshine", "Sunshine roll", "", 159),
        ("deluxe-super-lax", "Super salmon roll", "", 169),
        ("deluxe-tiger", "Tiger roll", "", 169),
    ]),
    cat("Drinks", "bar", [
        ("dryck-lask", "Soft drink", "Coca-Cola, Fanta, Sprite", 25),
        ("dryck-vatten", "Sparkling water", "", 25),
        ("dryck-ramune", "Ramune", "Japanese soda", 39),
        ("dryck-te", "Green tea", "", 29),
    ]),
]

SPEC = {
    "business_name": "Ichiban Sushi",
    "tagline": "Fresh sushi, made by hand",
    "about": "We make all our sushi by hand, every day, from ingredients we pick ourselves. "
             "Order on the screen or on your phone \u2014 you get a number, and we call it "
             "when your food is ready.",
    "language": "en",
    "currency": SEK,
    "theme": {
        "primary_color": "#8c1c13",
        "accent_color": "#c9713a",
        "background_color": "#fbf6ee",
        "text_color": "#25211c",
        "font": "mixed",
    },
    "hero": {"headline": "Ichiban Sushi", "subheadline": "Handmade sushi \u2014 eat in or take away",
             "emoji": "🍣"},
    "menu": MENU,
    "services": {
        "pickup": True, "delivery": False, "delivery_fee": 0, "min_order_for_delivery": 0,
        "dine_in": True, "pay_online": True, "pay_in_store": True,
    },
    "hours": [
        {"days": "Mon-Fri", "open": "11:00", "close": "21:00"},
        {"days": "Sat-Sun", "open": "12:00", "close": "21:00"},
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
