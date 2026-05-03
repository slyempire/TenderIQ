# Copyright (c) 2024, TenderIQ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TenderDocument(Document):
    """
    Represents a document (e.g. PDF, Word) attached to a Tender.

    On creation, triggers AI analysis of the document content if an
    Anthropic API key is configured.
    """

    def after_insert(self):
        """Trigger asynchronous AI analysis after the record is saved."""
        self._enqueue_ai_analysis()

    def _enqueue_ai_analysis(self):
        """
        Enqueue AI analysis as a background job so the UI remains responsive.
        Only runs when an API key is available.
        """
        try:
            settings = frappe.get_cached_doc("TenderIQ Settings")
            if not settings.get("anthropic_api_key"):
                return  # AI analysis not configured – skip silently

            frappe.enqueue(
                "tenderiq.tenderiq.doctype.tender_document.tender_document.run_ai_analysis",
                queue="long",
                timeout=600,
                document_name=self.name,
                now=frappe.flags.in_test,
            )
        except Exception:
            # Non-fatal – log but do not block document creation
            frappe.log_error(
                message=frappe.get_traceback(),
                title="TenderIQ – failed to enqueue AI analysis",
            )


@frappe.whitelist()
def run_ai_analysis(document_name: str) -> None:
    """
    Perform AI-powered analysis on a TenderDocument.

    Extracts text from the attached PDF (if any), sends it to Claude,
    and stores the summary on the parent Tender document.

    Args:
        document_name: Name of the TenderDocument record to analyse.
    """
    from tenderiq.tenderiq.integrations import call_claude, extract_pdf_text  # noqa: PLC0415

    doc = frappe.get_doc("Tender Document", document_name)

    if not doc.get("file_url"):
        return  # Nothing to analyse

    # Extract text from the PDF attachment
    raw_text = extract_pdf_text(doc.file_url)
    if not raw_text or len(raw_text.strip()) < 50:
        frappe.logger("tenderiq").warning(
            f"TenderIQ: Insufficient text extracted from {doc.file_url} – skipping analysis."
        )
        return

    # Truncate to avoid exceeding token limits (approx. 100k chars ≈ 25k tokens)
    truncated = raw_text[:100_000]

    system_prompt = (
        "You are an expert procurement analyst specialising in East African public tenders. "
        "Extract and summarise the key information from the tender document provided."
    )
    user_prompt = (
        "Please analyse the following tender document and provide:\n"
        "1. A concise executive summary (2-3 sentences)\n"
        "2. Key requirements and eligibility criteria\n"
        "3. Important deadlines\n"
        "4. Estimated contract value (if stated)\n"
        "5. Any red flags or compliance concerns\n\n"
        f"DOCUMENT TEXT:\n{truncated}"
    )

    try:
        analysis = call_claude(user_prompt=user_prompt, system_prompt=system_prompt, max_tokens=2048)
    except Exception:
        # Already logged inside call_claude – nothing more to do here
        return

    # Persist the analysis on the parent Tender
    if doc.get("tender"):
        tender = frappe.get_doc("Tender", doc.tender)
        existing = tender.get("ai_analysis") or ""
        new_entry = f"\n\n--- Document: {doc.document_name or doc.name} ---\n{analysis}"
        tender.ai_analysis = (existing + new_entry).strip()
        tender.save(ignore_permissions=True)
        frappe.db.commit()


# ---------------------------------------------------------------------------
# Module-level event handler referenced by hooks.py doc_events
# ---------------------------------------------------------------------------


def on_after_insert(doc, method=None):
    """
    Called by Frappe after a TenderDocument is inserted.
    Delegates to the controller's after_insert method.
    """
    doc.after_insert()
