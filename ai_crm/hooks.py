import frappe

app_name = "ai_crm"
app_title = "AI CRM"
app_publisher = "Developer"
app_description = "AI enhancements for Frappe CRM"
app_email = "developer@example.com"
app_license = "mit"

# Run setup scripts on installation
after_install = "ai_crm.setup.after_install"

# Document event hooks
doc_events = {
    "CRM Lead": {
        "after_insert": "ai_crm.hooks.trigger_lead_scoring",
        "on_update": "ai_crm.hooks.trigger_lead_scoring"
    }
}

# JS file injection
doctype_js = {
    "CRM Lead": "public/js/crm_lead.js"
}

# Scheduler hooks
scheduler_events = {
    "daily": [
        "ai_crm.hooks.daily_stale_leads_check"
    ]
}

def trigger_lead_scoring(doc, method=None):
    """Enqueue AI scoring in the background when a CRM Lead is created or updated."""
    # To prevent infinite loop when setting fields inside score_lead
    # we verify that the document is not currently being saved by the AI score process itself
    if doc.flags.in_ai_scoring:
        return
        
    # Enqueue background job to calculate score
    frappe.enqueue(
        "ai_crm.hooks.run_scoring_job",
        queue="short",
        timeout=120,
        lead_name=doc.name
    )

def run_scoring_job(lead_name):
    """Retrieves lead, sets a flag to avoid recursion, and executes the scoring API."""
    try:
        lead = frappe.get_doc("CRM Lead", lead_name)
        lead.flags.in_ai_scoring = True
        
        # Import and run the api method
        from ai_crm.api import score_lead
        score_lead(lead_name)
    except Exception as e:
        frappe.log_error(f"AI Scoring Background Job Failed for {lead_name}: {str(e)}", "AI CRM Queue Error")

def daily_stale_leads_check():
    """Daily job to find stale leads and generate AI follow-up recommendations."""
    import datetime
    from frappe.utils import now_datetime
    
    # Define 'stale' as no update in 14 days
    stale_threshold = now_datetime() - datetime.timedelta(days=14)
    
    # Get active leads that haven't been updated in 14 days
    stale_leads = frappe.get_all(
        "CRM Lead",
        filters={
            "status": ["not in", ["Won", "Lost"]],
            "modified": ["<", stale_threshold]
        },
        fields=["name"]
    )
    
    from ai_crm.api import recommend_action
    for lead in stale_leads:
        # Enqueue recommendation generation to avoid blocking cron
        frappe.enqueue(
            "ai_crm.api.recommend_action",
            queue="short",
            lead_name=lead.name
        )

