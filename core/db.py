import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from contextlib import contextmanager

# Ensure the data directory exists
DATA_DIR = os.path.expanduser("~/.assistant")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

def init_db():
    """Initialize the database with the tasks table."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                due_at TEXT,
                priority TEXT CHECK(priority IN ('low','medium','high')) DEFAULT 'medium',
                status TEXT CHECK(status IN ('pending','done','snoozed')) DEFAULT 'pending',
                recurrence TEXT,
                created_at TEXT,
                updated_at TEXT,
                snoozed_until TEXT
            )
        ''')
        # Migration: add gcal_event_id if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "gcal_event_id" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN gcal_event_id TEXT")
        conn.commit()


def get_tasks_for_gcal_sync() -> List[Tuple]:
    """Pending tasks with a due date — candidates for Google Calendar push."""
    with get_db_connection() as conn:
        cursor = conn.execute('''
            SELECT id, title, description, due_at, priority, recurrence, gcal_event_id
            FROM tasks
            WHERE status = 'pending' AND due_at IS NOT NULL
        ''')
        return cursor.fetchall()


def get_done_tasks_with_gcal() -> List[Tuple]:
    """Done tasks that still have a linked GCal event — for cleanup."""
    with get_db_connection() as conn:
        cursor = conn.execute('''
            SELECT id, gcal_event_id FROM tasks
            WHERE status = 'done' AND gcal_event_id IS NOT NULL
        ''')
        return cursor.fetchall()


def set_gcal_event_id(task_id: int, event_id: Optional[str]) -> None:
    with get_db_connection() as conn:
        conn.execute('UPDATE tasks SET gcal_event_id = ? WHERE id = ?', (event_id, task_id))
        conn.commit()

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()

def create_task(title: str, description: Optional[str] = None, 
               due_at: Optional[str] = None, priority: str = 'medium', 
               recurrence: Optional[str] = None) -> int:
    """Create a new task and return its ID."""
    created_at = datetime.now().isoformat()
    updated_at = created_at
    
    with get_db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO tasks (title, description, due_at, priority, recurrence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, description, due_at, priority, recurrence, created_at, updated_at))
        conn.commit()
        return cursor.lastrowid

def get_task(task_id: int) -> Optional[Tuple]:
    """Retrieve a task by ID."""
    with get_db_connection() as conn:
        cursor = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        return cursor.fetchone()

def list_tasks(filter_by: Optional[str] = None, priority: Optional[str] = None, 
              due_date: Optional[str] = None) -> List[Tuple]:
    """List tasks with optional filters."""
    with get_db_connection() as conn:
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if filter_by == 'pending':
            query += " AND status = ?"
            params.append('pending')
        elif filter_by == 'done':
            query += " AND status = ?"
            params.append('done')
        elif filter_by == 'overdue':
            query += " AND status = ? AND due_at < ?"
            params.extend(['pending', datetime.now().isoformat()])
        
        if priority:
            query += " AND priority = ?"
            params.append(priority)
            
        if due_date:
            query += " AND due_at = ?"
            params.append(due_date)
            
        query += (
            " ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END ASC,"
            " due_at ASC,"
            " CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END ASC"
        )
        
        cursor = conn.execute(query, params)
        return cursor.fetchall()

def update_task(task_id: int, **kwargs) -> bool:
    """Update a task with new values."""
    if not kwargs:
        return False
        
    updated_at = datetime.now().isoformat()
    kwargs['updated_at'] = updated_at
    
    # Build dynamic update query
    set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values())
    values.append(task_id)
    
    with get_db_connection() as conn:
        conn.execute(f'UPDATE tasks SET {set_clause} WHERE id = ?', values)
        conn.commit()
        return conn.total_changes > 0

def delete_task(task_id: int) -> bool:
    """Delete a task by ID."""
    with get_db_connection() as conn:
        conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        return conn.total_changes > 0

def complete_task(task_id: int) -> bool:
    """Mark a task as done."""
    with get_db_connection() as conn:
        conn.execute('UPDATE tasks SET status = ? WHERE id = ?', ('done', task_id))
        conn.commit()
        return conn.total_changes > 0

def reopen_task(task_id: int) -> bool:
    """Reopen a task: set to pending and clear snoozed_until."""
    updated_at = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            'UPDATE tasks SET status = ?, snoozed_until = NULL, updated_at = ? WHERE id = ?',
            ('pending', updated_at, task_id),
        )
        conn.commit()
        return conn.total_changes > 0

def get_pending_tasks() -> List[Tuple]:
    """Get all pending tasks that are due or not due."""
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute('''
            SELECT * FROM tasks 
            WHERE status = 'pending' 
            AND (due_at IS NULL OR due_at <= ?)
            AND (snoozed_until IS NULL OR snoozed_until <= ?)
            ORDER BY due_at ASC
        ''', (now, now))
        return cursor.fetchall()

def snooze_task(task_id: int, minutes: int) -> bool:
    """Snooze a task for specified minutes."""
    now = datetime.now()
    snooze_time = (now.replace(microsecond=0) + timedelta(minutes=minutes)).isoformat()
    
    with get_db_connection() as conn:
        conn.execute('UPDATE tasks SET status = ?, snoozed_until = ? WHERE id = ?', 
                    ('snoozed', snooze_time, task_id))
        conn.commit()
        return conn.total_changes > 0

def cleanup_stale_tasks(days: int = 3) -> int:
    """Delete pending non-recurring tasks that are either:
      - overdue by more than `days` days, or
      - have no due date and were created more than `days` days ago.
    Returns the number of deleted rows."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute('''
            DELETE FROM tasks
            WHERE status = 'pending'
              AND (recurrence IS NULL OR recurrence = '')
              AND (
                    (due_at IS NOT NULL AND due_at < ?)
                 OR (due_at IS NULL AND created_at IS NOT NULL AND created_at < ?)
              )
        ''', (cutoff, cutoff))
        conn.commit()
        return cursor.rowcount


def get_daemon_pid() -> Optional[int]:
    """Get the daemon PID from the PID file."""
    pid_file = os.path.join(DATA_DIR, "daemon.pid")
    try:
        with open(pid_file, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

def save_daemon_pid(pid: int):
    """Save the daemon PID to the PID file."""
    pid_file = os.path.join(DATA_DIR, "daemon.pid")
    with open(pid_file, 'w') as f:
        f.write(str(pid))

def remove_daemon_pid():
    """Remove the daemon PID file."""
    pid_file = os.path.join(DATA_DIR, "daemon.pid")
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass