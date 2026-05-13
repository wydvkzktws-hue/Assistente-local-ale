from calendar import monthrange
from datetime import datetime, timedelta
from typing import Optional


def _add_months(dt: datetime, months: int) -> datetime:
    """Advance dt by N months, clamping the day to the new month's last day."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


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
        next_due = _add_months(due_datetime, 1)
    else:
        return None

    # If the calculated date is still in the past, keep advancing until it
    # lands in the future (covers tasks that were completed weeks late).
    while next_due < now:
        if recurrence == 'daily':
            next_due += timedelta(days=1)
        elif recurrence == 'weekly':
            next_due += timedelta(weeks=1)
        elif recurrence == 'monthly':
            next_due = _add_months(next_due, 1)

    return next_due.isoformat()