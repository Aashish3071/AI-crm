import frappe
import json
import hmac
import requests
from frappe import _
from frappe.rate_limiter import rate_limit

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_ai_settings():
    """Fetch AI CRM settings from DB.

    SECURITY: Internal only — deliberately NOT whitelisted. This returns the
    decrypted API key, which must never be exposed to any client."""
    try:
        settings = frappe.get_single("AI CRM Settings")
        return {
            "api_url": settings.api_url or "http://host.docker.internal:1234/v1",
            "model_name": settings.model_name or "qwen/qwen3-4b",
            "api_key": settings.get_password("api_key") if settings.api_key else ""
        }
    except Exception:
        # Fallback to default if settings doc does not exist yet
        return {
            "api_url": "http://host.docker.internal:1234/v1",
            "model_name": "qwen/qwen3-4b",
            "api_key": ""
        }

# ---------------------------------------------------------------------------
# LLM Caller
# ---------------------------------------------------------------------------

def call_llm(system_prompt, user_prompt, json_response=False):
    """Utility function to invoke the local LM Studio model."""
    settings = get_ai_settings()
    url = f"{settings['api_url'].rstrip('/')}/chat/completions"
    
    headers = {
        "Content-Type": "application/json"
    }
    if settings["api_key"]:
        headers["Authorization"] = f"Bearer {settings['api_key']}"
        
    payload = {
        "model": settings["model_name"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2048
    }
    
    # Note: Omit response_format as some LM Studio versions reject "json_object"
    # and we already do clean manual regex parsing in _parse_json_response.

    try:
        # (connect timeout, read timeout) — never hang a web worker indefinitely
        response = requests.post(url, headers=headers, json=payload, timeout=(10, 120))
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        frappe.log_error("AI CRM: LLM request timed out (120s read limit)", "AI CRM Error")
        return None
    except requests.exceptions.ConnectionError:
        frappe.log_error("AI CRM: Cannot connect to LM Studio. Is it running?", "AI CRM Error")
        return None
    except Exception as e:
        frappe.log_error(f"AI CRM LLM Call Failed: {str(e)}", "AI CRM Error")
        return None


def _parse_json_response(text):
    """Clean and parse a JSON response from LLM, handling markdown fences and thinking tags."""
    if not text:
        return None
    clean = text.strip()
    
    # Strip <think>...</think> tags (Qwen3 thinking mode)
    import re
    clean = re.sub(r'<think>.*?</think>', '', clean, flags=re.DOTALL).strip()
    
    # Strip markdown code fences
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    
    try:
        return json.loads(clean.strip(), strict=False)
    except Exception as e:
        # Robust regex-based fallback to parse subject/body/score/explanation 
        # in case of unescaped quotes or literal newlines in the JSON string
        result = {}
        
        # Extract score (integer)
        score_match = re.search(r'"score"\s*:\s*(\d+)', clean)
        if score_match:
            result["score"] = int(score_match.group(1))
            
        # Extract explanation
        explanation_match = re.search(r'"explanation"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.DOTALL)
        if explanation_match:
            result["explanation"] = explanation_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            
        # Extract subject
        subject_match = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.DOTALL)
        if subject_match:
            result["subject"] = subject_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            
        # Extract body
        body_match = re.search(r'"body"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.DOTALL)
        if body_match:
            result["body"] = body_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            
        # Extract name/first_name/last_name/company/organization/biggest_challenge for smart entry
        for field in ["first_name", "last_name", "email", "organization", "company", "job_title", "biggest_challenge"]:
            match = re.search(r'"' + field + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', clean, re.DOTALL)
            if match:
                result[field] = match.group(1).replace('\\"', '"').replace('\\n', '\n')
                
        if result:
            return result
        raise e


def _build_lead_context(lead):
    """Build a rich text summary of a CRM Lead for AI prompts."""
    parts = []
    if lead.lead_name:
        parts.append(f"Contact Name: {lead.lead_name}")
    if lead.email:
        parts.append(f"Email: {lead.email}")
    if lead.organization:
        parts.append(f"Company: {lead.organization}")
    if lead.get("industry"):
        parts.append(f"Industry: {lead.industry}")
    if lead.get("job_title"):
        parts.append(f"Job Title: {lead.job_title}")
    if lead.get("no_of_employees"):
        parts.append(f"Company Size: {lead.no_of_employees}")
    if lead.get("annual_revenue"):
        parts.append(f"Annual Revenue: {lead.annual_revenue}")
    if lead.get("territory"):
        parts.append(f"Region: {lead.territory}")
    if lead.get("source"):
        parts.append(f"Lead Source: {lead.source}")
    if lead.get("biggest_challenge"):
        parts.append(f"Biggest Challenge: {lead.biggest_challenge}")
    if lead.status:
        parts.append(f"Current Status: {lead.status}")
    if lead.get("website"):
        parts.append(f"Website: {lead.website}")
        
    # Load associated FCRM Notes
    if frappe.db.exists("DocType", "FCRM Note"):
        notes = frappe.get_all(
            "FCRM Note",
            filters={
                "reference_doctype": "CRM Lead",
                "reference_docname": lead.name
            },
            fields=["title", "content"]
        )
        if notes:
            note_strings = []
            for n in notes:
                clean_content = frappe.utils.strip_html(n.content or "")
                note_strings.append(f"- {n.title}: {clean_content}")
            parts.append("Recent Interaction Notes:\n" + "\n".join(note_strings))
    
    return "\n".join(parts) if parts else "No detailed information available for this lead."


def _build_deal_context(deal):
    """Build a rich text summary of a CRM Deal for AI prompts."""
    parts = []
    if deal.name:
        parts.append(f"Deal ID: {deal.name}")
    if deal.get("lead_name"):
        parts.append(f"Lead Name: {deal.lead_name}")
    if deal.organization:
        parts.append(f"Company/Organization: {deal.organization}")
    if deal.get("deal_value"):
        parts.append(f"Deal Value: {deal.deal_value}")
    if deal.status:
        parts.append(f"Deal Status: {deal.status}")
    if deal.get("expected_closing_date"):
        parts.append(f"Expected Close Date: {deal.expected_closing_date}")
        
    # Load associated FCRM Notes
    if frappe.db.exists("DocType", "FCRM Note"):
        notes = frappe.get_all(
            "FCRM Note",
            filters={
                "reference_doctype": "CRM Deal",
                "reference_docname": deal.name
            },
            fields=["title", "content"]
        )
        if notes:
            note_strings = []
            for n in notes:
                clean_content = frappe.utils.strip_html(n.content or "")
                note_strings.append(f"- {n.title}: {clean_content}")
            parts.append("Recent Deal Notes:\n" + "\n".join(note_strings))
    
    return "\n".join(parts) if parts else "No detailed information available for this deal."


# ---------------------------------------------------------------------------
# API: Smart Data Entry (email → lead)
# ---------------------------------------------------------------------------

@frappe.whitelist()
@rate_limit(limit=20, seconds=60 * 60)
def smart_entry(email_body):
    """API endpoint to parse raw email and create a Lead in the CRM."""
    if not email_body:
        frappe.throw(_("Email body is required"))

    email_body = str(email_body)
    if len(email_body) > 10000:
        frappe.throw(_("Email body is too long (maximum 10,000 characters)"))

    # User must be allowed to create Leads — no silent permission bypass
    if not frappe.has_permission("CRM Lead", ptype="create"):
        frappe.throw(_("You do not have permission to create Leads"), frappe.PermissionError)


    system_prompt = (
        "You are an AI assistant for a CRM. Analyze the incoming email and extract lead info. "
        "Return ONLY a JSON object (no extra text) with these keys: "
        "'first_name', 'last_name', 'email', 'organization' (company name, 'Unknown' if not found), "
        "'job_title' (if mentioned), 'biggest_challenge' (summary of their problem, max 2 sentences)."
    )
    
    response_text = call_llm(system_prompt, email_body, json_response=True)
    if not response_text:
        frappe.throw(_("Failed to communicate with local AI model."))
        
    try:
        data = _parse_json_response(response_text)

        # Validate the LLM-extracted email before storing it
        from frappe.utils import validate_email_address
        email = validate_email_address(str(data.get("email") or "").strip(), throw=False) or ""

        lead = frappe.get_doc({
            "doctype": "CRM Lead",
            "first_name": data.get("first_name") or "New",
            "last_name": data.get("last_name") or "Lead",
            "email": email,
            "organization": data.get("organization") or "Unknown",
            "job_title": data.get("job_title") or "",
            "biggest_challenge": data.get("biggest_challenge") or ""
        })
        # Respect the user's actual permissions — insert() enforces them
        lead.insert()
        frappe.db.commit()

        return {"status": "success", "lead_name": lead.name, "data": data}
    except frappe.PermissionError:
        raise
    except Exception:
        # Log full detail server-side; never leak internals to the client
        frappe.log_error(frappe.get_traceback(), "Smart Entry Error")
        frappe.throw(_("Could not create a lead from this email. Please try again or contact your administrator."))


# ---------------------------------------------------------------------------
# API: Predictive Lead Scoring
# ---------------------------------------------------------------------------

@frappe.whitelist()
@rate_limit(limit=60, seconds=60 * 60)
def score_lead(lead_name):
    """Evaluates the lead profile using AI and updates its score."""
    if not lead_name:
        frappe.throw(_("Lead Name is required"))
        
    # Write permission required — this endpoint modifies the lead (ai_score fields)
    if not frappe.has_permission("CRM Lead", doc=lead_name, ptype="write"):
        frappe.throw(_("You do not have permission to update this Lead"), frappe.PermissionError)

    lead = frappe.get_doc("CRM Lead", lead_name)
    lead_info = _build_lead_context(lead)

    system_prompt = (
        "You are an expert B2B sales analyst for a CRM/ERP software company. "
        "Evaluate the quality of this lead and predict their likelihood to convert. "
        "Consider factors like: company size, having a clear business challenge, "
        "job seniority, industry fit, and engagement level.\n\n"
        "Return ONLY a JSON object with exactly these keys:\n"
        "- \"score\": integer 0-100 (conversion likelihood)\n"
        "- \"explanation\": string (1-2 sentence justification)\n\n"
        "Example: {\"score\": 75, \"explanation\": \"Mid-size tech company with clear CRM needs and decision-maker contact.\"}"
    )
    
    response_text = call_llm(system_prompt, lead_info, json_response=True)
    if not response_text:
        return {"status": "error", "message": "Failed to get AI score. Is LM Studio running?"}
        
    try:
        data = _parse_json_response(response_text)
        
        score = max(0, min(100, int(data.get("score", 50))))
        explanation = str(data.get("explanation", ""))
        
        lead.db_set("ai_score", score)
        lead.db_set("ai_score_explanation", explanation)
        frappe.db.commit()
        
        return {"status": "success", "score": score, "explanation": explanation}
    except Exception as e:
        frappe.log_error(f"Lead scoring logic failed: {str(e)}", "Lead Scoring Error")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# API: Action Recommendation (follow-up email draft)
# ---------------------------------------------------------------------------

@frappe.whitelist()
@rate_limit(limit=60, seconds=60 * 60)
def recommend_action(lead_name):
    """Generates a personalized follow-up email draft for a lead."""
    if not lead_name:
        frappe.throw(_("Lead Name is required"))
        
    # Write permission required — this endpoint modifies the lead (followup draft fields)
    if not frappe.has_permission("CRM Lead", doc=lead_name, ptype="write"):
        frappe.throw(_("You do not have permission to update this Lead"), frappe.PermissionError)

    lead = frappe.get_doc("CRM Lead", lead_name)
    lead_info = _build_lead_context(lead)

    system_prompt = (
        "You are an expert sales writer. Draft a short, highly personalized follow-up email. "
        "CRITICAL INSTRUCTIONS:\n"
        "1. Prioritize specific customer challenges and requirements mentioned in 'Biggest Challenge' or 'Recent Interaction Notes'.\n"
        "2. If notes mention concrete needs (like migrating from spreadsheets, requiring email integration, or team collaboration), address them directly. Do NOT write generic text.\n"
        "3. NEVER use generic business jargon like 'strategic initiatives', 'support your goals', 'align with objectives', or 'understand challenges'.\n"
        "4. Keep it short (under 120 words), direct, warm, and highly professional.\n\n"
        "Return ONLY a JSON object with exactly these keys:\n"
        "- \"subject\": string (email subject line)\n"
        "- \"body\": string (email body, use [Your Name] as placeholder for sender)\n\n"
        "Example: {\"subject\": \"Replacing spreadsheets at [Company Name]\", \"body\": \"Hi [Name],\\n\\n...\"}"
    )
    
    response_text = call_llm(system_prompt, lead_info, json_response=True)
    if not response_text:
        return {"status": "error", "message": "Failed to generate email draft. Is LM Studio running?"}
        
    try:
        data = _parse_json_response(response_text)
        
        subject = str(data.get("subject", "Follow-up"))
        body = str(data.get("body", ""))
        
        lead.db_set("suggested_followup_subject", subject)
        lead.db_set("suggested_followup_body", body)
        frappe.db.commit()
        
        return {"status": "success", "subject": subject, "body": body}
    except Exception as e:
        frappe.log_error(f"Action recommendation failed: {str(e)}", "Action Recommendation Error")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# API: Chat-based Insights
# ---------------------------------------------------------------------------

@frappe.whitelist()
@rate_limit(limit=60, seconds=60 * 60)
def chat_query(query):
    """AI Chat Assistant that answers analytical questions about the CRM database."""
    if not query:
        frappe.throw(_("Query is required"))

    query = str(query)
    if len(query) > 2000:
        frappe.throw(_("Query is too long (maximum 2,000 characters)"))

    # Verify the logged-in user has permission to read CRM Leads
    try:
        if not frappe.has_permission("CRM Lead", ptype="read"):
            return {"response": "I apologize, but you do not have permission to view CRM data."}
    except Exception:
        return {"response": "I apologize, but you do not have permission to view CRM data."}
        
    # Gather real statistics from the database (respecting user permissions / Sales Hierarchy)
    all_permitted_leads = frappe.get_list("CRM Lead", fields=["status", "industry"], ignore_permissions=False)
    lead_count = len(all_permitted_leads)
    
    # Lead status breakdown (from permitted leads)
    lead_status_map = {}
    industry_counts = {}
    for l in all_permitted_leads:
        status = l.get("status") or "Unknown"
        lead_status_map[status] = lead_status_map.get(status, 0) + 1
        ind = l.get("industry")
        if ind:
            industry_counts[ind] = industry_counts.get(ind, 0) + 1
            
    lead_statuses = [{"status": k, "count": v} for k, v in lead_status_map.items()]
    
    # Organization count (respecting permissions)
    org_count = 0
    if frappe.db.exists("DocType", "CRM Organization"):
        org_count = len(frappe.get_list("CRM Organization", fields=["name"], ignore_permissions=False))
    
    # Deal statistics (respecting permissions)
    deal_stats = ""
    if frappe.db.exists("DocType", "CRM Deal"):
        all_deals = frappe.get_list("CRM Deal", fields=["status", "deal_value"], ignore_permissions=False)
        deal_count = len(all_deals)
        deal_breakdown = {}
        for d in all_deals:
            status = d.get("status") or "Unknown"
            val = float(d.get("deal_value") or 0.0)
            if status not in deal_breakdown:
                deal_breakdown[status] = {"count": 0, "total_value": 0.0}
            deal_breakdown[status]["count"] += 1
            deal_breakdown[status]["total_value"] += val
            
        deal_breakdown_list = [{"status": k, "count": v["count"], "total_value": v["total_value"]} for k, v in deal_breakdown.items()]
        deal_stats = f"Total Deals: {deal_count}\nDeal breakdown: {json.dumps(deal_breakdown_list, default=str)}"
    
    # Task / Follow-up statistics (respecting permissions)
    task_stats = ""
    if frappe.db.exists("DocType", "CRM Task"):
        all_tasks = frappe.get_list("CRM Task", fields=["status"], ignore_permissions=False)
        task_count = len(all_tasks)
        pending_count = 0
        task_breakdown = {}
        for t in all_tasks:
            status = t.get("status") or "Unknown"
            task_breakdown[status] = task_breakdown.get(status, 0) + 1
            if status not in ["Done", "Canceled"]:
                pending_count += 1
                
        task_breakdown_list = [{"status": k, "count": v} for k, v in task_breakdown.items()]
        task_stats = f"Total Tasks/Follow-ups: {task_count}\nPending/Left Follow-ups: {pending_count}\nTask status breakdown: {json.dumps(task_breakdown_list, default=str)}"
    
    # Top industries (from permitted leads)
    sorted_industries = sorted(industry_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    industries = [{"industry": k, "count": v} for k, v in sorted_industries]
    
    # Search for specific leads or deals referenced in the query
    words = [w.strip("?,.!\"'") for w in query.split() if len(w) > 2]
    specific_contexts = []
    
    # Skip common query terms
    stop_words = {
        "i", "me", "my", "we", "us", "our", "you", "your", "he", "she", "they", "it",
        "and", "but", "or", "so", "for", "with", "about", "against", "between",
        "the", "a", "an", "this", "that", "these", "those", "how", "what", "why",
        "who", "where", "when", "which", "whom", "whose", "whose", "whom",
        "draft", "write", "create", "make", "send", "email", "mail", "followup",
        "follow-up", "letter", "template", "message", "crm", "erp", "lead", "leads",
        "deal", "deals", "task", "tasks", "contact", "contacts", "show", "get", "tell"
    }
    
    search_terms = [w for w in words if w.lower() not in stop_words]
    matching_leads = []
    matching_deals = []
    
    if search_terms:
        for term in search_terms[:3]:
            # Search leads (respecting permissions)
            leads = frappe.get_list(
                "CRM Lead",
                or_filters=[
                    ["lead_name", "like", f"%{term}%"],
                    ["first_name", "like", f"%{term}%"],
                    ["last_name", "like", f"%{term}%"],
                    ["organization", "like", f"%{term}%"],
                    ["email", "like", f"%{term}%"]
                ],
                fields=["name"],
                limit=3,
                ignore_permissions=False
            )
            for l in leads:
                if l.name not in matching_leads:
                    matching_leads.append(l.name)
            
            # Search deals (respecting permissions)
            if frappe.db.exists("DocType", "CRM Deal"):
                deals = frappe.get_list(
                    "CRM Deal",
                    or_filters=[
                        ["name", "like", f"%{term}%"],
                        ["lead_name", "like", f"%{term}%"],
                        ["organization", "like", f"%{term}%"],
                        ["email", "like", f"%{term}%"]
                    ],
                    fields=["name"],
                    limit=3,
                    ignore_permissions=False
                )
                for d in deals:
                    if d.name not in matching_deals:
                        matching_deals.append(d.name)
                        
    for lead_name in matching_leads[:3]:
        # Enforce document read permission before compiling details
        if frappe.has_permission("CRM Lead", doc=lead_name, ptype="read"):
            lead_doc = frappe.get_doc("CRM Lead", lead_name)
            specific_contexts.append(f"--- MATCHING LEAD DETAILED INFO ({lead_name}) ---\n" + _build_lead_context(lead_doc))
        
    for deal_name in matching_deals[:3]:
        # Enforce document read permission before compiling details
        if frappe.has_permission("CRM Deal", doc=deal_name, ptype="read"):
            deal_doc = frappe.get_doc("CRM Deal", deal_name)
            specific_contexts.append(f"--- MATCHING DEAL DETAILED INFO ({deal_name}) ---\n" + _build_deal_context(deal_doc))
        
    specific_context_str = "\n\n".join(specific_contexts) if specific_contexts else "No specific leads or deals were matched in this query."
    
    context = (
        f"CRM Database Summary:\n"
        f"- Total Leads: {lead_count}\n"
        f"- Lead Status Breakdown: {json.dumps(lead_statuses, default=str)}\n"
        f"- Total Organizations: {org_count}\n"
        f"- {deal_stats}\n"
        f"- {task_stats}\n"
        f"- Top Industries: {json.dumps(industries, default=str)}\n\n"
        f"Specific CRM Data matched for your query:\n"
        f"{specific_context_str}"
    )
    
    system_prompt = (
        f"You are the AI Sales Assistant / Advisor for an AI-powered CRM system.\n\n"
        f"Here is the database summary and matched records:\n{context}\n\n"
        f"CRITICAL SYSTEM INSTRUCTIONS:\n"
        f"1. GROUNDING: Ground all answers strictly in the provided data. If the user asks about a specific contact, you must search the matches. Do not hallucinate names, emails, values, or metrics.\n"
        f"2. SPECIFICITY OVER JARGON: When drafting emails, you MUST prioritize the specific requirements and challenges listed in 'Biggest Challenge' or 'Recent Interaction Notes' (e.g., transition from spreadsheets, email integration, team collaboration, implementation timeline). Address these details directly in the email body.\n"
        f"3. BAN CORPO-JARGON: Never write generic filler phrases like 'explore strategic initiatives', 'understand your goals', 'explore how we can align', or 'position our offerings'. Speak like a real human offering to solve a real, concrete problem.\n"
        f"4. DRAFT FORMAT: If the user asks to draft a follow-up email, output the subject line and email body cleanly. Keep the email concise (under 120 words), direct, and highly relevant to the lead's notes.\n"
        f"5. NO DATA FALLBACK: If no specific contact information is matched, do not draft a placeholder email. Ask the user for the contact's name or specific context."
    )
    
    response = call_llm(system_prompt, query, json_response=False)
    if not response:
        return {"response": "I apologize, I'm unable to connect to the AI model right now. Please check if LM Studio is running."}
    
    # Strip thinking tags from chat responses too
    import re
    response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

    return {"response": response}


# ---------------------------------------------------------------------------
# API: Generic Lead-Capture Webhook (Zapier / Make / any external platform)
# ---------------------------------------------------------------------------

# Only these fields may be written from an external payload. Everything else is
# ignored, so a malicious caller cannot set owner, permissions, scores, etc.
_WEBHOOK_DATA_FIELDS = {
    "first_name", "last_name", "email", "mobile_no", "phone",
    "organization", "job_title", "website", "lead_name",
    "biggest_challenge",
}
# Link fields are accepted but validated against existing records before use,
# so an unknown value from an ad platform can't break lead creation.
_WEBHOOK_LINK_FIELDS = {
    "source": "CRM Lead Source",
    "territory": "CRM Territory",
    "industry": "CRM Industry",
}
_WEBHOOK_MESSAGE_ALIASES = ("message", "notes", "comments", "description", "enquiry")


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="crm_lead_webhook", limit=120, seconds=60)
def capture_lead(**kwargs):
    """Public webhook that turns an external payload into a CRM Lead.

    Auth: a shared secret in site config (`crm_lead_webhook_token`), supplied
    either as the `X-CRM-Webhook-Token` request header or a `token` field.
    Set it with:  bench --site <site> set-config crm_lead_webhook_token <secret>

    Designed for Zapier/Make/webhook sources so leads from Google, Meta,
    LinkedIn, TikTok, web forms, etc. can all be captured through one endpoint.
    """
    # 1. Authenticate the caller with a constant-time secret comparison
    expected = frappe.conf.get("crm_lead_webhook_token")
    if not expected:
        # Webhook is disabled until an admin configures a secret
        frappe.throw(_("Lead capture webhook is not enabled."), frappe.ValidationError)

    token = frappe.get_request_header("X-CRM-Webhook-Token") or kwargs.get("token") or ""
    if not hmac.compare_digest(str(token), str(expected)):
        raise frappe.PermissionError(_("Invalid webhook token."))

    # 2. Collect only allow-listed data fields, each length-capped
    data = {}
    for field in _WEBHOOK_DATA_FIELDS:
        val = kwargs.get(field)
        if val not in (None, ""):
            data[field] = str(val)[:1000]

    # Map a free-text message onto the AI "biggest_challenge" field
    if not data.get("biggest_challenge"):
        for alias in _WEBHOOK_MESSAGE_ALIASES:
            if kwargs.get(alias):
                data["biggest_challenge"] = str(kwargs.get(alias))[:2000]
                break

    # 3. Accept link fields only when the target record actually exists
    for field, doctype in _WEBHOOK_LINK_FIELDS.items():
        val = kwargs.get(field)
        if val and frappe.db.exists(doctype, str(val)):
            data[field] = str(val)

    # 4. Validate email if present
    if data.get("email"):
        from frappe.utils import validate_email_address
        data["email"] = validate_email_address(data["email"], throw=False) or ""
        if not data["email"]:
            data.pop("email")

    # 5. Require at least one identifying field so we don't create empty junk
    if not any(data.get(f) for f in ("email", "mobile_no", "phone", "organization", "first_name")):
        frappe.throw(
            _("Provide at least one of: email, mobile_no, phone, organization, first_name."),
            frappe.ValidationError,
        )

    data.setdefault("first_name", "New")
    data.setdefault("last_name", "Lead")

    # 6. Create the lead. ignore_permissions is intentional: the caller is an
    #    anonymous webhook, authorised by the secret token above, not by a user.
    try:
        lead = frappe.get_doc(dict(doctype="CRM Lead", **data))
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Lead Webhook Error")
        frappe.throw(_("Could not create the lead from the provided data."))

    return {"status": "success", "lead": lead.name}


# ---------------------------------------------------------------------------
# API: Webhook configuration for the Lead Syncing settings UI
# ---------------------------------------------------------------------------

_WEBHOOK_METHOD_PATH = "/api/method/ai_crm.api.capture_lead"


def _require_system_manager():
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only administrators can manage the lead webhook."), frappe.PermissionError)


def _generate_and_store_webhook_token():
    """Create a fresh webhook secret and persist it to site config."""
    import secrets
    from frappe.installer import update_site_config

    token = secrets.token_hex(24)
    update_site_config("crm_lead_webhook_token", token)
    # Reflect immediately in the current request's config
    frappe.local.conf["crm_lead_webhook_token"] = token
    return token


@frappe.whitelist()
def get_lead_webhook_config():
    """Return the lead-capture webhook path + token for the settings UI.

    System Manager only. Generates and stores a token on first access, so the
    webhook is ready to use without any shell command."""
    _require_system_manager()
    token = frappe.conf.get("crm_lead_webhook_token")
    if not token:
        token = _generate_and_store_webhook_token()
    return {"path": _WEBHOOK_METHOD_PATH, "token": token, "header": "X-CRM-Webhook-Token"}


@frappe.whitelist()
def regenerate_lead_webhook_token():
    """Rotate the webhook secret. System Manager only."""
    _require_system_manager()
    token = _generate_and_store_webhook_token()
    return {"path": _WEBHOOK_METHOD_PATH, "token": token, "header": "X-CRM-Webhook-Token"}
