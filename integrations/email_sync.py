import email
import imaplib
import json
import os
import re
import urllib.parse
from datetime import date, datetime
from email.header import decode_header
from typing import Optional

from core.db import create_task

DATA_DIR = os.path.expanduser("~/.assistant")
CONFIG_PATH = os.path.join(DATA_DIR, "email_config.json")
SEEN_IDS_PATH = os.path.join(DATA_DIR, "seen_email_ids.json")
MAX_SEEN = 2000  # cap so the file doesn't grow forever

# ── Email categories ──────────────────────────────────────────────────────────

NO_REPLY_PATTERNS = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "do_not_reply", "notifications@", "mailer-daemon", "automated@",
]

CATEGORIES = {
    "safety": {
        "keywords": [
            "safety", "segurança", "incident", "hazard", "accident",
            "emergency", "alert", "warning", "risk", "fire drill",
            "injury", "evacuation", "unsafe", "near miss", "near-miss",
            "ppe", "lockout", "tagout",
        ],
        "emoji": "🔴",
        "priority": "high",
    },
    "status_report": {
        "keywords": [
            "status report", "weekly report", "daily report", "monthly report",
            "progress update", "status update", "project update", "summary",
            "dashboard", "kpi", "metrics", "weekly update", "daily update",
            "end of day", "eod report", "standup notes",
            "diário de disponibilidade", "disponibilidade dos equipamentos",
        ],
        "sender_domains": ["varejo2led.com.br"],
        "emoji": "📊",
        "priority": "low",
    },
    "payment": {
        "keywords": [],
        "sender_domains": ["infocount.com.br", "infocount.com"],
        "emoji": "💳",
        "priority": "high",
    },
    "meeting": {
        "keywords": [
            "google meet", "meet.google.com", "join with google meet",
            "microsoft teams", "teams.microsoft.com", "join microsoft teams",
            "join a teams meeting", "teams meeting",
        ],
        "emoji": "📅",
        "priority": "medium",
    },
}


def _is_noreply(sender: str) -> bool:
    s = sender.lower()
    return any(p in s for p in NO_REPLY_PATTERNS)


def _categorize(subject: str, sender: str) -> Optional[tuple]:
    """Return (category_key, emoji, priority) or None to discard."""
    sender_l = sender.lower()
    subject_l = subject.lower()
    for cat_key, info in CATEGORIES.items():
        # Sender-domain check (used by payment category)
        if any(d in sender_l for d in info.get("sender_domains", [])):
            return cat_key, info["emoji"], info["priority"]
        # Keyword check against subject + sender
        text = subject_l + " " + sender_l
        if any(kw in text for kw in info.get("keywords", [])):
            return cat_key, info["emoji"], info["priority"]
    return None


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> Optional[dict]:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f)


# ── Seen-ID tracking ──────────────────────────────────────────────────────────

def _load_seen() -> set:
    try:
        with open(SEEN_IDS_PATH) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_seen(ids: set) -> None:
    # Keep only the most recent MAX_SEEN entries
    items = list(ids)[-MAX_SEEN:]
    with open(SEEN_IDS_PATH, "w") as f:
        json.dump(items, f)


# ── Email parsing helpers ─────────────────────────────────────────────────────

def _decode_header_str(raw: str) -> str:
    parts = decode_header(raw or "")
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(chunk))
    return "".join(out)


DUE_KEYWORDS = [
    "vencimento", "data de vencimento", "vence em", "vence no", "vence:", "vence ",
    "pagar até", "pague até", "pagamento até", "prazo de pagamento", "prazo:",
    "expira em", "expira:", "expira no",
    "due date", "due by", "due on", "due:",
    "payment due", "pay by",
]

DATE_PATTERNS = [
    # yyyy-mm-dd (most specific — must come before dm)
    (re.compile(r"\b(20\d{2})-([01]?\d)-([0-3]?\d)\b"),           "ymd"),
    # dd/mm/yyyy or dd-mm-yyyy or dd.mm.yyyy
    (re.compile(r"(\b[0-3]?\d)[/.\-]([01]?\d)[/.\-](20\d{2})\b"), "dmy"),
    # mm/yyyy — interpreted as last day of that month
    (re.compile(r"(\b[01]?\d)[/.\-](20\d{2})\b"),                 "my"),
    # dd/mm (no year)
    (re.compile(r"(\b[0-3]?\d)[/.\-]([01]?\d)\b(?!\d)"),          "dm"),
]


def _last_day(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days



def _parse_due_date(text: str) -> Optional[str]:
    """
    Scan text for a payment due date near a Portuguese/English keyword.
    Returns ISO datetime string (date at 09:00 local) or None.
    """
    if not text:
        return None
    low = text.lower()
    today = date.today()

    candidates = []
    for kw in DUE_KEYWORDS:
        start = 0
        while True:
            i = low.find(kw, start)
            if i < 0:
                break
            # Scan a window around the keyword: 40 chars before + 80 chars after.
            # This catches formats like "PA 05/2026 - vencimento" where the
            # date appears immediately before the keyword.
            w_start = max(0, i - 40)
            w_end = i + len(kw) + 80
            window = low[w_start:w_end]
            for rx, kind in DATE_PATTERNS:
                m = rx.search(window)
                if not m:
                    continue
                try:
                    if kind == "dmy":
                        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    elif kind == "ymd":
                        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    elif kind == "my":  # mm/yyyy → last day of that month
                        mm, yy = int(m.group(1)), int(m.group(2))
                        d = date(yy, mm, _last_day(yy, mm))
                    else:  # "dm" — assume current year, roll to next only if clearly past
                        dd, mm = int(m.group(1)), int(m.group(2))
                        d = date(today.year, mm, dd)
                        if (today - d).days > 30:
                            d = date(today.year + 1, mm, dd)
                except ValueError:
                    continue
                delta = (d - today).days
                if delta < -180 or delta > 730:
                    continue
                candidates.append(d)
                break  # first matching pattern in this window wins
            start = i + len(kw)

    if not candidates:
        return None
    # Prefer the earliest future date; if all are past, take the latest past one.
    future = sorted([c for c in candidates if c >= today])
    chosen = future[0] if future else sorted(candidates)[-1]
    return datetime(chosen.year, chosen.month, chosen.day, 9, 0, 0).isoformat(sep=" ")


def _extract_body(msg: email.message.Message, max_chars: int = 400) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                raw = part.get_payload(decode=True)
                if raw:
                    return raw.decode("utf-8", errors="replace").strip()[:max_chars]
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            return raw.decode("utf-8", errors="replace").strip()[:max_chars]
    return ""


# ── Main sync ─────────────────────────────────────────────────────────────────

def sync_emails(rescan: bool = False) -> dict:
    """
    Fetches emails and creates tasks. rescan=True searches ALL mail (not just
    UNSEEN) so already-read emails can be imported for the first time.
    Returns {'imported': int, 'error': str|None}.
    """
    cfg = load_config()
    if not cfg:
        return {"imported": 0, "error": "not_configured"}

    seen = _load_seen()
    imported = 0

    try:
        host = cfg.get("imap_host", "imap.gmail.com")
        mail = imaplib.IMAP4_SSL(host, 993)
        mail.login(cfg["email"], cfg["app_password"])
        mail.select("INBOX")

        search_criterion = "ALL" if rescan else "UNSEEN"
        _, data = mail.search(None, search_criterion)
        ids = data[0].split() if data[0] else []

        # Process newest-first, cap at 200 for rescan, 50 for normal
        cap = 200 if rescan else 50
        for eid in reversed(ids[-cap:]):
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw_msg = msg_data[0][1]
            msg = email.message_from_bytes(raw_msg)

            msg_id = (msg.get("Message-ID") or "").strip()
            if msg_id and msg_id in seen:
                continue

            subject = _decode_header_str(msg.get("Subject", "(no subject)"))
            sender  = _decode_header_str(msg.get("From", ""))

            if _is_noreply(sender):
                if msg_id:
                    seen.add(msg_id)
                continue

            cat = _categorize(subject, sender)
            if cat is None:
                if msg_id:
                    seen.add(msg_id)
                continue  # discard uncategorised email

            cat_key, cat_emoji, priority = cat

            # Payment emails: scan a larger body slice for a due date.
            scan_chars = 4000 if cat_key == "payment" else 400
            body_full = _extract_body(msg, max_chars=scan_chars)
            body = body_full[:400]

            due_at = None
            if cat_key == "payment":
                due_at = _parse_due_date(subject + "\n" + body_full)

            title = f"📧 {cat_emoji} {subject[:80]}"
            desc_lines = [f"[email-category:{cat_key}]"]
            if msg_id:
                safe_id = urllib.parse.quote(msg_id, safe='')
                desc_lines.append(f"[gmail-link:https://mail.google.com/mail/u/0/#search/rfc822msgid:{safe_id}]")
            desc_lines.append(f"From: {sender}")
            if body:
                desc_lines.append("")
                desc_lines.append(body)

            create_task(
                title=title,
                description="\n".join(desc_lines),
                priority=priority,
                due_at=due_at,
            )
            imported += 1

            if msg_id:
                seen.add(msg_id)

        mail.logout()
        _save_seen(seen)
        return {"imported": imported, "error": None}

    except imaplib.IMAP4.error as exc:
        return {"imported": 0, "error": f"IMAP auth error: {exc}"}
    except Exception as exc:
        return {"imported": 0, "error": str(exc)}


def test_connection(email_addr: str, app_password: str, imap_host: str = "imap.gmail.com") -> dict:
    """Quick connectivity check without importing anything."""
    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993)
        mail.login(email_addr, app_password)
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        unread = len(data[0].split()) if data[0] else 0
        mail.logout()
        return {"ok": True, "unread": unread}
    except imaplib.IMAP4.error as exc:
        return {"ok": False, "error": f"IMAP auth error — check your App Password. ({exc})"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
