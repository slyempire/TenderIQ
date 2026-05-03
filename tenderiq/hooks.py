from . import __version__ as app_version

app_name = "tenderiq"
app_title = "TenderIQ"
app_publisher = "TenderIQ"
app_description = "AI-powered tender management for African procurement markets"
app_email = "hello@tenderiq.app"
app_license = "MIT"
app_version = app_version

# ----- Includes in <head> -----
# app_include_css = "/assets/tenderiq/css/tenderiq.css"
# app_include_js  = "/assets/tenderiq/js/tenderiq.js"

# ----- DocType-level hooks -----
doc_events = {
    "Tender": {
        "after_insert": "tenderiq.tenderiq.doctype.tender.tender.on_after_insert",
        "on_update": "tenderiq.tenderiq.doctype.tender.tender.on_update",
    },
    "Tender Document": {
        "after_insert": "tenderiq.tenderiq.doctype.tender_document.tender_document.on_after_insert",
    },
}

# ----- Scheduler events -----
scheduler_events = {
    "hourly": [
        "tenderiq.tenderiq.calendar.deadlines.compute_countdowns",
    ],
    "daily": [
        "tenderiq.tenderiq.calendar.digest.send_daily_digest",
    ],
    "cron": {
        # Every 6 hours: scrape PPRA + AGPO + county portals
        "0 */6 * * *": [
            "tenderiq.tenderiq.scrapers.runner.run_all_scrapers",
        ],
    },
}

# ----- Fixtures -----
fixtures = [
    {"dl": "Compliance Clause", "filters": [["is_seed", "=", 1]]},
]

# ----- Whitelisted methods (exposed to /api/method/...) -----
# Listed here for documentation; @frappe.whitelist() decorator handles auth
override_whitelisted_methods = {}

# ----- Permissions / role hooks -----
# permission_query_conditions = {}
# has_permission = {}

# ----- Website / desk pages -----
# website_route_rules = []

# ----- Required apps -----
# Optional ERPNext integration is detected at runtime, not required here.
required_apps = ["frappe"]
