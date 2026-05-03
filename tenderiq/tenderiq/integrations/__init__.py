"""
TenderIQ Integrations Module
Handles third-party AI (Anthropic/Claude) and external service integrations.
"""

import frappe
from frappe import _

DEFAULT_MODEL = "claude-3-5-haiku-20241022"
DEFAULT_MAX_TOKENS = 4096


def get_anthropic_client():
    """
    Return an initialized Anthropic client using the API key from TenderIQ Settings.

    Raises:
        frappe.ValidationError: If the anthropic package is missing or the API key is not set.
    """
    try:
        import anthropic
    except ImportError:
        frappe.throw(
            _(
                "The 'anthropic' Python package is not installed. "
                "Please run: pip install 'anthropic>=0.34.0'"
            ),
            title=_("Missing Dependency"),
        )

    settings = frappe.get_cached_doc("TenderIQ Settings")
    api_key = settings.get_password("anthropic_api_key") if settings.get("anthropic_api_key") else None

    if not api_key:
        frappe.throw(
            _(
                "Anthropic API key is not configured. "
                "Please open TenderIQ Settings and enter your API key."
            ),
            title=_("Missing API Key"),
        )

    return anthropic.Anthropic(api_key=api_key)


def get_default_model() -> str:
    """Return the Claude model configured in TenderIQ Settings, or the default."""
    try:
        settings = frappe.get_cached_doc("TenderIQ Settings")
        return settings.get("anthropic_model") or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def call_claude(
    user_prompt: str,
    system_prompt: str = "",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str | None = None,
) -> str:
    """
    Send a request to the Anthropic Claude API and return the response text.

    Args:
        user_prompt: The user-side message.
        system_prompt: Optional system-level instructions.
        max_tokens: Maximum output tokens (default: 4096).
        model: Claude model identifier. Falls back to TenderIQ Settings → DEFAULT_MODEL.

    Returns:
        str: The text of Claude's first response block.

    Raises:
        frappe.ValidationError: On configuration or API errors.
    """
    client = get_anthropic_client()

    if model is None:
        model = get_default_model()

    request_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if system_prompt:
        request_kwargs["system"] = system_prompt

    try:
        message = client.messages.create(**request_kwargs)
        return message.content[0].text
    except Exception as exc:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"TenderIQ – Anthropic API error: {exc.__class__.__name__}",
        )
        frappe.throw(
            _(
                "AI analysis failed ({0}). Please verify your API key and model, "
                "then try again."
            ).format(exc.__class__.__name__),
            title=_("AI Error"),
        )


def extract_pdf_text(file_url: str) -> str:
    """
    Extract all text from a PDF attached to the Frappe site.

    Args:
        file_url: A Frappe-relative file path, e.g. ``/files/tender_doc.pdf``.

    Returns:
        str: Concatenated page text, or an empty string if extraction fails.
    """
    try:
        import pdfplumber
    except ImportError:
        frappe.throw(
            _(
                "The 'pdfplumber' Python package is not installed. "
                "Please run: pip install 'pdfplumber>=0.10.0'"
            ),
            title=_("Missing Dependency"),
        )

    file_path = frappe.get_site_path("public", file_url.lstrip("/"))

    try:
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
        return "\n\n".join(pages)
    except FileNotFoundError:
        frappe.log_error(
            message=f"PDF not found at path: {file_path}",
            title="TenderIQ – PDF extraction: file not found",
        )
        return ""
    except Exception as exc:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"TenderIQ – PDF extraction error: {exc.__class__.__name__}",
        )
        return ""


def send_whatsapp_alert(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message via the AfricasTalking API.

    Args:
        phone: Recipient phone number in E.164 format (e.g. +254712345678).
        message: Text content to send.

    Returns:
        dict: Response payload from AfricasTalking, or error details.
    """
    try:
        import africastalking  # type: ignore[import]
    except ImportError:
        frappe.log_error(
            message="africastalking package not installed",
            title="TenderIQ – WhatsApp alert: missing dependency",
        )
        return {"status": "error", "message": "africastalking package not installed"}

    settings = frappe.get_cached_doc("TenderIQ Settings")
    username = settings.get("africastalking_username")
    api_key = settings.get_password("africastalking_api_key") if settings.get("africastalking_api_key") else None

    if not username or not api_key:
        frappe.log_error(
            message="AfricasTalking credentials not configured",
            title="TenderIQ – WhatsApp alert: missing credentials",
        )
        return {"status": "error", "message": "AfricasTalking credentials not configured"}

    try:
        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        response = sms.send(message, [phone])
        return {"status": "success", "response": response}
    except Exception as exc:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"TenderIQ – WhatsApp alert error: {exc.__class__.__name__}",
        )
        return {"status": "error", "message": str(exc)}
