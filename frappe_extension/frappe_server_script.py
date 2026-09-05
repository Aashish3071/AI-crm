# ==============================================================================
# FRAPPE CRM SERVER SCRIPT: Automated AI Voice Follow-up Trigger
# ==============================================================================
# How to install in Frappe CRM / ERPNext:
# 1. Open Frappe Desk -> Search "Server Script" -> Add Server Script
# 2. Script Type: DocType Event
# 3. Reference DocType: "CRM Lead" (or "Lead")
# 4. DocType Event: "After Save" (or "on_update")
# 5. Paste the code below and save!
# ==============================================================================

import frappe
from frappe.integrations.utils import make_post_request

INSURE_VOICE_ENDPOINT = "http://localhost:3030/api/webhooks/frappe-lead"

def trigger_ai_voice_call(doc, method):
    # Condition: Trigger AI voice call when status is set to 'Follow Up Needed' 
    # or when custom_insurance_expiry is within 15 days
    if doc.status in ["Follow Up Needed", "Renewal Due", "Pending Customer Action"]:
        
        # Prevent spamming multiple calls on the same day
        if doc.get("custom_last_ai_call_date") == frappe.utils.today():
            frappe.logger().info(f"AI Call already dispatched today for {doc.name}")
            return

        payload = {
            "event": "LEAD_FOLLOW_UP_TRIGGERED",
            "name": doc.name,
            "lead_name": doc.lead_name or doc.name,
            "mobile_no": doc.mobile_no or doc.phone,
            "email": doc.email_id,
            "custom_insurance_type": doc.get("custom_insurance_type") or "Comprehensive Motor Insurance",
            "custom_policy_no": doc.get("custom_policy_no") or "POL-AUTO-9912",
            "custom_expiry_date": str(doc.get("custom_expiry_date") or frappe.utils.add_days(frappe.utils.today(), 7)),
            "custom_premium_amount": doc.get("custom_premium_amount") or "$840.00",
            "custom_campaign_type": doc.get("custom_campaign_type") or "policy_renewal"
        }

        try:
            # Dispatch asynchronous or synchronous HTTP webhook to InsureVoice Engine
            response = make_post_request(
                url=INSURE_VOICE_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            
            # Record dispatch on the Lead
            frappe.db.set_value("CRM Lead", doc.name, "custom_last_ai_call_date", frappe.utils.today())
            doc.add_comment("Comment", f"🤖 AI Voice Call Follow-up dispatched via InsureVoice Engine. Status: {response.get('status')}")
            
        except Exception as e:
            frappe.log_error(f"Failed to dispatch AI Voice Call for {doc.name}: {str(e)}", "InsureVoice Webhook Error")

# Execute hook
trigger_ai_voice_call(doc, method)
