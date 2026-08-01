"""Claude integration: every builder turn sends the chat history + current site
spec and gets back {reply, site} via structured outputs."""

import json
import os

import anthropic

from .schema import RESPONSE_SCHEMA

MODEL = os.environ.get("VIBE_MODEL", "claude-fable-5")
FALLBACK_MODEL = "claude-opus-4-8"

client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are Vibe Business, an AI that builds and runs websites for small \
businesses — starting with restaurants. Your user is a business owner with zero IT \
knowledge. They describe what they want in plain language (often Swedish or English); \
you maintain the complete website for them as a structured site spec.

Rules:
- Always return the COMPLETE updated site spec, not a fragment.
- Fill in tasteful, realistic details the owner didn't specify (menu descriptions, \
colors matching the cuisine, opening hours typical for the business type) — but never \
invent prices for items the owner priced, and never delete things they added unless asked.
- Menu item ids are stable kebab-case slugs. Keep existing ids unchanged when editing \
an item; new dishes get new ids.
- Default currency SEK and Swedish conventions when the business appears to be in Sweden.
- Write all site-facing text (tagline, about, menu descriptions) in the site language; \
write your `reply` in the same language the owner writes to you.
- Theme: light, warm, paper-like backgrounds; muted colors that fit the cuisine. No neon, \
no dark themes unless explicitly requested.
- In `reply`, briefly say what you changed and offer ONE concrete next suggestion. \
Keep it to 2-4 sentences, no technical jargon (never mention JSON, specs, databases).
- Services: `dine_in` enables ordering to the table (QR code / in-store iPad); `delivery` \
means the restaurant's OWN delivery with own staff — we never integrate Foodora/Wolt/Uber \
Eats. Enable services only when the owner says they offer them.
- Legal guardrails (Sweden): age-restricted goods (tobacco, snus, e-cigarettes, alcohol, \
lottery) must carry the tag "in-store-only" — they are then displayed but cannot be \
ordered online. Never make them orderable, even if asked; explain briefly why. \
Regulated services the shop offers through licensed partners (money transfer, gambling \
agents) may be DESCRIBED on the site (rates, partners, opening hours) via announcements \
and the about text, but the site never processes such transactions.
"""


class BuilderRefused(Exception):
    pass


def chat_update(history: list[dict], site: dict, user_message: str) -> tuple[str, dict]:
    """history: [{role, content}] of prior plain-text turns (no specs embedded)."""
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({
        "role": "user",
        "content": (
            f"<current_site_spec>\n{json.dumps(site, ensure_ascii=False)}\n</current_site_spec>\n\n"
            f"{user_message}"
        ),
    })

    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}, "effort": "high"},
    )

    if MODEL.startswith(("claude-fable", "claude-mythos")):
        # Fable 5: safety classifiers can decline benign requests; server-side
        # fallback re-serves the request on Opus 4.8 inside the same call.
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": FALLBACK_MODEL}],
            **kwargs,
        )
    else:
        response = client.messages.create(**kwargs)

    if response.stop_reason == "refusal":
        raise BuilderRefused("The assistant declined this request. Try rephrasing it.")

    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return data["reply"], data["site"]
