# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

Run all commands from the repo root so package imports resolve.

```bash
# Install dependencies
pip install -r requirements.txt

# Start the web UI (Flask, port 5050)
python -m web.app

# CLI task management
python -m cli.main add "Task title" --due "2026-05-10 09:00" --priority high
python -m cli.main list
python -m cli.main done <id>
python -m cli.main snooze <id> --until "2026-05-11 08:00"

# Background notification daemon
python -m cli.main daemon start
python -m cli.main daemon stop
python -m cli.main daemon status
```

There is no test suite, no linting config, and no Makefile.

## Layout

```
core/           db.py, recurrence.py        — shared data + pure logic
integrations/   email_sync.py, notify.py, reminder.py
web/            app.py, templates/index.html
cli/            main.py
docs/           CLAUDE.md, corpo_assistente.md
```

## Architecture

Two entry points share the same `core.db` layer:

- **`web.app`** — Flask web server serving a single-page app (`web/templates/index.html`). Exposes REST endpoints under `/api/tasks` and `/api/email`, plus a Server-Sent Events stream at `/stream` for real-time updates. Also runs the notification loop as a background daemon thread.
- **`cli.main`** — CLI with argparse subcommands for the same task operations.

### Data Layer (`core/db.py`)

SQLite at `~/.assistant/tasks.db`. Single `tasks` table; all dates stored as ISO 8601 strings. Provides `create_task`, `get_task`, `list_tasks`, `update_task`, `delete_task`, `complete_task`, `snooze_task`, `get_pending_tasks`. Also manages a PID file at `~/.assistant/daemon.pid`.

### Email Integration (`integrations/email_sync.py`)

Connects to IMAP (default: `imap.gmail.com`) using credentials in `~/.assistant/email_config.json`. Classifies emails into four categories: **Safety** (high), **Payment** (high), **Meeting** (medium), **Status Report** (low). No-reply senders are blocked. Seen email IDs are cached in `~/.assistant/seen_email_ids.json` (capped at 2000) to avoid duplicate tasks.

### Notifications

- **`integrations/notify.py`** — Platform dispatcher: `osascript` on macOS, `notify-send` on Linux, `plyer` on Windows.
- **`integrations/reminder.py`** — Detached daemon that polls `get_pending_tasks()` every 60 seconds and triggers notifications. Launched via `python -m integrations.reminder` by the CLI daemon command.

### Recurrence (`core/recurrence.py`)

`calculate_next_due_date(due_at, recurrence)` computes the next date for `daily`/`weekly`/`monthly` tasks after completion. Handles the Feb 29 → Feb 28 edge case.

### Frontend (`web/templates/index.html`)

Single large HTML file with inline CSS and JavaScript — Catppuccin dark theme, task list, email config panel, and check-in modal. Email tasks are grouped by sender (collapsible) in both list and kanban views; expansion state persists in `localStorage` under `emailGroupOpen`. All API calls go to the Flask server.

## Key File Locations

| Purpose | Path |
|---|---|
| SQLite database | `~/.assistant/tasks.db` |
| Email credentials | `~/.assistant/email_config.json` |
| Seen email IDs | `~/.assistant/seen_email_ids.json` |
| Daemon PID | `~/.assistant/daemon.pid` |
