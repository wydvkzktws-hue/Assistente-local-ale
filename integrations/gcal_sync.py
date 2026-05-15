"""Google Calendar one-way push sync.

Reuses the email account (same Google identity) but requires OAuth2 — IMAP app
passwords don't work with the Calendar API.

Setup:
  1. Create OAuth2 client (Desktop app) in Google Cloud Console.
  2. Download credentials.json to ~/.assistant/gcal_credentials.json.
  3. Call begin_auth() once — opens a browser, stores token at
     ~/.assistant/gcal_token.json.
  4. Subsequent syncs auto-refresh.

Mapping:
  pending tasks with due_at  →  Calendar events (30 min default).
  task title / description    →  event summary / description.
  task.gcal_event_id          ←  Calendar event id (idempotent push/update).
  task marked done            →  event deleted on next sync.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from core.db import (get_done_tasks_with_gcal, get_tasks_for_gcal_sync,
                     set_gcal_event_id)

DATA_DIR = os.path.expanduser("~/.assistant")
CREDENTIALS_PATH = os.path.join(DATA_DIR, "gcal_credentials.json")
TOKEN_PATH = os.path.join(DATA_DIR, "gcal_token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Pull a Meet/Teams/Zoom URL out of an email-derived description, if present.
_MEET_URL_RX = re.compile(
    r"https?://(?:meet\.google\.com/[a-z0-9\-?=]+"
    r"|teams\.microsoft\.com/l/meetup-join/[^\s]+"
    r"|teams\.live\.com/meet/[^\s]+"
    r"|[a-z0-9.\-]*zoom\.us/j/\d+[^\s]*)",
    re.IGNORECASE,
)


def _lazy_imports():
    """Imported lazily so the rest of the app runs without google libs installed."""
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    return Request, Credentials, InstalledAppFlow, build, HttpError


def is_configured() -> bool:
    return os.path.exists(CREDENTIALS_PATH)


def is_connected() -> bool:
    return os.path.exists(TOKEN_PATH)


def _load_creds():
    Request, Credentials, InstalledAppFlow, _build, _HttpError = _lazy_imports()
    if not os.path.exists(TOKEN_PATH):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def begin_auth() -> dict:
    """Run the local-server OAuth flow. Blocks until user consents in browser."""
    if not os.path.exists(CREDENTIALS_PATH):
        return {
            "ok": False,
            "error": (
                f"Missing {CREDENTIALS_PATH}. Create an OAuth2 Desktop client in "
                "Google Cloud Console and save the JSON there."
            ),
        }
    try:
        _Request, _Credentials, InstalledAppFlow, _build, _HttpError = _lazy_imports()
    except ImportError as exc:
        return {"ok": False, "error": f"google libs missing: {exc}"}

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    return {"ok": True}


def disconnect() -> None:
    try:
        os.remove(TOKEN_PATH)
    except FileNotFoundError:
        pass


def _build_service():
    _Request, _Credentials, _Flow, build, _HttpError = _lazy_imports()
    creds = _load_creds()
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _extract_meet_url(description: str) -> Optional[str]:
    if not description:
        return None
    m = _MEET_URL_RX.search(description)
    return m.group(0) if m else None


def _event_payload(title: str, description: str, due_at: str, priority: str) -> dict:
    start = datetime.fromisoformat(due_at)
    end = start + timedelta(minutes=30)
    payload = {
        "summary": title,
        "description": description or "",
        "start": {"dateTime": start.isoformat(), "timeZone": "America/Sao_Paulo"},
        "end":   {"dateTime": end.isoformat(),   "timeZone": "America/Sao_Paulo"},
        "reminders": {"useDefault": True},
    }
    # Color coding by priority: 11=red, 5=yellow, 8=grey
    payload["colorId"] = {"high": "11", "medium": "5", "low": "8"}.get(priority, "5")
    meet_url = _extract_meet_url(description)
    if meet_url:
        payload["location"] = meet_url
    return payload


def sync_to_calendar() -> dict:
    """Push pending tasks to Calendar; remove events for completed tasks.

    Returns {'created': int, 'updated': int, 'deleted': int, 'error': str|None}.
    """
    if not is_configured():
        return {"created": 0, "updated": 0, "deleted": 0, "error": "not_configured"}
    if not is_connected():
        return {"created": 0, "updated": 0, "deleted": 0, "error": "not_connected"}

    try:
        _R, _C, _F, _B, HttpError = _lazy_imports()
    except ImportError as exc:
        return {"created": 0, "updated": 0, "deleted": 0, "error": f"google libs missing: {exc}"}

    svc = _build_service()
    if svc is None:
        return {"created": 0, "updated": 0, "deleted": 0, "error": "auth_invalid"}

    created = updated = deleted = 0
    errors: list[str] = []

    # 1. Push/refresh pending tasks
    for row in get_tasks_for_gcal_sync():
        task_id, title, description, due_at, priority, _recurrence, gcal_event_id = row
        try:
            body = _event_payload(title, description or "", due_at, priority)
            if gcal_event_id:
                svc.events().update(
                    calendarId="primary", eventId=gcal_event_id, body=body
                ).execute()
                updated += 1
            else:
                resp = svc.events().insert(calendarId="primary", body=body).execute()
                set_gcal_event_id(task_id, resp["id"])
                created += 1
        except HttpError as exc:
            # Event was deleted on Google's side — recreate.
            if gcal_event_id and exc.resp.status in (404, 410):
                try:
                    resp = svc.events().insert(calendarId="primary", body=body).execute()
                    set_gcal_event_id(task_id, resp["id"])
                    created += 1
                    continue
                except HttpError as exc2:
                    errors.append(f"task {task_id}: {exc2}")
            else:
                errors.append(f"task {task_id}: {exc}")
        except Exception as exc:
            errors.append(f"task {task_id}: {exc}")

    # 2. Delete events for tasks that got marked done
    for task_id, event_id in get_done_tasks_with_gcal():
        try:
            svc.events().delete(calendarId="primary", eventId=event_id).execute()
            deleted += 1
        except HttpError as exc:
            if exc.resp.status not in (404, 410):
                errors.append(f"task {task_id} delete: {exc}")
        except Exception as exc:
            errors.append(f"task {task_id} delete: {exc}")
        set_gcal_event_id(task_id, None)

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "error": "; ".join(errors) if errors else None,
    }


def delete_event(event_id: str) -> None:
    """Best-effort delete of a single Calendar event. Silent on failure."""
    if not event_id or not is_connected():
        return
    try:
        svc = _build_service()
        if svc is None:
            return
        svc.events().delete(calendarId="primary", eventId=event_id).execute()
    except Exception:
        pass


def status() -> dict:
    return {
        "configured": is_configured(),
        "connected": is_connected(),
        "credentials_path": CREDENTIALS_PATH,
    }
