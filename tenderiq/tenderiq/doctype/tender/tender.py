import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, add_days, getdate


class Tender(Document):

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def validate(self):
        self._validate_deadlines()
        self._set_default_status()

    def after_insert(self):
        self._create_checklist()
        self._create_bid_team()

    def on_update(self):
        self._update_checklist_completion()

    # ------------------------------------------------------------------
    # Deadline validation
    # ------------------------------------------------------------------

    def _validate_deadlines(self):
        if self.deadline and self.clarification_deadline:
            if getdate(self.clarification_deadline) >= getdate(self.deadline):
                frappe.throw(
                    "Clarification deadline must be before the submission deadline."
                )
        if self.site_visit_date and self.deadline:
            if getdate(self.site_visit_date) >= getdate(self.deadline):
                frappe.throw(
                    "Site visit date must be before the submission deadline."
                )

    def _set_default_status(self):
        if not self.status:
            self.status = "Identified"

    # ------------------------------------------------------------------
    # Auto-generate checklist from Compliance Clause library
    # ------------------------------------------------------------------

    def _create_checklist(self):
        """Create a Tender Checklist populated from the Compliance Clause library."""
        if frappe.db.exists("Tender Checklist", {"tender": self.name}):
            return  # already exists (e.g. after a rename)

        checklist = frappe.new_doc("Tender Checklist")
        checklist.tender = self.name
        checklist.category = self.category

        clauses = frappe.get_all(
            "Compliance Clause",
            filters={
                "category": ["in", [self.category, "All"]],
            },
            fields=["name", "clause_name", "is_mandatory", "description"],
        )

        # If no category-specific clauses, fall back to general ones
        if not clauses:
            clauses = frappe.get_all(
                "Compliance Clause",
                fields=["name", "clause_name", "is_mandatory", "description"],
            )

        for clause in clauses:
            checklist.append(
                "items",
                {
                    "document_name": clause.clause_name,
                    "status": "Pending",
                    "compliance_flag": 1 if clause.is_mandatory else 0,
                    "notes": clause.description or "",
                    "due_date": add_days(nowdate(), -3) if not self.deadline
                                else add_days(self.deadline, -3),
                },
            )

        checklist.insert(ignore_permissions=True)
        frappe.db.commit()

    def _create_bid_team(self):
        """Initialise an empty Bid Team record for this tender."""
        if frappe.db.exists("Bid Team", {"tender": self.name}):
            return
        bid_team = frappe.new_doc("Bid Team")
        bid_team.tender = self.name
        bid_team.insert(ignore_permissions=True)
        frappe.db.commit()

    # ------------------------------------------------------------------
    # Completion rollup
    # ------------------------------------------------------------------

    def _update_checklist_completion(self):
        checklist_name = frappe.db.get_value(
            "Tender Checklist", {"tender": self.name}, "name"
        )
        if checklist_name:
            checklist = frappe.get_doc("Tender Checklist", checklist_name)
            checklist.recalculate_completion()
            checklist.save(ignore_permissions=True)


# ------------------------------------------------------------------
# Whitelisted API helpers (called from JS / external)
# ------------------------------------------------------------------

@frappe.whitelist()
def get_tender_dashboard(tender_name):
    """Return a lightweight dashboard payload for a tender."""
    tender = frappe.get_doc("Tender", tender_name)

    checklist_name = frappe.db.get_value(
        "Tender Checklist", {"tender": tender_name}, "name"
    )
    completion = 0
    pending_items = []
    if checklist_name:
        checklist = frappe.get_doc("Tender Checklist", checklist_name)
        completion = checklist.completion or 0
        pending_items = [
            {
                "document_name": i.document_name,
                "responsible_person": i.responsible_person,
                "due_date": str(i.due_date) if i.due_date else None,
                "status": i.status,
            }
            for i in checklist.items
            if i.status in ("Pending", "In Progress")
        ]

    days_remaining = None
    if tender.deadline:
        delta = getdate(tender.deadline) - getdate(nowdate())
        days_remaining = delta.days

    return {
        "tender": tender.as_dict(),
        "completion_pct": completion,
        "days_remaining": days_remaining,
        "pending_items": pending_items,
    }


@frappe.whitelist()
def advance_status(tender_name):
    """Move tender to the next logical status."""
    flow = [
        "Identified",
        "Bid Decision",
        "In Preparation",
        "Submitted",
    ]
    tender = frappe.get_doc("Tender", tender_name)
    if tender.status in flow:
        idx = flow.index(tender.status)
        if idx < len(flow) - 1:
            tender.status = flow[idx + 1]
            tender.save(ignore_permissions=True)
            return tender.status
    return tender.status


# ---------------------------------------------------------------------------
# Module-level event handlers (referenced by hooks.py doc_events)
# These are called by Frappe with signature (doc, method).
# ---------------------------------------------------------------------------


def on_after_insert(doc, method=None):
    """
    Called by Frappe after a new Tender is inserted.
    Delegates to the Tender controller's after_insert method.
    """
    doc.after_insert()


def on_update(doc, method=None):
    """
    Called by Frappe when a Tender is saved/updated.
    Delegates to the Tender controller's on_update method.
    """
    doc.on_update()
