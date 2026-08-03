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

# Relative to this file, not to $HOME — the repo sits at ~/vibe-business-llm on
# the server and ~/Projects/vibe-business-llm on the Mac, and a backup script
# that only works in one of them is a backup script that fails when you need it.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "vibe.db"
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

# Off-site: same-disk snapshots survive a bad deploy, not a dead machine.
# No-ops silently when R2 isn't configured, so the local backup never fails
# because of a credential problem.
def upload_to_r2(path: Path) -> str:
    import os
    account = os.environ.get("R2_ACCOUNT_ID", "")
    key_id = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    bucket = os.environ.get("R2_BUCKET", "")
    if not all([account, key_id, secret, bucket]):
        return "r2 not configured"
    try:
        import boto3
    except ImportError:
        return "r2 skipped (boto3 not installed)"
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name="auto",
        )
        s3.upload_file(str(path), bucket, f"vibe/{path.name}")
        return f"uploaded to r2://{bucket}/vibe/{path.name}"
    except Exception as e:
        # Never let an off-site failure hide the fact that the local one worked.
        return f"r2 FAILED: {type(e).__name__}: {e}"


print("   ", upload_to_r2(Path(f"{tmp}.gz")))

hourly = sorted(DEST.glob("vibe-*.db.gz"))
for old in hourly[:-KEEP_HOURLY]:
    # keep one per day before deleting the rest
    if not old.name.endswith("0300.db.gz"):
        old.unlink()
dailies = sorted(DEST.glob("vibe-*0300.db.gz"))
for old in dailies[:-KEEP_DAILY]:
    old.unlink()
