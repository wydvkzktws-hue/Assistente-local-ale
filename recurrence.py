from datetime import datetime, timedelta
from typing import Optional

def calculate_next_due_date(due_at: str, recurrence: str) -> Optional[str]:
    """
    Calculate the next due date based on recurrence rule.
    
    Args:
        due_at: Current due date as ISO string
        recurrence: Recurrence rule ('daily', 'weekly', 'monthly')
        
    Returns:
        Next due date as ISO string, or None if invalid recurrence
    """
    if not due_at or not recurrence:
        return None
        
    try:
        due_datetime = datetime.fromisoformat(due_at)
    except ValueError:
        return None
        
    now = datetime.now()
    
    if recurrence == 'daily':
        next_due = due_datetime + timedelta(days=1)
    elif recurrence == 'weekly':
        next_due = due_datetime + timedelta(weeks=1)
    elif recurrence == 'monthly':
        # Handle month overflow
        try:
            next_due = due_datetime.replace(year=due_datetime.year + 1)
        except ValueError:
            # This handles leap year edge case (e.g., Feb 29)
            next_due = due_datetime.replace(year=due_datetime.year + 1, month=2, day=28)
    else:
        return None
        
    # If the calculated date is in the past, set it to tomorrow
    if next_due < now:
        if recurrence == 'daily':
            next_due = now + timedelta(days=1)
        elif recurrence == 'weekly':
            next_due = now + timedelta(weeks=1)
        elif recurrence == 'monthly':
            # For monthly, we'll add one month from now
            try:
                next_due = now.replace(year=now.year + 1)
            except ValueError:
                next_due = now.replace(year=now.year + 1, month=2, day=28)
    
    return next_due.isoformat()