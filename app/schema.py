"""Site spec: the single JSON document that describes a business website.

Claude reads and rewrites this spec on every chat turn; the renderer turns it
into the live site. Keeping prices and services in structured data (not
generated HTML) is what lets checkout build real Stripe line items safely.
"""


def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


SITE_SCHEMA = _obj({
    "business_name": {"type": "string"},
    "copyright": {"type": "string",
                  "description": "Footer legal line, e.g. '© 2026 Hong Yan AB'. Empty for default."},
    "logo": {"type": "string",
             "description": "Logo image URL shown in the nav and as favicon, or empty string"},
    "tagline": {"type": "string"},
    "about": {"type": "string", "description": "1-2 warm paragraphs about the business"},
    "language": {"type": "string", "description": "Site language code, e.g. 'sv' or 'en'"},
    "currency": {"type": "string", "enum": ["SEK", "EUR", "USD", "GBP", "DKK", "NOK"]},
    "theme": _obj({
        "primary_color": {"type": "string", "description": "hex, used for headings/buttons"},
        "accent_color": {"type": "string", "description": "hex"},
        "background_color": {"type": "string", "description": "hex, light paper-like"},
        "text_color": {"type": "string", "description": "hex, dark"},
        "font": {"type": "string", "enum": ["serif", "sans", "mixed"]},
    }),
    "hero": _obj({
        "headline": {"type": "string"},
        "subheadline": {"type": "string"},
        "emoji": {"type": "string", "description": "1-3 emoji that fit the cuisine"},
        "image": {"type": "string",
                  "description": "Full-width photo URL behind the headline, or empty string"},
    }),
    # What a search result and a shared link look like. A restaurant lives or dies
    # on being found and on the link looking appetising when someone pastes it
    # into a group chat — that is most of what a site builder is actually for.
    "seo": _obj({
        "title": {"type": "string", "description": "Browser tab and Google result title, ~60 chars"},
        "description": {"type": "string",
                        "description": "Google result and link-preview text, ~155 chars"},
    }),
    "gallery": {
        "type": "array",
        "description": "Photos of the food and the room. Empty list if none.",
        "items": _obj({
            "image": {"type": "string", "description": "Photo URL"},
            "caption": {"type": "string"},
        }),
    },
    "menu": {
        "type": "array",
        "items": _obj({
            "category": {"type": "string"},
            "image": {"type": "string",
                      "description": "Photo URL for the category tile, or empty string"},
            "items": {
                "type": "array",
                "items": _obj({
                    "id": {"type": "string", "description": "stable kebab-case slug, never reuse for a different dish"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "price": {"type": "number"},
                    "station": {"type": "string", "enum": ["kitchen", "sushi", "bar", "dessert"],
                                "description": "which station prepares this — routes it to the right kitchen screen/printer. sushi/sashimi/maki/nigiri -> sushi; hot dishes -> kitchen; drinks -> bar; desserts -> dessert."},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "e.g. vegetarian, vegan, spicy, popular, gluten-free"},
                    "image": {"type": "string",
                              "description": "Photo URL for this dish, or empty string if there is none"},
                }),
            },
        }),
    },
    "services": _obj({
        "pickup": {"type": "boolean"},
        "delivery": {"type": "boolean", "description": "restaurant's OWN delivery (own cars/staff) — not Foodora/Wolt"},
        "delivery_fee": {"type": "number"},
        "min_order_for_delivery": {"type": "number"},
        "dine_in": {"type": "boolean", "description": "order from the table/counter via QR or in-store iPad"},
        "pay_online": {"type": "boolean",
                       "description": "offer paying by card/Swish/Apple Pay at the moment of ordering (Stripe)"},
        "pay_in_store": {"type": "boolean",
                         "description": "offer paying on the card reader in the restaurant (Zettle)"},
    }),
    "hours": {
        "type": "array",
        "items": _obj({
            "days": {"type": "string", "description": "e.g. 'Mon-Fri' or 'Lör-Sön'"},
            "open": {"type": "string", "description": "e.g. '11:00'"},
            "close": {"type": "string", "description": "e.g. '21:00'"},
        }),
    },
    "contact": _obj({
        "address": {"type": "string"},
        "phone": {"type": "string"},
        "email": {"type": "string"},
        "facebook": {"type": "string", "description": "Facebook page URL or empty"},
        "instagram": {"type": "string", "description": "Instagram URL or empty"},
    }),
    "announcements": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Short banners, e.g. lunch offer. Empty list if none.",
    },
})

RESPONSE_SCHEMA = _obj({
    "reply": {
        "type": "string",
        "description": "Short friendly message to the owner about what you changed or suggest, in their language",
    },
    "site": SITE_SCHEMA,
})

DEFAULT_SPEC = {
    "business_name": "My Restaurant",
    "copyright": "",
    "logo": "",
    "tagline": "Good food, made with care",
    "about": "",
    "language": "en",
    "currency": "SEK",
    "theme": {
        "primary_color": "#2f4436",
        "accent_color": "#c96f4a",
        "background_color": "#faf7f0",
        "text_color": "#2b2a26",
        "font": "mixed",
    },
    "hero": {"headline": "Welcome", "subheadline": "", "emoji": "🍽️", "image": ""},
    "seo": {"title": "", "description": ""},
    "gallery": [],
    "menu": [],
    "services": {"pickup": True, "delivery": False, "delivery_fee": 0, "min_order_for_delivery": 0,
                 "dine_in": False, "pay_online": True, "pay_in_store": True},
    "hours": [],
    "contact": {"address": "", "phone": "", "email": "", "facebook": "", "instagram": ""},
    "announcements": [],
}


def find_menu_item(spec: dict, item_id: str):
    for category in spec.get("menu", []):
        for item in category.get("items", []):
            if item.get("id") == item_id:
                return item
    return None
