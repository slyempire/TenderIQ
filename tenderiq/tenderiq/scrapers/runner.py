"""
TenderIQ Scraper Runner
Entry point for the Frappe scheduler. Delegates to scrapers/__init__.py.
"""


def run_all_scrapers():
    """
    Scheduler entry point (invoked every 6 hours via hooks.py).

    Delegates to the full implementation in ``tenderiq.tenderiq.scrapers``.
    Keeping this thin shim means hooks.py can reference
    ``tenderiq.tenderiq.scrapers.runner.run_all_scrapers`` while the real
    logic stays in ``scrapers/__init__.py`` for easier testing.
    """
    from tenderiq.tenderiq.scrapers import run_all_scrapers as _run  # noqa: PLC0415

    _run()
