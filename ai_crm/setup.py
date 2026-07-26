import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
    """Inject AI fields into the CRM Lead doctype. Safe to re-run (idempotent)."""
    create_custom_fields({
        "CRM Lead": [
            {
                "fieldname": "biggest_challenge",
                "label": "Biggest Challenge",
                "fieldtype": "Small Text",
                "insert_after": "industry",
            },
            {
                "fieldname": "ai_score",
                "label": "AI Score",
                "fieldtype": "Percent",
                "insert_after": "biggest_challenge",
                "read_only": 1
            },
            {
                "fieldname": "ai_score_explanation",
                "label": "AI Score Explanation",
                "fieldtype": "Small Text",
                "insert_after": "ai_score",
                "read_only": 1
            },
            {
                "fieldname": "suggested_followup_subject",
                "label": "Suggested Followup Subject",
                "fieldtype": "Data",
                "insert_after": "ai_score_explanation",
                "read_only": 1,
                "hidden": 1
            },
            {
                "fieldname": "suggested_followup_body",
                "label": "Suggested Followup Body",
                "fieldtype": "Long Text",
                "insert_after": "suggested_followup_subject",
                "read_only": 1,
                "hidden": 1
            }
        ]
    }, update=True)

    hide_upstream_navbar_links()

    # Commit database changes
    frappe.db.commit()


def hide_upstream_navbar_links():
    """Hide admin-UI menu entries that point at the upstream vendor.

    The Desk help menu ships a "Frappe Support" entry linking to
    frappe.io/support. Only administrators can reach the Desk, but this is a
    white-labelled product — the vendor's support link should not be offered
    to whoever administers a customer's system. Runs on install so every
    deployment gets it, and is safe to re-run.
    """
    try:
        settings = frappe.get_single("Navbar Settings")
        changed = False
        for item in (settings.get("help_dropdown") or []):
            route = (item.get("route") or "")
            if "frappe.io" in route or "frappecloud.com" in route:
                if not item.hidden:
                    item.hidden = 1
                    changed = True
        if changed:
            settings.flags.ignore_permissions = True
            settings.save(ignore_permissions=True)
            frappe.clear_cache()
    except Exception:
        # Cosmetic — never fail an install over it
        frappe.log_error(frappe.get_traceback(), "AI CRM: navbar cleanup failed")
