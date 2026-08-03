#!/usr/bin/env python3
"""Hourly snapshot of the restaurant database.

Uses SQLite's own backup API rather than copying the file: a plain cp of a
live database can capture a half-written transaction and restore as corrupt.
The sqlite3 CLI is not installed on this box, so this does it in Python.
"""
import gzip
import shutil
import sqlite3
import time
from pathlib import Path

SRC = Path.home() / "vibe-business-llm" / "data" / "vibe.db"
DEST = Path.home() / "backups" / "vibe"
KEEP_HOURLY = 48          # two days of hourly snapshots
KEEP_DAILY = 30           # a month of dailies

DEST.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d-%H%M")
tmp = DEST / f"vibe-{stamp}.db"

src = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
dst = sqlite3.connect(tmp)
with dst:
    src.backup(dst)          # consistent even while the app is writing
dst.close(); src.close()

with open(tmp, "rb") as f_in, gzip.open(f"{tmp}.gz", "wb") as f_out:
    shutil.copyfileobj(f_in, f_out)
tmp.unlink()

# A backup nobody ever restores is a rumour. Verify this one opens and has rows.
import io
with gzip.open(f"{tmp}.gz", "rb") as f:
    check = DEST / "_verify.db"
    check.write_bytes(f.read())
conn = sqlite3.connect(check)
orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
conn.close(); check.unlink()
print(f"{stamp}  ok  {projects} projects, {orders} orders")

hourly = sorted(DEST.glob("vibe-*.db.gz"))
for old in hourly[:-KEEP_HOURLY]:
    # keep one per day before deleting the rest
    if not old.name.endswith("0300.db.gz"):
        old.unlink()
dailies = sorted(DEST.glob("vibe-*0300.db.gz"))
for old in dailies[:-KEEP_DAILY]:
    old.unlink()
