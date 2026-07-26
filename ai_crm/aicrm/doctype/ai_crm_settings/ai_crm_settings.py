import frappe
from frappe.model.document import Document


class AICRMSettings(Document):
    def validate(self):
        """Fill in the standard endpoint for a known provider.

        The API key is never touched here — it stays in Frappe's encrypted
        password store (or in site_config, which takes precedence).
        """
        from ai_crm.api import PROVIDER_PRESETS

        preset = PROVIDER_PRESETS.get(self.provider)
        if preset and not self.api_url:
            self.api_url = preset

        if self.api_url:
            self.api_url = self.api_url.strip()
            if not self.api_url.startswith(("http://", "https://")):
                frappe.throw(frappe._("API URL must start with http:// or https://"))
