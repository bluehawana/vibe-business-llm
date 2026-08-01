#!/usr/bin/env bash
# Release Yan Liu — start the Vibe Business server on the restaurant's Mac mini.
# Binds to 0.0.0.0 so the iPads and Apple TV on the same wifi can reach it.
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

# Load .env if present (STRIPE_SECRET_KEY, VIBE_MODEL, etc.)
[ -f .env ] && set -a && . ./.env && set +a

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<mac-mini-ip>")
echo ""
echo "  Vibe Business is starting."
echo "  On the iPads / Apple TV, open:  http://$IP:8100/panel/<project-id>"
echo ""
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
