"""
TenderIQ Calendar – Daily Digest
Shim module referenced by hooks.py scheduler_events.
"""


def send_daily_digest():
    """
    Scheduler entry point (runs daily).
    Delegates to the digest logic in ``calendar/__init__.py``.
    """
    from tenderiq.tenderiq.calendar import send_daily_digest as _send  # noqa: PLC0415

    _send()
