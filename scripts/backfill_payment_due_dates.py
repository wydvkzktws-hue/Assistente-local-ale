"""
One-off: re-fetch each payment task's email via IMAP, parse a due date,
and set the task's due_at if found.

Run from repo root:
    python -m scripts.backfill_payment_due_dates [--dry-run]
"""
import email
import imaplib
import re
import sys
import urllib.parse
from datetime import date, datetime

from core.db import complete_task, get_db_connection, update_task
from integrations.email_sync import (
    _extract_body,
    _parse_due_date,
    load_config,
)


def extract_msg_id(description: str) -> str | None:
    if not description:
        return None
    m = re.search(r"\[gmail-link:[^\]]*rfc822msgid:([^\]]+)\]", description)
    if not m:
        return None
    return urllib.parse.unquote(m.group(1))


def fetch_payment_tasks_without_due():
    with get_db_connection() as conn:
        cur = conn.execute(
            "SELECT id, description FROM tasks "
            "WHERE due_at IS NULL "
            "  AND description LIKE '%[email-category:payment]%' "
            "  AND status != 'done'"
        )
        return cur.fetchall()


def main(dry_run: bool = False) -> int:
    cfg = load_config()
    if not cfg:
        print("Email not configured — abort.")
        return 1

    rows = fetch_payment_tasks_without_due()
    print(f"Found {len(rows)} payment tasks without a due date.")
    if not rows:
        return 0

    host = cfg.get("imap_host", "imap.gmail.com")
    mail = imaplib.IMAP4_SSL(host, 993)
    mail.login(cfg["email"], cfg["app_password"])
    mail.select("INBOX", readonly=True)

    updated = 0
    from_desc = 0
    auto_done = 0
    no_match = 0
    no_date = 0
    today = date.today()

    def apply(tid: int, due: str, source: str):
        nonlocal updated, auto_done
        due_date = datetime.fromisoformat(due).date()
        is_past = due_date < today
        marker = "  [DONE — past due]" if is_past else ""
        print(f"  task {tid}: {due}  ({source}){marker}")
        if not dry_run:
            update_task(tid, due_at=due)
            if is_past:
                complete_task(tid)
        updated += 1
        if is_past:
            auto_done += 1

    for tid, desc in rows:
        # 1) Try parsing the date directly from the stored description.
        due = _parse_due_date(desc or "")
        if due:
            apply(tid, due, "from description")
            from_desc += 1
            continue

        msg_id = extract_msg_id(desc)
        if not msg_id:
            no_date += 1
            continue

        # IMAP HEADER search; angle brackets included for accuracy
        search_id = msg_id if msg_id.startswith("<") else f"<{msg_id}>"
        typ, data = mail.search(None, "HEADER", "Message-ID", search_id)
        ids = data[0].split() if data and data[0] else []
        if not ids:
            # try other folders gmail uses
            for folder in ('"[Gmail]/All Mail"', "INBOX"):
                try:
                    mail.select(folder, readonly=True)
                    typ, data = mail.search(None, "HEADER", "Message-ID", search_id)
                    ids = data[0].split() if data and data[0] else []
                    if ids:
                        break
                except Exception:
                    continue
            mail.select("INBOX", readonly=True)
        if not ids:
            no_match += 1
            continue

        _, msg_data = mail.fetch(ids[-1], "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        subject = msg.get("Subject", "") or ""
        body = _extract_body(msg, max_chars=4000)
        due = _parse_due_date(subject + "\n" + body)
        if not due:
            no_date += 1
            continue

        apply(tid, due, "from IMAP")

    mail.logout()
    print(
        f"\nUpdated: {updated}  (from description: {from_desc}, auto-completed past-due: {auto_done})  "
        f"| not found in mailbox: {no_match}  | no due-date found: {no_date}"
    )
    if dry_run:
        print("(dry run — no DB changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
