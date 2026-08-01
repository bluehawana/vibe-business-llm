# Vibe Business

**Describe your business in plain language → get a complete website with online ordering
and payments. Keep talking to improve it.**

An MVP of the "vibe-to-OS" idea: a platform where a non-technical business owner (first
vertical: restaurants) builds and runs their online presence purely through conversation —
no code, no Wix, no per-seat SaaS.

## How it works

```
Owner chats in plain language (Swedish/English/any)
        │
        ▼
Claude (claude-fable-5, falls back to claude-opus-4-8) maintains a structured
"site spec" — menu, prices, services, hours, theme, copy — via structured outputs
        │
        ▼
The platform renders the spec into a live website with cart + checkout,
and closes the transaction chain through Stripe (test mode) or demo mode
```

The LLM never generates raw payment code — prices live in the spec, checkout builds
Stripe line items server-side from the spec, orders land in SQLite and the owner's
order dashboard. That's what makes "AI-customized commerce" safe.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Auth: either `ant auth login`, or export ANTHROPIC_API_KEY=...
uvicorn app.main:app --port 8100
```

Open http://localhost:8100 — describe a restaurant, get the site, keep chatting in the
builder, place a test order on the live site, see it in `/admin/<id>/orders`.

## Configuration (.env / environment)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (profile auth) | Anthropic API access |
| `VIBE_MODEL` | `claude-fable-5` | Builder model (auto-fallback to `claude-opus-4-8`) |
| `STRIPE_SECRET_KEY` | unset → demo mode | Stripe test key enables real Checkout |
| `STRIPE_WEBHOOK_SECRET` | unset | Verifies Stripe webhooks |
| `BASE_URL` | `http://localhost:8100` | Public URL for Stripe redirects |

## Architecture

- `app/schema.py` — the site spec JSON schema (the "customizable SaaS" contract)
- `app/llm.py` — the only file that talks to the LLM; swap point for local models later
- `app/main.py` — FastAPI routes: builder, published site, checkout, webhook, orders
- `app/db.py` — SQLite (projects, chat history, orders)
- `app/stripe_pay.py` — Stripe Checkout + webhook, demo-mode fallback
- `app/templates/` — builder UI and the rendered tenant site

## MVP limitations (deliberate)

- No authentication — anyone with a project URL can edit it. Add before deploying publicly.
- One template family (restaurant). The spec schema is where new verticals get added.
- Sites render server-side from the spec; no arbitrary code generation yet.
