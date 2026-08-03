"""Stripe Checkout integration. Runs in demo mode (orders complete instantly)
when STRIPE_SECRET_KEY is not set, so the full order chain works without keys."""

import os

import stripe

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
# Comma-separated, because one endpoint is rarely the whole story: a test-mode
# and a live-mode destination have different secrets, and rotating a secret means
# briefly accepting the old one and the new one. Any of them may verify an event.
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8100")
# Explicit opt-in for the no-Stripe testing stub. Without this AND without a
# Stripe key, checkout refuses — an order must never be accepted without payment.
DEMO_PAYMENTS = os.environ.get("VIBE_DEMO_PAYMENTS", "") == "1"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def stripe_enabled() -> bool:
    return bool(STRIPE_SECRET_KEY)


def webhook_secrets() -> list[str]:
    """Every signing secret we'll accept, in order. Read at call time so tests
    and a restart-free key change both take effect."""
    return [s.strip() for s in STRIPE_WEBHOOK_SECRET.split(",") if s.strip()]


def payments_configured() -> bool:
    """True when the shop can actually collect prepayment (real Stripe, or the
    explicit local demo stub). If neither, checkout is blocked on purpose."""
    return bool(STRIPE_SECRET_KEY) or DEMO_PAYMENTS


def create_checkout_session(project_id: str, order_id: str, line_items: list[dict],
                            currency: str) -> str:
    """line_items: [{name, unit_amount_minor, quantity}] — prices resolved
    server-side from the site spec, never trusted from the client."""
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": currency.lower(),
                    "product_data": {"name": li["name"]},
                    "unit_amount": li["unit_amount_minor"],
                },
                "quantity": li["quantity"],
            }
            for li in line_items
        ],
        metadata={"order_id": order_id, "project_id": project_id},
        success_url=f"{BASE_URL}/site/{project_id}/success?order={order_id}",
        cancel_url=f"{BASE_URL}/site/{project_id}",
    )
    return session.url


def parse_webhook(payload: bytes, sig_header: str):
    """Returns the order_id of a completed checkout, or None.

    This endpoint is what turns an order into 'paid', so an unverified one is a
    free-food machine: anyone who can reach it could POST a fake
    checkout.session.completed. It therefore refuses to run unsigned unless we
    are explicitly in the local demo stub, where no real money exists.
    """
    import json

    secrets_ = webhook_secrets()
    if secrets_:
        # Verify with the SDK, then read the raw payload ourselves. construct_event
        # hands back a StripeObject, which is not a dict — .get() on it raises
        # AttributeError, which would 400 every genuine payment.
        for i, secret in enumerate(secrets_):
            try:
                stripe.Webhook.construct_event(payload, sig_header, secret)
                break
            except stripe.SignatureVerificationError:
                if i == len(secrets_) - 1:
                    raise  # none of the configured endpoints signed this
    elif not (DEMO_PAYMENTS and not STRIPE_SECRET_KEY):
        raise RuntimeError(
            "STRIPE_WEBHOOK_SECRET is not set — refusing to trust an unsigned webhook")

    event = json.loads(payload)
    if event.get("type") != "checkout.session.completed":
        return None
    return event.get("data", {}).get("object", {}).get("metadata", {}).get("order_id")
