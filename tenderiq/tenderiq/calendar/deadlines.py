"""
TenderIQ Calendar – Deadline Countdowns
Shim module referenced by hooks.py scheduler_events.
"""


def compute_countdowns():
    """
    Scheduler entry point (runs hourly).
    Delegates to the countdown/alert logic in ``calendar/__init__.py``.
    """
    from tenderiq.tenderiq.calendar import check_deadline_alerts  # noqa: PLC0415

    check_deadline_alerts()
