import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
    # Inject AI fields into the CRM Lead doctype
    create_custom_fields({
        "CRM Lead": [
            {
                "fieldname": "ai_score",
                "label": "AI Score",
                "fieldtype": "Percent",
                "insert_after": "status",
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
                "read_only": 1
            },
            {
                "fieldname": "suggested_followup_body",
                "label": "Suggested Followup Body",
                "fieldtype": "Long Text",
                "insert_after": "suggested_followup_subject",
                "read_only": 1
            }
        ]
    })
    
    # Commit database changes
    frappe.db.commit()
