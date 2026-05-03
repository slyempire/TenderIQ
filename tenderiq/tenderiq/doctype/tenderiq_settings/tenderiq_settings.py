# Copyright (c) 2024, TenderIQ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

VALID_CLAUDE_MODELS = [
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]
DEFAULT_MODEL = "claude-3-5-haiku-20241022"


class TenderIQSettings(Document):
    """
    Singleton settings doctype for TenderIQ configuration.

    Stores API keys, feature flags, and scraping configuration.
    """

    def validate(self):
        """Validate settings and apply sensible defaults."""
        self._validate_anthropic_model()
        self._validate_africastalking()
        self._warn_missing_api_key()

    def _validate_anthropic_model(self):
        """Ensure the configured Claude model is a known valid value."""
        if self.anthropic_model and self.anthropic_model not in VALID_CLAUDE_MODELS:
            frappe.msgprint(
                _(
                    "Warning: '{0}' is not a recognised Claude model. "
                    "Valid models are: {1}. Defaulting to {2}."
                ).format(
                    self.anthropic_model,
                    ", ".join(VALID_CLAUDE_MODELS),
                    DEFAULT_MODEL,
                ),
                indicator="orange",
                alert=True,
            )
            self.anthropic_model = DEFAULT_MODEL

        if not self.anthropic_model:
            self.anthropic_model = DEFAULT_MODEL

    def _validate_africastalking(self):
        """Warn if WhatsApp alerts are enabled but AfricasTalking is not configured."""
        if self.enable_whatsapp_alerts:
            if not self.africastalking_api_key or not self.africastalking_username:
                frappe.msgprint(
                    _(
                        "WhatsApp alerts are enabled but AfricasTalking credentials "
                        "(API key and username) are not configured. "
                        "Alerts will not be sent until credentials are provided."
                    ),
                    indicator="orange",
                    alert=True,
                )

    def _warn_missing_api_key(self):
        """Warn if scraping or AI is enabled but the Anthropic key is missing."""
        if self.enable_ppra_scraper and not self.anthropic_api_key:
            frappe.msgprint(
                _(
                    "PPRA scraper is enabled but the Anthropic API key is missing. "
                    "AI-powered document analysis will be skipped."
                ),
                indicator="orange",
                alert=True,
            )

    @frappe.whitelist()
    def test_api_connection(self):
        """
        Validate Anthropic API credentials by making a minimal test call.

        Returns:
            dict: {'status': 'success'|'warning'|'error', 'message': str}
        """
        from tenderiq.tenderiq.integrations import call_claude

        try:
            response = call_claude(
                user_prompt="Reply with exactly: OK",
                system_prompt="You are a connection test. Reply only with OK.",
                max_tokens=10,
            )
            if "OK" in response.upper():
                return {"status": "success", "message": _("API connection successful!")}
            return {
                "status": "warning",
                "message": _("Unexpected response from API: {0}").format(response[:100]),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
