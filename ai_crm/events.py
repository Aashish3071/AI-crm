import frappe
import datetime
from frappe import _
from frappe.utils import now_datetime


def trigger_lead_scoring(doc, method=None):
    """Enqueue AI scoring in the background when a CRM Lead is created."""
    frappe.enqueue(
        "ai_crm.events.run_scoring_job",
        queue="short",
        timeout=120,
        lead_name=doc.name
    )


#: Desk lives at /app on Frappe 15 and /desk on Frappe 16 — block both.
_DESK_PREFIXES = ("/app", "/desk")


def restrict_desk_access():
    """Keep ordinary CRM users out of the Frappe Desk interface.

    Hiding the menu entry only removes the link; the route stays reachable by
    typing the URL, which exposes the raw framework UI (and its branding) to a
    customer's sales staff. Enforce it server-side instead, and send them back
    to the CRM. Administrators keep access so the system stays maintainable.

    Set `allow_desk_access: 1` in site config to disable this restriction.
    """
    try:
        if frappe.conf.get("allow_desk_access"):
            return
        request = getattr(frappe.local, "request", None)
        if not request:
            return

        path = "/" + (request.path or "").strip("/")
        if not any(path == p or path.startswith(p + "/") for p in _DESK_PREFIXES):
            return

        user = getattr(frappe.session, "user", None)
        # Guests get the normal login flow; don't interfere with it
        if not user or user == "Guest":
            return
        if "System Manager" in frappe.get_roles(user):
            return

        # before_request runs ahead of path resolution, so raising frappe.Redirect
        # here would not attach a Location header. Deny outright instead: Frappe
        # renders its standard not-permitted response, and the user still has the
        # CRM at /crm.
        raise frappe.PermissionError(
            _("The admin interface is not available. Please use the CRM at /crm")
        )
    except frappe.PermissionError:
        raise
    except Exception:
        # Never let this guard break request handling
        frappe.log_error(frappe.get_traceback(), "AI CRM: desk guard failed")


def sync_brand_to_website(doc, method=None):
    """Mirror the CRM's Custom Branding onto the framework's own pages.

    The CRM portal reads brand name/logo/favicon from FCRM Settings, but the
    framework login page reads Website Settings. Without this, a customer sets
    their branding in the CRM and still meets a generic login screen.

    Note: no frappe.db.commit() here — Frappe 16 forbids committing inside
    document hooks; the surrounding transaction handles persistence.
    """
    try:
        values = {}
        if doc.get("brand_logo"):
            values["app_logo"] = doc.brand_logo
        if doc.get("favicon"):
            values["favicon"] = doc.favicon
        if doc.get("brand_name"):
            values["app_name"] = doc.brand_name
        if not values:
            return
        frappe.db.set_single_value("Website Settings", values)
        frappe.clear_cache()
    except Exception:
        # Branding is cosmetic — never block saving CRM settings over it
        frappe.log_error(frappe.get_traceback(), "AI CRM: brand sync failed")


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
