import frappe
from frappe.model.document import Document


class TenderChecklist(Document):

    def validate(self):
        self.recalculate_completion()

    def recalculate_completion(self):
        """Recalculate the completion percentage based on item statuses."""
        if not self.items:
            self.completion = 0
            return
        done = sum(
            1 for item in self.items if item.status == "Submitted"
        )
        self.completion = round((done / len(self.items)) * 100, 1)

    def get_missing_mandatory(self):
        """Return checklist items that are mandatory but not yet submitted."""
        return [
            item for item in self.items
            if item.compliance_flag and item.status != "Submitted"
        ]

    def get_overdue_items(self):
        """Return items where due_date has passed and status is not Submitted."""
        from frappe.utils import getdate, nowdate
        today = getdate(nowdate())
        return [
            item for item in self.items
            if item.due_date
            and getdate(item.due_date) < today
            and item.status != "Submitted"
        ]
