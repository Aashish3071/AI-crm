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


def _run_as_system(fn, lead_name, label):
    """Run an AI job for a single lead with system privileges.

    Auto-scoring is a system action, not a user action: a lead may be created by
    the unauthenticated capture webhook, in which case the enqueuing session is
    Guest and the permission check inside the API would fail. `lead_name` is
    always the record we just created, never caller-supplied, so elevating here
    does not widen what can be touched.

    Calls made here draw on the automation budget, keeping interactive AI
    features usable even if automation floods.
    """
    original_user = frappe.session.user
    try:
        frappe.flags.ai_crm_automated = True
        frappe.set_user("Administrator")
        fn(lead_name)
    except Exception as e:
        frappe.log_error(
            f"{label} Background Job Failed for {lead_name}: {str(e)}",
            "AI CRM Queue Error"
        )
    finally:
        frappe.flags.ai_crm_automated = False
        try:
            frappe.set_user(original_user)
        except Exception:
            pass


def run_scoring_job(lead_name):
    """Background job to calculate AI score for a lead."""
    from ai_crm.api import score_lead
    _run_as_system(score_lead, lead_name, "AI Scoring")


def run_followup_job(lead_name):
    """Background job to draft an AI follow-up for a stale lead."""
    from ai_crm.api import recommend_action
    _run_as_system(recommend_action, lead_name, "AI Follow-up")


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
            "ai_crm.events.run_followup_job",
            queue="short",
            timeout=120,
            lead_name=lead.name
        )
