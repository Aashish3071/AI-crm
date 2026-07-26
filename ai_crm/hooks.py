import frappe

app_name = "ai_crm"
app_title = "AI CRM"
app_publisher = "Developer"
app_description = "AI enhancements for Frappe CRM"
app_email = "developer@example.com"
app_license = "mit"

home_page = "crm"

# Run setup scripts on installation
after_install = "ai_crm.setup.after_install"

# Document event hooks
doc_events = {
    "CRM Lead": {
        "after_insert": "ai_crm.events.trigger_lead_scoring",
    },
    # Keep the framework login page on the customer's own branding
    "FCRM Settings": {
        "on_update": "ai_crm.events.sync_brand_to_website",
    },
}

# JS file injection (Desk-side only, CRM portal uses Vue component)
doctype_js = {
    "CRM Lead": "public/js/crm_lead.js"
}

# Scheduler hooks
scheduler_events = {
    "daily": [
        "ai_crm.events.daily_stale_leads_check"
    ]
}
