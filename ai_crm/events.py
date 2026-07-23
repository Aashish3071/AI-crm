import frappe
import datetime
from frappe.utils import now_datetime


def trigger_lead_scoring(doc, method=None):
    """Enqueue AI scoring in the background when a CRM Lead is created."""
    frappe.enqueue(
        "ai_crm.events.run_scoring_job",
        queue="short",
        timeout=120,
        lead_name=doc.name
    )


def run_scoring_job(lead_name):
    """Background job to calculate AI score for a lead."""
    try:
        from ai_crm.api import score_lead
        score_lead(lead_name)
    except Exception as e:
        frappe.log_error(
            f"AI Scoring Background Job Failed for {lead_name}: {str(e)}",
            "AI CRM Queue Error"
        )


def daily_stale_leads_check():
    """Daily job to find stale leads and generate AI follow-up recommendations."""
    # Define 'stale' as no update in 14 days
    stale_threshold = now_datetime() - datetime.timedelta(days=14)
    
    # Cap per run so a large backlog can't flood the queue or the LLM in one go.
    # The remainder is picked up on subsequent daily runs (oldest first).
    MAX_LEADS_PER_RUN = 50

    stale_leads = frappe.get_all(
        "CRM Lead",
        filters={
            "status": ["not in", ["Converted", "Lost"]],
            "modified": ["<", stale_threshold]
        },
        fields=["name"],
        order_by="modified asc",
        limit=MAX_LEADS_PER_RUN
    )

    for lead in stale_leads:
        frappe.enqueue(
            "ai_crm.api.recommend_action",
            queue="short",
            timeout=120,
            lead_name=lead.name
        )
