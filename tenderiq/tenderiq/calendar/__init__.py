"""
TenderIQ Calendar & Deadline Engine
====================================
Handles:
  - Daily digest email to Bid Managers (7am)
  - Deadline countdown alerts (14, 7, 3, 1 days before)
  - Overdue checklist item flagging
  - WhatsApp alerts via Africa's Talking (if configured)

Called by hooks.py scheduler:
  - send_daily_digest: daily at 07:00
  - check_deadline_alerts: daily at 08:00
"""
import frappe
from frappe.utils import (
    nowdate, getdate, add_days, date_diff, get_url
)


# ---------------------------------------------------------------------------
# Daily Digest
# ---------------------------------------------------------------------------

def send_daily_digest():
    """
    Send a morning digest to all Bid Managers listing:
    - Active tenders with deadlines in next 14 days
    - Overdue checklist items
    - Tenders needing a bid decision
    """
    active_tenders = frappe.get_all(
        "Tender",
        filters={
            "status": ["in", ["Identified", "Bid Decision", "In Preparation"]],
        },
        fields=[
            "name", "tender_name", "procuring_entity", "category",
            "deadline", "status", "compliance_score",
        ],
        order_by="deadline asc",
    )

    if not active_tenders:
        return  # Nothing to report

    today = getdate(nowdate())
    urgent = []       # <= 7 days
    upcoming = []     # 8-14 days
    attention = []    # no deadline or > 14 days
    decision_needed = []

    for t in active_tenders:
        days_left = None
        if t.deadline:
            days_left = date_diff(t.deadline, today)

        if t.status == "Identified":
            decision_needed.append({**t, "days_left": days_left})
        elif days_left is not None and days_left <= 7:
            urgent.append({**t, "days_left": days_left})
        elif days_left is not None and days_left <= 14:
            upcoming.append({**t, "days_left": days_left})
        else:
            attention.append({**t, "days_left": days_left})

    # Build email HTML
    html = _build_digest_html(urgent, upcoming, attention, decision_needed)

    # Get all Bid Managers
    recipients = _get_role_users("Bid Manager")
    if not recipients:
        return

    frappe.sendmail(
        recipients=recipients,
        subject=f"[TenderIQ Daily Digest] {today} — {len(urgent)} urgent, {len(decision_needed)} awaiting decision",
        message=html,
    )


def _build_digest_html(urgent, upcoming, attention, decision_needed):
    def tender_row(t):
        days_str = f"{t['days_left']} days" if t.get('days_left') is not None else "No deadline"
        color = "#d32f2f" if (t.get('days_left') or 99) <= 3 else (
            "#f57c00" if (t.get('days_left') or 99) <= 7 else "#388e3c"
        )
        url = f"{get_url()}/app/tender/{t['name']}"
        return (
            f"<tr>"
            f"<td><a href='{url}'>{t['tender_name']}</a></td>"
            f"<td>{t['procuring_entity']}</td>"
            f"<td>{t['category']}</td>"
            f"<td style='color:{color};font-weight:bold'>{days_str}</td>"
            f"<td>{t['status']}</td>"
            f"</tr>"
        )

    table_header = (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        "<thead><tr style='background:#1a237e;color:white'>"
        "<th>Tender</th><th>Entity</th><th>Category</th><th>Deadline</th><th>Status</th>"
        "</tr></thead><tbody>"
    )

    sections = []

    if urgent:
        rows = "".join(tender_row(t) for t in urgent)
        sections.append(
            f"<h2 style='color:#d32f2f'>\ud83d\udd34 URGENT — Deadline within 7 days ({len(urgent)})</h2>"
            + table_header + rows + "</tbody></table>"
        )

    if decision_needed:
        rows = "".join(tender_row(t) for t in decision_needed)
        sections.append(
            f"<h2 style='color:#f57c00'>\u23f3 Awaiting Bid Decision ({len(decision_needed)})</h2>"
            + table_header + rows + "</tbody></table>"
        )

    if upcoming:
        rows = "".join(tender_row(t) for t in upcoming)
        sections.append(
            f"<h2 style='color:#1565c0'>\ud83d\udcc5 Upcoming — 8-14 days ({len(upcoming)})</h2>"
            + table_header + rows + "</tbody></table>"
        )

    if attention:
        rows = "".join(tender_row(t) for t in attention)
        sections.append(
            f"<h2 style='color:#555'>\u2139\ufe0f In Progress ({len(attention)})</h2>"
            + table_header + rows + "</tbody></table>"
        )

    body = "\n".join(sections) or "<p>No active tenders today.</p>"
    return f"""
    <html><body style='font-family:Arial,sans-serif;max-width:900px;margin:auto'>
    <h1 style='border-bottom:3px solid #1a237e;padding-bottom:8px'>
        Tender— <a href='{get_url()}/app'>Open TenderIQ</a></p>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Deadline Alerts
# ---------------------------------------------------------------------------

ALERT_DAYS = [14, 7, 3, 1]  # send alerts at these many days before deadline


def check_deadline_alerts():
    """
    Check all active tenders and send targeted alerts when deadlines are
    exactly N days away. Also flags overdue checklist items.
    """
    today = getdate(nowdate())

    active_tenders = frappe.get_all(
        "Tender",
        filters={
            "status": ["not in", ["Bid Decision", "I\u2013 not required."]],
            "deadline": ["is", "set"],
        },
        fields=["name", "tender_name", "deadline", "status", "bid_manager",
                "procuring_entity"],
        order_by="deadline asc",
    )

    if not active_tenders:
        return

    alerts_sent = 0

    for t in active_tenders:
        days_left = date_diff(t.deadline, today)

        if days_left in ALERT_DAYS or days_left < 0:
            _send_deadline_alert(t, days_left)
            alerts_sent += 1

    # Also flag overdue checklist items
    _flag_overdue_checklist_items(today)

    frappe.logger().info(f"TenderIQ: check_deadline_alerts sent {alerts_sent} alerts")


def _send_deadline_alert(tender, days_left):
    """Send a deadline alert email (and optionally WhatsApp) for a tender."""
    if not tender.bid_manager:
        return

    if days_left < 0:
        subject = f"\u26a0\ufe0f OVERDUE: {tender.tender_name} deadline was {abs(days_left)} day(s) ago"
        urgency = "OVERDUE"
    elif days_left == 0:
        subject = f"\ud83d\udea8 TODAY: {tender.tender_name} deadline is TODAY"
        urgency = "TODAY"
    else:
        subject = f"\u23f0 {days_left} day(s) left: {tender.tender_name}"
        urgency = f"{days_left} DAYS"

    message = f"""
    <p>Deadline alert for tender: <strong>{tender.tender_name}</strong></p>
    <p>Entity: {tender.procuring_entity}</p>
    <p>Deadline: {tender.deadline} ({urgency})</p>
    <p>Status: {tender.status}</p>
    <p><a href="{get_url()}/app/tender/{tender.name}">Open in TenderIQ</a></p>
    """

    frappe.sendmail(
        recipients=[tender.bid_manager],
        subject=subject,
        message=message,
    )


def _flag_overdue_checklist_items(today):
    """Mark checklist items whose due date has passed as overdue."""
    overdue_items = frappe.get_all(
        "Tender Checklist",
        filters={
            "status": ["not in", ["Done", "N/A"]],
            "due_date": ["<", today],
        },
        fields=["name"],
    )

    for item in overdue_items:
        frappe.db.set_value("Tender Checklist", item.name, "status", "Overdue")

    if overdue_items:
        frappe.db.commit()




# ---------------------------------------------------------------------------
# ERPNext Integration
# ---------------------------------------------------------------------------

def is_erpnext_installed():
    """Return True if ERPNext is installed and active."""
    return frappe.db.exists("Module Def", "Accounts") is not None


@frappe.whitelist()
def get_financial_capacity_data(company=None):
    """
    Pull financial data from ERPNext to auto-populate Form of Financial Capacity.
    Returns: turnover for last 3 years, net worth, current ratio.
    Falls back to empty dict if ERPNext is not installed.
    """
    if not is_erpnext_installed():
        return {
            "available": False,
            "message": "ERPNext not installed. Enter financial data manually.",
        }

    try:
        from erpnext.accounts.report.balance_sheet.balance_sheet import execute as bs_execute
        from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
            execute as pl_execute
        )
    except ImportError:
        return {"available": False, "message": "ERPNext accounts module unavailable."}

    if not company:
        company = frappe.defaults.get_user_default("Company") or frappe.get_all(
            "Company", limit=1, pluck="name"
        )[0]

    from frappe.utils import today, getdate
    current_year = getdate(today()).year
    years = [current_year - 1, current_year - 2, current_year - 3]

    turnover_data = []
    for year in years:
        filters = frappe._dict(
            company=company,
            fiscal_year=str(year),
            periodicity="Yearly",
        )
        try:
            result = pl_execute(filters)
            # Extract total revenue row
            revenue = _extract_financial_value(result, "Income")
            turnover_data.append({"year": year, "turnover": revenue})
        except Exception:
            turnover_data.append({"year": year, "turnover": None})

    # Balance sheet for latest year
    bs_filters = frappe._dict(
        company=company,
        fiscal_year=str(years[0]),
        periodicity="Yearly",
    )
    net_worth = None
    current_ratio = None
    try:
        bs_result = bs_execute(bs_filters)
        equity = _extract_financial_value(bs_result, "Equity")
        current_assets = _extract_financial_value(bs_result, "Current Assets")
        current_liabilities = _extract_financial_value(bs_result, "Current Liabilities")
        net_worth = equity
        if current_liabilities and current_liabilities != 0:
            current_ratio = round(current_assets / current_liabilities, 2)
    except Exception:
        pass

    return {
        "available": True,
        "company": company,
        "turnover": turnover_data,
        "net_worth": net_worth,
        "current_ratio": current_ratio,
    }


def _extract_financial_value(report_result, section_name):
    """Extract a total value from an ERPNext financial report result."""
    try:
        columns, data = report_result[0], report_result[1]
        for row in data:
            if section_name.lower() in str(row.get("account", "")).lower():
                # Find the last non-label column value
                for col in reversed(columns):
                    val = row.get(col.get("fieldname", ""))
                    if val is not None:
                        return val
    except Exception:
        pass
    return None


@frappe.whitelist()
def get_tax_compliance_status(company=None):
    """
    Check tax compliance certificate status from ERPNext.
    Returns the most recent tax payment dates if available.
    """
    if not is_erpnext_installed():
        return {"available": False}

    if not company:
        company = frappe.defaults.get_user_default("Company") or frappe.get_all(
            "Company", limit=1, pluck="name"
        )[0]

    # Check Payment Entries for tax authorities
    tax_bodies = ["KRA", "Kenya Revenue Authority", "NSSF", "NHIF", "NITA"]
    compliance = {}

    for body in tax_bodies:
        last_payment = frappe.db.get_value(
            "Payment Entry",
            {
                "party_name": ["like", f"%{body}%"],
                "company": company,
                "docstatus": 1,
            },
            "posting_date",
            order_by="posting_date desc",
        )
        compliance[body] = str(last_payment) if last_payment else "No record"

    return {"available": True, "company": company, "compliance": compliance}


# ---------------------------------------------------------------------------
# Document upload helpers
# ---------------------------------------------------------------------------

@frappe.whitelist()
def attach_audited_accounts(tender_name, fiscal_year):
    """
    Pull the audited accounts PDF from ERPNext Accounting (if uploaded there)
    and attach it to the Tender Document list.
    This is a stub — implement based on how your firm stores audited accounts.
    """
    # Placeholder: in practice, look for a File record attached to
    # 'Balance Sheet' or a custom Audited Accounts doctype
    attached_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Company",
            "file_name": ["like", f"%audit%{fiscal_year}%"],
        },
        fields=["name", "file_url", "file_name"],
        limit=1,
    )

    if not attached_files:
        return {"found": False, "message": f"No audited accounts found for {fiscal_year}"}

    source_file = attached_files[0]

    # Create a Tender Document entry
    td = frappe.new_doc("Tender Document")
    td.tender = tender_name
    td.document_type = "Audited Accounts"
    td.file = source_file.file_url
    td.version = fiscal_year
    td.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"found": True, "tender_document": td.name, "file": source_file.file_url}
