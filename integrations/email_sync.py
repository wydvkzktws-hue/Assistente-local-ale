import email
import imaplib
import json
import os
import re
import urllib.parse
from datetime import date, datetime
from email.header import decode_header
from email.utils import parseaddr
from typing import Optional

from core.db import create_task
from integrations.notify import send_notification

DATA_DIR = os.path.expanduser("~/.assistant")
CONFIG_PATH = os.path.join(DATA_DIR, "email_config.json")
SEEN_IDS_PATH = os.path.join(DATA_DIR, "seen_email_ids.json")
MAX_SEEN = 2000  # cap so the file doesn't grow forever

# ── Email categories ──────────────────────────────────────────────────────────

URGENT_KEYWORDS = [
    "urgente", "urgent", "urgência", "urgencia",
    "asap", "imediato", "imediata", "immediately",
    "prioritário", "prioritario", "prioridade alta",
    "critical", "crítico", "critico",
    "atenção urgente", "atencao urgente",
]


def _is_urgent(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in URGENT_KEYWORDS)


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
            "invitation:", "updated invitation:", "convite:", "convite atualizado:",
            "invited you to", "convidou você", "convidou voce",
            "accepted:", "declined:", "tentatively accepted:",
            "calendar invitation", "convite de calendário", "convite de calendario",
        ],
        "sender_domains": [
            "calendar-notification@google.com",
            "calendar-server.bounces.google.com",
        ],
        "emoji": "📅",
        "priority": "medium",
    },
}


def _is_noreply(sender: str) -> bool:
    s = sender.lower()
    return any(p in s for p in NO_REPLY_PATTERNS)


# Body-only meeting signals: Meet/Teams/Zoom URLs, "convite" anywhere,
# and date+time patterns (DD/MM[/YYYY] HH:MM  or  YYYY-MM-DD HH:MM).
MEETING_URL_RX = re.compile(
    r"(meet\.google\.com/[a-z0-9\-]+|teams\.microsoft\.com/l/meetup-join|"
    r"teams\.live\.com/meet/|zoom\.us/j/\d+)",
    re.IGNORECASE,
)
MEETING_CONVITE_RX = re.compile(r"\bconvite\b", re.IGNORECASE)
MEETING_DATETIME_RX = re.compile(
    r"\b("
    r"[0-3]?\d[/.\-][01]?\d(?:[/.\-]20\d{2})?\s+[0-2]?\d:[0-5]\d"  # 10/05 14:30 or 10/05/2026 14:30
    r"|20\d{2}-[01]?\d-[0-3]?\d\s+[0-2]?\d:[0-5]\d"               # 2026-05-10 14:30
    r")\b"
)


def _looks_like_meeting_body(text: str) -> bool:
    if not text:
        return False
    if MEETING_URL_RX.search(text):
        return True
    if MEETING_CONVITE_RX.search(text):
        return True
    if MEETING_DATETIME_RX.search(text):
        return True
    return False


def _categorize(subject: str, sender: str, body: str = "") -> Optional[tuple]:
    """Return (category_key, emoji, priority) or None to discard.

    `body` is an optional snippet used as a fallback for the meeting category
    only — picks up Google Meet links, "convite" mentions, and date+time
    patterns that don't appear in the subject line.
    """
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
    # Body-fallback for meetings only.
    if body and _looks_like_meeting_body(body):
        info = CATEGORIES["meeting"]
        return "meeting", info["emoji"], info["priority"]
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

def _parse_fetch_response(data) -> list:
    """imaplib fetch with multiple IDs returns a flat list interleaving tuples
    and b')'. Pull out the (meta, payload) tuples in order."""
    out = []
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            out.append(item[1])
    return out


def sync_emails(rescan: bool = False) -> dict:
    """
    Fetches emails and creates tasks. rescan=True searches ALL mail (not just
    UNSEEN) so already-read emails can be imported for the first time.
    Returns {'imported': int, 'error': str|None}.

    Speed strategy:
      1. Batch-fetch headers only (Message-ID/Subject/From) for all candidates
         in one IMAP round-trip.
      2. Filter out already-seen IDs without ever pulling their body.
      3. Categorize by header; drop noreply only if header didn't categorize.
      4. Fetch full body only for survivors (one IMAP call per survivor).
    """
    cfg = load_config()
    if not cfg:
        return {"imported": 0, "error": "not_configured"}

    seen = _load_seen()
    imported = 0
    urgent_items: list = []  # [{'task_id': int, 'subject': str, 'sender': str}, ...]

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
        batch_ids = list(reversed(ids[-cap:]))
        if not batch_ids:
            mail.logout()
            return {"imported": 0, "urgent": [], "error": None}

        # ── Phase 1: one IMAP fetch for headers + first 16KB body ─────────
        # Partial-message fetch gives us everything needed to classify
        # (including Meet links and "convite" mentions buried in the body)
        # without a second round-trip per message.
        id_set = b",".join(batch_ids)
        _, hdr_data = mail.fetch(id_set, "(BODY.PEEK[]<0.16384>)")

        candidates = []  # [(eid, msg_id, subject, sender, snippet_msg)]
        idx = 0
        for item in hdr_data:
            if not (isinstance(item, tuple) and len(item) >= 2):
                continue
            meta = item[0]
            payload = item[1]
            try:
                eid = meta.split(b" ", 1)[0]
            except Exception:
                eid = batch_ids[idx] if idx < len(batch_ids) else b""
            idx += 1
            try:
                snippet_msg = email.message_from_bytes(payload)
            except Exception:
                continue
            msg_id = (snippet_msg.get("Message-ID") or "").strip()
            if msg_id and msg_id in seen:
                continue
            subject = _decode_header_str(snippet_msg.get("Subject", "(no subject)"))
            sender = _decode_header_str(snippet_msg.get("From", ""))
            candidates.append((eid, msg_id, subject, sender, snippet_msg))

        # ── Phase 2: categorize using snippet; refetch full only if needed ─
        for eid, msg_id, subject, sender, snippet_msg in candidates:
            content_type = (snippet_msg.get("Content-Type") or "").lower()
            snippet_body = _extract_body(snippet_msg, max_chars=8000)

            cat = _categorize(subject, sender, body=snippet_body)

            # text/calendar parts → meeting, even if nothing else matched
            if cat is None and "text/calendar" in content_type:
                cat = ("meeting", CATEGORIES["meeting"]["emoji"], "medium")

            # Drop noreply only when nothing categorized it. Legitimate
            # senders like calendar-notification@google.com must survive.
            if cat is None:
                if msg_id:
                    seen.add(msg_id)
                continue  # uncategorised → discard

            cat_key, cat_emoji, priority = cat

            # For payment we may need more body to find the due date; refetch
            # full message only when the snippet didn't already contain one.
            if cat_key == "payment":
                body_full = snippet_body
                if not _parse_due_date(subject + "\n" + body_full):
                    _, msg_data = mail.fetch(eid, "(RFC822)")
                    try:
                        raw_msg = msg_data[0][1]
                        full_msg = email.message_from_bytes(raw_msg)
                        body_full = _extract_body(full_msg, max_chars=4000)
                    except Exception:
                        pass
            else:
                body_full = snippet_body[:1000]
            body = body_full[:400]

            is_urgent_msg = _is_urgent(subject + "\n" + body_full)
            if is_urgent_msg:
                priority = "high"

            due_at = None
            if cat_key == "payment":
                due_at = _parse_due_date(subject + "\n" + body_full)

            title = f"📧 {cat_emoji} {subject[:80]}"
            desc_lines = [f"[email-category:{cat_key}]"]
            if msg_id:
                safe_id = urllib.parse.quote(msg_id, safe='')
                desc_lines.append(f"[gmail-link:https://mail.google.com/mail/u/0/#search/rfc822msgid:{safe_id}]")
            if cat_key == "meeting":
                _, sender_addr = parseaddr(sender)
                if msg_id:
                    desc_lines.append(f"[email-msgid:{msg_id}]")
                if sender_addr:
                    desc_lines.append(f"[email-sender-addr:{sender_addr}]")
                desc_lines.append(f"[email-subject:{subject}]")
            desc_lines.append(f"From: {sender}")
            if body:
                desc_lines.append("")
                desc_lines.append(body)

            task_id = create_task(
                title=title,
                description="\n".join(desc_lines),
                priority=priority,
                due_at=due_at,
            )
            imported += 1

            if is_urgent_msg and not rescan:
                urgent_items.append({
                    "task_id": task_id,
                    "subject": subject[:80],
                    "sender": sender,
                })
                # Fire a desktop notification right away for urgent emails.
                try:
                    send_notification(
                        title=f"🚨 Urgent email: {subject[:60]}",
                        body=f"From: {sender}",
                        task_id=task_id,
                    )
                except Exception:
                    pass  # never let a notification failure abort the sync

            if msg_id:
                seen.add(msg_id)

        mail.logout()
        _save_seen(seen)
        return {"imported": imported, "urgent": urgent_items, "error": None}

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
