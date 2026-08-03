"""Tests get their own throwaway database.

Without this, importing app.main ran init_db() against data/vibe.db and every
test run left junk projects and orders in the restaurant's real data — and once
order numbers are per-day sequences, test orders would burn real numbers too.
"""

import tempfile
from pathlib import Path

# Redirect the DB before app.main is imported anywhere: app.main calls
# db.init_db() at import time.
from app import auth, db

_tmp = tempfile.TemporaryDirectory()
db.DB_PATH = Path(_tmp.name) / "test.db"

# Staff screens fail closed without a password, so tests need one set. Anything
# that must work for a guest is verified without logging in.
auth.STAFF_PASSWORD = "test-staff-pw"
