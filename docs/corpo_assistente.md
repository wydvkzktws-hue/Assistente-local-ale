You are an expert Python developer. Build a fully local personal assistant CLI application that manages to-dos and sends desktop reminders. The app must run entirely offline on macOS/Linux/Windows with no cloud dependencies.

---

## WHAT TO BUILD

A command-line personal assistant with the following capabilities:

1. **Add tasks** — title, optional description, due date/time, priority (low/medium/high), optional recurrence (daily/weekly/monthly)
2. **List tasks** — filter by status (pending/done/overdue), priority, or due date
3. **Complete tasks** — mark one or multiple tasks as done
4. **Delete tasks** — remove tasks by ID
5. **Edit tasks** — update any field of an existing task
6. **Reminders** — a background daemon that checks due tasks and fires native desktop notifications
7. **Snooze** — postpone a reminder by N minutes from the notification itself (or via CLI)
8. **Recurring tasks** — automatically recreate the task after completion based on recurrence rule

---

## TECHNICAL REQUIREMENTS

### Stack
- **Language:** Python 3.10+
- **Storage:** SQLite via the built-in `sqlite3` module (single file `~/.assistant/tasks.db`)
- **CLI:** `argparse` or `click` — your choice, but commands must be intuitive
- **Notifications:**
  - macOS → `osascript` (AppleScript) via `subprocess`
  - Linux → `notify-send` via `subprocess`
  - Windows → `plyer` library (only external dep allowed for notifications)
- **Daemon:** A lightweight background process using Python's `schedule` library + `subprocess.Popen` to detach it; store its PID in `~/.assistant/daemon.pid`
- **No LLMs, no APIs, no internet calls**

### Project structure
```
assistant/
├── main.py          # CLI entry point
├── db.py            # SQLite schema + CRUD functions
├── reminder.py      # Daemon loop that polls DB and fires notifications
├── notify.py        # Cross-platform notification dispatcher
├── recurrence.py    # Logic for computing next due date from recurrence rule
└── requirements.txt # Only list external deps (plyer if needed, schedule)
```

### Database schema
Table `tasks`:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `title` TEXT NOT NULL
- `description` TEXT
- `due_at` TEXT (ISO 8601 datetime, nullable)
- `priority` TEXT CHECK(priority IN ('low','medium','high')) DEFAULT 'medium'
- `status` TEXT CHECK(status IN ('pending','done','snoozed')) DEFAULT 'pending'
- `recurrence` TEXT (nullable — 'daily'|'weekly'|'monthly')
- `created_at` TEXT (ISO 8601)
- `updated_at` TEXT (ISO 8601)
- `snoozed_until` TEXT (ISO 8601, nullable)

### CLI commands
```
python main.py add "Buy groceries" --due "2024-12-01 10:00" --priority high --recur weekly
python main.py list
python main.py list --filter overdue
python main.py list --priority high
python main.py done 3
python main.py edit 3 --due "2024-12-05 09:00"
python main.py delete 3
python main.py snooze 3 --minutes 30
python main.py daemon start   # launch background reminder process
python main.py daemon stop    # kill daemon by PID
python main.py daemon status  # show if daemon is running
```

### Reminder daemon behavior
- Poll the DB every 60 seconds
- Fire a notification for any task where `status = 'pending'` AND `due_at <= now` AND (`snoozed_until` IS NULL OR `snoozed_until <= now`)
- After firing, set `status = 'snoozed'` and `snoozed_until = now + 10 minutes` to avoid spam — the user can re-snooze or mark done
- For recurring tasks: when user marks done, call `recurrence.py` to compute the next `due_at` and insert a new identical task with `status = 'pending'`

### Notification format
```
Title: [PRIORITY] Task title
Body:  Due: <human-readable datetime>
       ID: <task_id>  |  snooze: python main.py snooze <id> --minutes 30
```

---

## CODE QUALITY REQUIREMENTS

- All functions must have type hints
- Use `datetime` from stdlib for all date math — no `dateutil`
- Handle the case where `due_at` is None (tasks with no deadline are never reminded)
- On `daemon start`, check if PID file already exists and warn the user instead of spawning a second daemon
- Graceful shutdown: daemon catches `SIGTERM` / `KeyboardInterrupt` and exits cleanly
- `db.py` must use context managers (`with sqlite3.connect(...) as conn`) — no bare connections
- Print task lists as aligned ASCII tables (use `str.ljust` / `str.rjust`, no external table libraries)

---

## DELIVERABLES

Produce the complete, runnable source code for every file listed in the project structure. Each file should be self-contained and importable. After the code, include a short **Setup & Usage** section with:
1. How to install dependencies (`pip install -r requirements.txt`)
2. How to add a first task
3. How to start the daemon
4. Where the DB file lives

Do not truncate any file. Write the full implementation.
