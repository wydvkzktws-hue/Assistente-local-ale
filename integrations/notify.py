import os
import platform
import subprocess
from typing import Optional
from datetime import datetime

def send_notification(title: str, body: str, task_id: int, snooze_minutes: int = 30) -> bool:
    """
    Send a desktop notification based on the platform.
    
    Args:
        title: Notification title
        body: Notification body
        task_id: Task ID for snooze command
        snooze_minutes: Minutes to snooze (default 30)
        
    Returns:
        True if notification was sent successfully, False otherwise
    """
    system = platform.system()
    
    if system == "Darwin":  # macOS
        return _send_macos_notification(title, body, task_id, snooze_minutes)
    elif system == "Linux":
        return _send_linux_notification(title, body)
    elif system == "Windows":
        return _send_windows_notification(title, body)
    else:
        print(f"Unsupported platform: {system}")
        return False

def _send_macos_notification(title: str, body: str, task_id: int, snooze_minutes: int) -> bool:
    """Send notification on macOS using osascript."""
    try:
        # Format the snooze command
        snooze_cmd = f"python main.py snooze {task_id} --minutes {snooze_minutes}"
        
        # Create AppleScript command
        script = f'''
        display notification "{body}" with title "{title}"
        '''
        
        subprocess.run(['osascript', '-e', script], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to send macOS notification: {e}")
        return False
    except FileNotFoundError:
        print("osascript not found. Please ensure AppleScript is available.")
        return False

def _send_linux_notification(title: str, body: str) -> bool:
    """Send notification on Linux using notify-send."""
    try:
        # Format the body with the snooze command
        full_body = f"{body}\nID: {task_id}  |  snooze: notify-send --expire-time=30000 'Snooze' 'python main.py snooze {task_id} --minutes 30'"
        
        subprocess.run(['notify-send', title, body], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to send Linux notification: {e}")
        return False
    except FileNotFoundError:
        print("notify-send not found. Please install libnotify.")
        return False

def _send_windows_notification(title: str, body: str) -> bool:
    """Send notification on Windows using plyer."""
    try:
        from plyer import notification
        
        # Format the body with the snooze command
        full_body = f"{body}\nID: {task_id}  |  snooze: python main.py snooze {task_id} --minutes 30"
        
        notification.notify(
            title=title,
            message=body,
            app_name="Personal Assistant",
            timeout=10
        )
        return True
    except ImportError:
        print("plyer not installed. Please run: pip install plyer")
        return False
    except Exception as e:
        print(f"Failed to send Windows notification: {e}")
        return False

# ============================================================
# 📋 DAILY TASK ASSESSMENT
# ============================================================
def daily_task_assessment():
    print("==========================================================")
    print("📋 DAILY TASK ASSESSMENT")
    print("==========================================================")
    print("Please answer the following questions about your day and week:\n")

    # Daily tasks
    print("📝 DAILY TASKS:")
    print("------------------------------")
    daily_tasks = []
    while True:
        task = input("Enter daily task (or press Enter to finish): ")
        if not task:
            break
        daily_tasks.append(task)
    print()

    # Weekly tasks
    print("📅 WEEKLY TASKS:")
    print("------------------------------")
    weekly_tasks = []
    while True:
        task = input("Enter weekly task (or press Enter to finish): ")
        if not task:
            break
        weekly_tasks.append(task)
    print()

    # Summary
    print("==========================================================")
    print("YOUR DAILY TASK SUMMARY")
    print("==========================================================")

    # Daily tasks summary
    print("📋 DAILY TASKS:")
    if daily_tasks:
        print("┌" + "─" * 86 + "┐")
        for idx, task in enumerate(daily_tasks, start=1):
            print(f"|  {idx}. {task:<84}|")
        print("└" + "─" * 86 + "┘")
    else:
        print("No daily tasks recorded.")

    print()

    # Weekly tasks summary
    print("📅 WEEKLY TASKS:")
    if weekly_tasks:
        print("┌" + "─" * 86 + "┐")
        for idx, task in enumerate(weekly_tasks, start=1):
            print(f"|  {idx}. {task:<84}|")
        print("└" + "─" * 86 + "┘")
    else:
        print("No weekly tasks recorded.")

    print()
    print("==========================================================")
    print("THANK YOU FOR YOUR INPUT!")
    print("==========================================================")
    print()

# Call the daily task assessment when script runs
if __name__ == "__main__":
    daily_task_assessment()
