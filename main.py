import argparse
import os
import sys
import textwrap
from datetime import datetime
from db import init_db, create_task, get_task, list_tasks, update_task, delete_task, complete_task, snooze_task, get_daemon_pid
from reminder import start_daemon
from recurrence import calculate_next_due_date

def setup():
    """Initialize the database."""
    init_db()

def add_task(args):
    """Add a new task."""
    try:
        task_id = create_task(
            title=args.title,
            description=args.description,
            due_at=args.due,
            priority=args.priority,
            recurrence=args.recur
        )
        print(f"Task added successfully with ID: {task_id}")
    except Exception as e:
        print(f"Error adding task: {e}")

def list_tasks_cmd(args):
    """List tasks with optional filters."""
    try:
        tasks = list_tasks(
            filter_by=args.filter,
            priority=args.priority,
            due_date=args.due
        )
        
        if not tasks:
            print("No tasks found.")
            return
            
        # Print as a table
        print(f"{'ID':<4} {'Title':<20} {'Due':<20} {'Priority':<10} {'Status':<10} {'Recurrence':<12}")
        print("-" * 80)
        
        for task in tasks:
            task_id, title, description, due_at, priority, status, recurrence, created_at, updated_at, snoozed_until = task
            
            # Format due date
            due_str = "None" if due_at is None else datetime.fromisoformat(due_at).strftime("%Y-%m-%d %H:%M")
            
            print(f"{task_id:<4} {title[:19]:<20} {due_str:<20} {priority:<10} {status:<10} {recurrence or 'None':<12}")
            
    except Exception as e:
        print(f"Error listing tasks: {e}")

def complete_task_cmd(args):
    """Mark a task as done."""
    try:
        task = get_task(args.task_id)
        if not task:
            print(f"Task with ID {args.task_id} not found.")
            return
            
        task_id, title, description, due_at, priority, status, recurrence, created_at, updated_at, snoozed_until = task
        
        if status == 'done':
            print(f"Task {args.task_id} is already completed.")
            return
            
        # If task is recurring, create a new instance
        if recurrence:
            next_due = calculate_next_due_date(due_at, recurrence)
            if next_due:
                new_task_id = create_task(
                    title=title,
                    description=description,
                    due_at=next_due,
                    priority=priority,
                    recurrence=recurrence
                )
                print(f"Recurring task created with ID: {new_task_id}")
        
        complete_task(args.task_id)
        print(f"Task {args.task_id} marked as done.")
        
    except Exception as e:
        print(f"Error completing task: {e}")

def delete_task_cmd(args):
    """Delete a task."""
    try:
        if delete_task(args.task_id):
            print(f"Task {args.task_id} deleted successfully.")
        else:
            print(f"Task with ID {args.task_id} not found.")
    except Exception as e:
        print(f"Error deleting task: {e}")

def edit_task(args):
    """Edit an existing task."""
    try:
        task = get_task(args.task_id)
        if not task:
            print(f"Task with ID {args.task_id} not found.")
            return
            
        # Build update dictionary
        update_data = {}
        if args.title is not None:
            update_data['title'] = args.title
        if args.description is not None:
            update_data['description'] = args.description
        if args.due is not None:
            update_data['due_at'] = args.due
        if args.priority is not None:
            update_data['priority'] = args.priority
        if args.recur is not None:
            update_data['recurrence'] = args.recur
            
        if update_data:
            if update_task(args.task_id, **update_data):
                print(f"Task {args.task_id} updated successfully.")
            else:
                print(f"Failed to update task {args.task_id}.")
        else:
            print("No changes specified.")
            
    except Exception as e:
        print(f"Error editing task: {e}")

def snooze_task_cmd(args):
    """Snooze a task."""
    try:
        if snooze_task(args.task_id, args.minutes):
            print(f"Task {args.task_id} snoozed for {args.minutes} minutes.")
        else:
            print(f"Failed to snooze task {args.task_id}.")
    except Exception as e:
        print(f"Error snoozing task: {e}")

def daily_task_cmd(args):
    """Ask about daily and weekly tasks with text box style input."""
    print("\n" + "="*60)
    print("📋 DAILY TASK ASSESSMENT")
    print("="*60)
    print("Please answer the following questions about your day and week:")
    print()
    
    # Daily tasks
    print("📝 DAILY TASKS:")
    print("-" * 40)
    daily_tasks = []
    
    while True:
        task_input = input("Enter daily task (or press Enter to finish): ").strip()
        if not task_input:
            break
        daily_tasks.append(task_input)
    
    # Weekly tasks
    print("\n📅 WEEKLY TASKS:")
    print("-" * 40)
    weekly_tasks = []
    
    while True:
        task_input = input("Enter weekly task (or press Enter to finish): ").strip()
        if not task_input:
            break
    
    # Display in text box format
    print("\n" + "="*60)
    print("YOUR DAILY TASK SUMMARY")
    print("="*60)
    
    if daily_tasks:
        print("📋 DAILY TASKS:")
        print("┌" + "─" * 58 + "┐")
        for i, task in enumerate(daily_tasks, 1):
            print(f"│ {i:2d}. {task:<52} │")
        print("└" + "─" * 58 + "┘")
    else:
        print("📋 DAILY TASKS:")
        print("┌" + "─" * 58 + "┐")
        print("│ No daily tasks entered                                 │")
        print("└" + "─" * 58 + "┘")
    
    print()
    
    if weekly_tasks:
        print("📅 WEEKLY TASKS:")
        print("┌" + "─" * 58 + "┐")
        for i, task in enumerate(weekly_tasks, 1):
            print(f"│ {i:2d}. {task:<52} │")
        print("└" + "─" * 58 + "┘")
    else:
        print("📅 WEEKLY TASKS:")
        print("┌" + "─" * 58 + "┐")
        print("│ No weekly tasks entered                                │")
        print("└" + "─" * 58 + "┘")
    
    print("\n" + "="*60)
    print("THANK YOU FOR YOUR INPUT!")
    print("="*60)

def daemon_cmd(args):
    """Handle daemon commands."""
    if args.action == 'start':
        start_daemon_cmd()
    elif args.action == 'stop':
        stop_daemon_cmd()
    elif args.action == 'status':
        status_daemon_cmd()

def start_daemon_cmd():
    """Start the daemon process."""
    pid = get_daemon_pid()
    if pid:
        print(f"Daemon is already running with PID: {pid}")
        return
        
    try:
        import subprocess
        import sys
        
        # Start daemon in background
        cmd = [sys.executable, 'reminder.py']
        process = subprocess.Popen(cmd)
        print(f"Daemon started with PID: {process.pid}")
        # Save PID
        from db import save_daemon_pid
        save_daemon_pid(process.pid)
        
    except Exception as e:
        print(f"Error starting daemon: {e}")

def stop_daemon_cmd():
    """Stop the daemon process."""
    pid = get_daemon_pid()
    if not pid:
        print("Daemon is not running.")
        return
        
    try:
        import os
        import signal
        
        os.kill(pid, signal.SIGTERM)
        from db import remove_daemon_pid
        remove_daemon_pid()
        print(f"Daemon with PID {pid} stopped.")
        
    except ProcessLookupError:
        print(f"Daemon with PID {pid} not found. Removing stale PID file.")
        from db import remove_daemon_pid
        remove_daemon_pid()
    except Exception as e:
        print(f"Error stopping daemon: {e}")

def status_daemon_cmd():
    """Check daemon status."""
    pid = get_daemon_pid()
    if pid:
        print(f"Daemon is running with PID: {pid}")
    else:
        print("Daemon is not running.")

def main():
    """Main CLI entry point."""
    setup()
    
    parser = argparse.ArgumentParser(description="Personal Assistant CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add task command
    add_parser = subparsers.add_parser('add', help='Add a new task')
    add_parser.add_argument('title', help='Task title')
    add_parser.add_argument('--description', help='Task description')
    add_parser.add_argument('--due', help='Due date/time (ISO format)')
    add_parser.add_argument('--priority', choices=['low', 'medium', 'high'], default='medium', help='Task priority')
    add_parser.add_argument('--recur', choices=['daily', 'weekly', 'monthly'], help='Recurrence rule')
    
    # List tasks command
    list_parser = subparsers.add_parser('list', help='List tasks')
    list_parser.add_argument('--filter', choices=['pending', 'done', 'overdue'], help='Filter by status')
    list_parser.add_argument('--priority', choices=['low', 'medium', 'high'], help='Filter by priority')
    list_parser.add_argument('--due', help='Filter by due date')
    
    # Complete task command
    done_parser = subparsers.add_parser('done', help='Mark a task as done')
    done_parser.add_argument('task_id', type=int, help='Task ID to complete')
    
    # Delete task command
    delete_parser = subparsers.add_parser('delete', help='Delete a task')
    delete_parser.add_argument('task_id', type=int, help='Task ID to delete')
    
    # Edit task command
    edit_parser = subparsers.add_parser('edit', help='Edit a task')
    edit_parser.add_argument('task_id', type=int, help='Task ID to edit')
    edit_parser.add_argument('--title', help='New task title')
    edit_parser.add_argument('--description', help='New task description')
    edit_parser.add_argument('--due', help='New due date/time (ISO format)')
    edit_parser.add_argument('--priority', choices=['low', 'medium', 'high'], help='New task priority')
    edit_parser.add_argument('--recur', choices=['daily', 'weekly', 'monthly'], help='New recurrence rule')
    
    # Snooze command
    snooze_parser = subparsers.add_parser('snooze', help='Snooze a task')
    snooze_parser.add_argument('task_id', type=int, help='Task ID to snooze')
    snooze_parser.add_argument('--minutes', type=int, default=30, help='Minutes to snooze (default: 30)')
    
    # Daily command
    daily_parser = subparsers.add_parser('daily', help='Assess daily and weekly tasks')
    
    # Daemon command
    daemon_parser = subparsers.add_parser('daemon', help='Daemon management')
    daemon_parser.add_argument('action', choices=['start', 'stop', 'status'], help='Daemon action')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
        
    if args.command == 'add':
        add_task(args)
    elif args.command == 'list':
        list_tasks_cmd(args)
    elif args.command == 'done':
        complete_task_cmd(args)
    elif args.command == 'delete':
        delete_task_cmd(args)
    elif args.command == 'edit':
        edit_task(args)
    elif args.command == 'snooze':
        snooze_task_cmd(args)
    elif args.command == 'daily':
        daily_task_cmd(args)
    elif args.command == 'daemon':
        daemon_cmd(args)

if __name__ == "__main__":
    main()