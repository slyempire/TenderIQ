"""
TenderIQ AI Pipeline
====================
Three core functions:
  1. analyse_rfp         -- Extract requirements from an uploaded RFP PDF
  2. score_proposal      -- Score a draft technical proposal against RFP criteria
  3. generate_boilerplate -- Generate first-draft sections using company profile

All functions call the Anthropic Messages API. The API key is stored in
TenderIQ Settings.anthropic_api_key.
"""
import json
import frappe
from frappe.utils import now_datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_anthropic_key():
    settings = frappe.get_single("TenderIQ Settings")
    key = settings.get_password("anthropic_api_key") if hasattr(settings, "get_password") else getattr(settings, "anthropic_api_key", None)
    if not key:
        frappe.throw(
            "Anthropic API key not configured. Set it in TenderIQ Settings."
        )
    return key


def _call_claude(system_prompt, user_prompt, max_tokens=4096):
    """Call Claude claude-3-5-sonnet-20241022 and return the text response."""
    try:
        import anthropic
    except ImportError:
        frappe.throw("anthropic Python package not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=_get_anthropic_key())
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=max_tokens,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=system_prompt,
    )
    return message.content[0].text


def _extract_pdf_text(file_url):
    """Extract plain text from a PDF stored in Frappe's file system."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        frappe.throw("PyMuPDF not installed. Run: pip install PyMuPDF")

    site_path = frappe.get_site_path()
    # file_url is like /files/rfp.pdf or /private/files/rfp.pdf
    if file_url.startswith("/private"):
        abs_path = f"{site_path}{file_url}"
    elif file_url.startswith("/files"):
        abs_path = f"{site_path}/public{file_url}"
    else:
        abs_path = file_url

    doc = fitz.open(abs_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text.strip()


# ---------------------------------------------------------------------------
# 1. RFP Analysis
# ---------------------------------------------------------------------------

@frappe.whitelist()
def analyse_rfp(tender_name, file_url):
    """
    Extract structured requirements from an RFP PDF and:
    - Populate / update the Tender Checklist with newly found items
    - Store compliance_score baseline and unusual_clauses on the Tender
    Returns a summary dict.
    """
    frappe.publish_realtime(
        "rfp_analysis_progress",
        {"tender": tender_name, "status": "extracting_text"},
        user=frappe.session.user,
    )

    raw_text = _extract_pdf_text(file_url)
    if not raw_text:
        frappe.throw("Could not extract text from the uploaded PDF.")

    # Truncate to ~120k chars to stay within context window
    text_chunk = raw_text[:120000]

    SYSTEM = (
        "You are a senior procurement specialist with 20 years of experience "
        "evaluating tenders in East Africa. You are precise, thorough, and "
        "flag unusual or onerous clauses that bidders commonly miss."
    )

    USER = f"""Analyse the following RFP document and return a JSON object with exactly these keys:

{{
  \"mandatory_requirements\": [list of strings - every document, certificate, or statement the bidder MUST submit],
  \"evaluation_criteria\": [
    {{\"criterion\": \"string\", \"weight_pct\": number_or_null, \"description\": \"string\"}}
  ],
  \"disqualification_clauses\": [list of strings - conditions that automatically disqualify a bidder],
  \"submission_format\": \"string describing how bids must be submitted (physical/online/both, copies, format)\",
  \"key_dates\": {{
    \"clarification_deadline\": \"YYYY-MM-DD or null\",
    \"site_visit\": \"YYYY-MM-DD or null\",
    \"submission_deadline\": \"YYYY-MM-DD or null\"
  }},
  \"unusual_clauses\": [list of strings - clauses that are unusual, onerous, or carry hidden risk],
  \"tender_category\": \"Goods | Works | Services | Consultancy\"
}}

Return ONLY valid JSON. No markdown fences, no commentary.

RFP TEXT:
{text_chunk}"""

    frappe.publish_realtime(
        "rfp_analysis_progress",
        {"tender": tender_name, "status": "calling_ai"},
        user=frappe.session.user,
    )

    raw_response = _call_claude(SYSTEM, USER, max_tokens=4096)

    try:
        analysis = json.loads(raw_response)
    except json.JSONDecodeError:
        # Try to extract JSON block if model wrapped it
        import re
        match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if match:
            analysis = json.loads(match.group())
        else:
            frappe.throw("AI returned an unparseable response. Please try again.")

    # --- Update the Tender record ---
    tender = frappe.get_doc("Tender", tender_name)
    unusual = analysis.get("unusual_clauses", [])
    tender.unusual_clauses = "\n".join(f"• {c}" for c in unusual) if unusual else ""
    # Set key dates if not already set
    kd = analysis.get("key_dates", {})
    if not tender.clarification_deadline and kd.get("clarification_deadline"):
        tender.clarification_deadline = kd["clarification_deadline"]
    if not tender.site_visit_date and kd.get("site_visit"):
        tender.site_visit_date = kd["site_visit"]
    if not tender.deadline and kd.get("submission_deadline"):
        tender.deadline = kd["submission_deadline"]
    tender.save(ignore_permissions=True)

    # --- Mark the Tender Document as AI-analysed ---
    doc_record = frappe.db.get_value(
        "Tender Document",
        {"tender": tender_name, "file": file_url},
        "name",
    )
    if doc_record:
        frappe.db.set_value("Tender Document", doc_record, "ai_analysed", 1)
        frappe.db.set_value(
            "Tender Document",
            doc_record,
            "extracted_text",
            raw_text[:10000],  # store first 10k for reference
        )

    # --- Populate checklist with new items from mandatory requirements ---
    checklist_name = frappe.db.get_value(
        "Tender Checklist", {"tender": tender_name}, "name"
    )
    if checklist_name:
        checklist = frappe.get_doc("Tender Checklist", checklist_name)
        existing_names = {item.document_name.lower() for item in checklist.items}

        added = 0
        for req in analysis.get("mandatory_requirements", []):
            if req.lower() not in existing_names:
                checklist.append(
                    "items",
                    {
                        "document_name": req,
                        "status": "Pending",
                        "compliance_flag": 1,
                        "notes": "Added by AI analysis of RFP",
                    },
                )
                existing_names.add(req.lower())
                added += 1

        checklist.recalculate_completion()
        checklist.save(ignore_permissions=True)

    frappe.publish_realtime(
        "rfp_analysis_progress",
        {"tender": tender_name, "status": "complete"},
        user=frappe.session.user,
    )

    return {
        "mandatory_requirements_count": len(analysis.get("mandatory_requirements", [])),
        "evaluation_criteria": analysis.get("evaluation_criteria", []),
        "disqualification_clauses": analysis.get("disqualification_clauses", []),
        "unusual_clauses": unusual,
        "checklist_items_added": added if checklist_name else 0,
        "key_dates": analysis.get("key_dates", {}),
        "tender_category": analysis.get("tender_category", ""),
    }


# ---------------------------------------------------------------------------
# 2. Proposal Scorer
# ---------------------------------------------------------------------------

@frappe.whitelist()
def score_proposal(tender_name, proposal_text):
    """
    Score a draft technical proposal against the evaluation criteria
    extracted from the RFP. Returns a score out of 100 with section-level
    feedback and improvement suggestions.
    """
    tender = frappe.get_doc("Tender", tender_name)

    # Pull evaluation criteria from the most recent Tender Document with extracted text
    rfp_text = ""
    td = frappe.db.get_value(
        "Tender Document",
        {"tender": tender_name, "ai_analysed": 1},
        ["name", "extracted_text"],
        as_dict=True,
    )
    if td:
        rfp_text = td.extracted_text or ""

    SYSTEM = (
        "You are an expert bid evaluator. You score technical proposals "
        "against evaluation criteria objectively and provide constructive "
        "feedback that helps bidders improve their submissions."
    )

    rfp_context = f"\n\nRFP CONTEXT (first 8000 chars):\n{rfp_text[:8000]}" if rfp_text else ""

    USER = f"""You are evaluating a technical proposal for the following tender:
Tender: {tender.tender_name}
Category: {tender.category}
Procuring Entity: {tender.procuring_entity}
{rfp_context}

DRAFT PROPOSAL:
{proposal_text[:15000]}

Score this proposal and return a JSON object with exactly these keys:
{{
  \"overall_score\": <integer 0-100>,
  \"grade\": \"A/B/C/D/F\",
  \"section_scores\": [
    {{
      \"section\": \"string\",
      \"score\": <integer 0-100>,
      \"strengths\": [\"string\"],
      \"gaps\": [\"string\"],
      \"improvement\": \"string\"
    }}
  ],
  \"missing_sections\": [\"string\"],
  \"top_3_improvements\": [\"string\"],
  \"compliance_risks\": [\"string - items that could cause disqualification\"]
}}

Return ONLY valid JSON."""

    raw = _call_claude(SYSTEM, USER, max_tokens=3000)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(match.group()) if match else {"error": raw}

    # Save the score back to the Tender
    if "overall_score" in result:
        frappe.db.set_value(
            "Tender", tender_name, "compliance_score", result["overall_score"]
        )

    return result


# ---------------------------------------------------------------------------
# 3. Boilerplate Generator
# ---------------------------------------------------------------------------

@frappe.whitelist()
def generate_boilerplate(tender_name, section_type):
    """
    Generate a first-draft boilerplate section for the proposal.
    section_type: 'company_profile' | 'experience_summary' | 'approach_methodology'
    """
    VALID_SECTIONS = {
        "company_profile": "Company Profile / About Us",
        "experience_summary": "Relevant Experience Summary",
        "approach_methodology": "Technical Approach and Methodology",
    }
    if section_type not in VALID_SECTIONS:
        frappe.throw(f"Invalid section_type. Must be one of: {list(VALID_SECTIONS.keys())}")

    tender = frappe.get_doc("Tender", tender_name)
    section_label = VALID_SECTIONS[section_type]

    # Pull any RFP context
    rfp_text = ""
    td = frappe.db.get_value(
        "Tender Document",
        {"tender": tender_name, "ai_analysed": 1},
        ["extracted_text"],
        as_dict=True,
    )
    if td:
        rfp_text = (td.extracted_text or "")[:5000]

    # Pull company profile from TenderIQ Settings if stored
    settings = frappe.get_single("TenderIQ Settings")
    company_profile = getattr(settings, "company_profile", "") or ""

    SYSTEM = (
        "You are a professional bid writer with deep experience in East African "
        "public procurement. You write compelling, compliant proposal sections "
        "that score highly in technical evaluations. Your writing is clear, "
        "professional, and avoids generic filler."
    )

    USER = f"""Write a {section_label} section for the following tender proposal.

TENDER DETAILS:
- Tender Name: {tender.tender_name}
- Procuring Entity: {tender.procuring_entity}
- Category: {tender.category}
- Source: {tender.source}

COMPANY PROFILE:
{company_profile if company_profile else '[No company profile configured in TenderIQ Settings - write placeholder text in square brackets]'}

RFP CONTEXT:
{rfp_text if rfp_text else '[RFP not yet analysed]'}

Write the {section_label} section now. Format it in clean markdown with appropriate headings.
The section should be 400-700 words. Make it specific to this tender's requirements.
Use [PLACEHOLDER] for any information that the bid writer needs to fill in from their own records."""

    text = _call_claude(SYSTEM, USER, max_tokens=2000)
    return {"section": section_label, "content": text}


# ---------------------------------------------------------------------------
# 4. Addendum Diff
# ---------------------------------------------------------------------------

@frappe.whitelist()
def analyse_addendum(tender_document_name):
    """
    Compare an addendum Tender Document against the original RFP.
    Flags checklist items affected by the addendum.
    """
    addendum_doc = frappe.get_doc("Tender Document", tender_document_name)
    if addendum_doc.document_type != "Addendum":
        frappe.throw("This function only works on Addendum documents.")

    tender_name = addendum_doc.tender

    # Get original RFP text
    original = frappe.db.get_value(
        "Tender Document",
        {"tender": tender_name, "document_type": "RFP", "ai_analysed": 1},
        ["extracted_text"],
        as_dict=True,
    )
    original_text = original.extracted_text[:8000] if original else "[Original RFP not analysed]"

    addendum_text = _extract_pdf_text(addendum_doc.file)

    SYSTEM = "You are a procurement specialist reviewing a tender addendum."

    USER = f"""An addendum has been issued for a tender. Compare it to the original RFP and return JSON:
{{
  \"summary\": \"1-paragraph summary of what changed\",
  \"affected_checklist_items\": [\"list of document/requirement names now affected\"],
  \"deadline_changes\": {{\"old\": \"date or null\", \"new\": \"date or null\"}},
  \"critical_changes\": [\"changes that could affect bid price or eligibility\"]
}}

ORIGINAL RFP (excerpt):
{original_text}

ADDENDUM:
{addendum_text[:8000]}

Return ONLY valid JSON."""

    raw = _call_claude(SYSTEM, USER, max_tokens=2000)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(match.group()) if match else {"summary": raw}

    # Store the diff summary on the Tender Document
    frappe.db.set_value(
        "Tender Document",
        tender_document_name,
        "diff_summary",
        result.get("summary", ""),
    )

    # Flag affected checklist items
    checklist_name = frappe.db.get_value(
        "Tender Checklist", {"tender": tender_name}, "name"
    )
    flagged = []
    if checklist_name:
        checklist = frappe.get_doc("Tender Checklist", checklist_name)
        affected = {x.lower() for x in result.get("affected_checklist_items", [])}
        for item in checklist.items:
            for a in affected:
                if a in item.document_name.lower():
                    item.notes = f"[ADDENDUM REVIEW NEEDED] {item.notes or ''}"
                    item.status = "In Progress"
                    flagged.append(item.document_name)
                    break
        checklist.save(ignore_permissions=True)

    result["checklist_items_flagged"] = flagged
    return result
