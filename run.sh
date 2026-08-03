#!/usr/bin/env bash
# Release Yan Liu — start the Vibe Business server on the restaurant's Mac mini.
# Binds to 0.0.0.0 so the iPads and Apple TV on the same wifi can reach it.
set -e
cd "$(dirname "$0")"

PORT=${PORT:-8100}

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

[ -f .env ] || touch .env

# The staff screens fail closed without a password, and "I'll set it later" is
# how a kitchen display ends up on the open internet. Generate one on first run.
if ! grep -q '^VIBE_STAFF_PASSWORD=' .env; then
  GENERATED=$(LC_ALL=C tr -dc 'a-z2-9' < /dev/urandom | head -c 12)
  printf '\nVIBE_STAFF_PASSWORD=%s\n' "$GENERATED" >> .env
  echo ""
  echo "  ┌───────────────────────────────────────────────┐"
  echo "  │  Staff password generated (saved in .env):    │"
  echo "  │      $GENERATED                             │"
  echo "  │  Each staff iPad logs in once with this.      │"
  echo "  └───────────────────────────────────────────────┘"
fi

# Load .env (STRIPE_SECRET_KEY, VIBE_STAFF_PASSWORD, VIBE_MODEL, etc.)
set -a && . ./.env && set +a

if [ -n "$STRIPE_SECRET_KEY" ] && [ -z "$STRIPE_WEBHOOK_SECRET" ]; then
  echo ""
  echo "  ⚠️  STRIPE_WEBHOOK_SECRET is not set. Online payments will be taken but"
  echo "     never confirmed, so those orders will never reach the kitchen."
fi

# "[errno 48] address already in use" tells you nothing useful at 18:00 on a
# Friday. Name the process that has the port, so you know what to stop.
BUSY=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)
if [ -n "$BUSY" ]; then
  echo ""
  echo "  Port $PORT is already in use by PID $BUSY:"
  ps -o pid=,command= -p "$BUSY" | sed 's/^/    /'
  echo ""
  echo "  If that is an older copy of this server, stop it with:  kill $BUSY"
  echo "  Then run ./run.sh again."
  exit 1
fi

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<mac-mini-ip>")
echo ""
echo "  Vibe Business is starting."
echo "  On the iPads / Apple TV, open:  http://$IP:$PORT/panel/<project-id>"
echo ""
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
