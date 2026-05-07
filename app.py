import json
import queue
import schedule
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

from db import (complete_task, create_task, delete_task, get_pending_tasks,
                get_task, init_db, list_tasks, snooze_task, update_task)
from email_sync import load_config, save_config, sync_emails, test_connection
from notify import send_notification
from recurrence import calculate_next_due_date

app = Flask(__name__)
init_db()

_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()


def _push_to_clients(event: dict) -> None:
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def _task_to_dict(task: tuple) -> dict:
    task_id, title, description, due_at, priority, status, recurrence, created_at, updated_at, snoozed_until = task
    return {
        "id": task_id,
        "title": title,
        "description": description,
        "due_at": due_at,
        "priority": priority,
        "status": status,
        "recurrence": recurrence,
        "created_at": created_at,
        "updated_at": updated_at,
        "snoozed_until": snoozed_until,
    }


_last_email_sync: dict = {"imported": 0, "error": None, "at": None}


def _run_email_sync() -> None:
    global _last_email_sync
    result = sync_emails()
    result["at"] = datetime.now().isoformat(timespec="seconds")
    _last_email_sync = result
    if result["imported"] > 0:
        n = result["imported"]
        _push_to_clients({"type": "email_sync", "imported": n})
        send_notification("New email tasks", f"{n} unread email{'s' if n > 1 else ''} added as task{'s' if n > 1 else ''}.", 0)


def _fire_daily_checkin() -> None:
    """Runs at 11am. Pushes overdue tasks + opens check-in in the browser."""
    overdue = list_tasks(filter_by="overdue")
    overdue_dicts = [_task_to_dict(t) for t in overdue]

    _push_to_clients({"type": "daily_checkin", "overdue_tasks": overdue_dicts})

    if overdue_dicts:
        body = f"You have {len(overdue_dicts)} unfinished task(s). Time to review!"
    else:
        body = "Good morning! Time to plan your day."
    send_notification("Daily Check-in", body, 0)


def _notification_loop() -> None:
    schedule.every().day.at("11:00").do(_fire_daily_checkin)
    schedule.every(5).minutes.do(_run_email_sync)

    while True:
        try:
            schedule.run_pending()
            tasks = get_pending_tasks()
            for task in tasks:
                task_id, title, _, due_at, priority, *_ = task
                title_text = f"[{priority.upper()}] {title}"
                body_text = (
                    f"Due: {datetime.fromisoformat(due_at).strftime('%Y-%m-%d %H:%M')}"
                    if due_at else "No due date"
                )
                _push_to_clients({"type": "reminder", "id": task_id, "title": title_text, "body": body_text})
                send_notification(title_text, body_text, task_id)
                snooze_until = (datetime.now() + timedelta(minutes=10)).isoformat()
                update_task(task_id, snoozed_until=snooze_until)
        except Exception as exc:
            print(f"Notification loop error: {exc}", file=sys.stderr)
        time.sleep(60)


threading.Thread(target=_notification_loop, daemon=True, name="notification-loop").start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    q: queue.Queue = queue.Queue(maxsize=20)
    with _clients_lock:
        _clients.append(q)

    def generate():
        try:
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/checkin", methods=["GET"])
def api_checkin():
    """Returns overdue tasks for the manual check-in trigger."""
    overdue = list_tasks(filter_by="overdue")
    return jsonify([_task_to_dict(t) for t in overdue])


@app.route("/api/tasks", methods=["GET"])
def api_list_tasks():
    tasks = list_tasks(
        filter_by=request.args.get("filter"),
        priority=request.args.get("priority"),
        due_date=request.args.get("due"),
    )
    return jsonify([_task_to_dict(t) for t in tasks])


@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    data = request.get_json(force=True)
    task_id = create_task(
        title=data["title"],
        description=data.get("description"),
        due_at=data.get("due_at"),
        priority=data.get("priority", "medium"),
        recurrence=data.get("recurrence"),
    )
    return jsonify({"id": task_id}), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id: int):
    data = request.get_json(force=True)
    allowed = {"title", "description", "due_at", "priority", "recurrence"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if fields:
        update_task(task_id, **fields)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id: int):
    delete_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/done", methods=["POST"])
def api_complete_task(task_id: int):
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "Not found"}), 404
    _, title, description, due_at, priority, _, recurrence, *_ = task
    if recurrence:
        next_due = calculate_next_due_date(due_at, recurrence)
        if next_due:
            create_task(
                title=title, description=description,
                due_at=next_due, priority=priority, recurrence=recurrence,
            )
    complete_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/snooze", methods=["POST"])
def api_snooze_task(task_id: int):
    data = request.get_json(force=True) or {}
    minutes = int(data.get("minutes", 30))
    snooze_task(task_id, minutes)
    return jsonify({"ok": True})


@app.route("/api/email/config", methods=["GET"])
def api_email_config_get():
    cfg = load_config()
    if not cfg:
        return jsonify({"configured": False})
    return jsonify({
        "configured": True,
        "email": cfg.get("email", ""),
        "imap_host": cfg.get("imap_host", "imap.gmail.com"),
    })


@app.route("/api/email/config", methods=["POST"])
def api_email_config_save():
    data = request.get_json(force=True)
    cfg = {
        "email": data["email"],
        "app_password": data["app_password"],
        "imap_host": data.get("imap_host", "imap.gmail.com"),
    }
    result = test_connection(cfg["email"], cfg["app_password"], cfg["imap_host"])
    if not result["ok"]:
        return jsonify({"ok": False, "error": result["error"]}), 400
    save_config(cfg)
    return jsonify({"ok": True, "unread": result["unread"]})


@app.route("/api/email/sync", methods=["POST"])
def api_email_sync():
    _run_email_sync()
    return jsonify(_last_email_sync)


@app.route("/api/email/status", methods=["GET"])
def api_email_status():
    cfg = load_config()
    return jsonify({**_last_email_sync, "configured": cfg is not None})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
