import time

import schedule
import threading
import signal
import sys
import os
from datetime import datetime
from core.db import get_pending_tasks, update_task, complete_task, save_daemon_pid, remove_daemon_pid
from integrations.notify import send_notification

# Global flag for daemon shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    print("Received shutdown signal. Stopping daemon...")
    shutdown_requested = True

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

def fire_notifications():
    """Check for pending tasks and send notifications."""
    tasks = get_pending_tasks()
    
    for task in tasks:
        task_id, title, description, due_at, priority, status, recurrence, created_at, updated_at, snoozed_until = task
        
        # Format the notification title and body
        priority_text = priority.upper()
        title_text = f"[{priority_text}] {title}"
        
        if due_at:
            # Format due date for display
            try:
                due_datetime = datetime.fromisoformat(due_at)
                due_str = due_datetime.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                due_str = due_at
            body_text = f"Due: {due_str}"
        else:
            body_text = "No due date"
        
        # Send notification
        if send_notification(title_text, body_text, task_id):
            # After sending notification, update the task to snoozed state
            # This prevents spamming the same notification
            update_task(task_id, status='snoozed', snoozed_until=datetime.now().isoformat())
            print(f"Notification sent for task: {title}")
        else:
            print(f"Failed to send notification for task: {title}")

def start_daemon():
    """Start the reminder daemon."""
    # Setup signal handlers
    setup_signal_handlers()
    
    # Save PID
    pid = os.getpid()
    save_daemon_pid(pid)
    
    print("Daemon started. PID:", pid)
    
    # Schedule the job to run every 60 seconds
    schedule.every(60).seconds.do(fire_notifications)
    
    try:
        while not shutdown_requested:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("Daemon interrupted by user.")
    finally:
        print("Daemon stopping...")
        remove_daemon_pid()
        schedule.clear()

if __name__ == "__main__":
    start_daemon()