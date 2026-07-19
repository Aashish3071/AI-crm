import frappe
import json
import requests
from frappe import _

@frappe.whitelist()
def get_ai_settings():
    """Fetch user settings for AI CRM from DB."""
    try:
        settings = frappe.get_single("AI CRM Settings")
        return {
            "api_url": settings.api_url or "http://host.docker.internal:1234/v1",
            "model_name": settings.model_name or "meta-llama-3-8b-instruct",
            "api_key": settings.get_password("api_key") if settings.api_key else ""
        }
    except Exception:
        # Fallback to default if settings doc does not exist yet
        return {
            "api_url": "http://host.docker.internal:1234/v1",
            "model_name": "meta-llama-3-8b-instruct",
            "api_key": ""
        }

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
        "temperature": 0.2
    }
    
    if json_response:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        frappe.log_error(f"AI CRM LLM Call Failed: {str(e)}", "AI CRM Error")
        return None

@frappe.whitelist()
def smart_entry(email_body):
    """API endpoint to parse raw email and create a Lead in the CRM."""
    if not email_body:
        frappe.throw(_("Email body is required"))
        
    system_prompt = (
        "You are an AI assistant for a CRM. Analyze the incoming email and extract lead info. "
        "You MUST return a JSON object with the following keys: "
        "'name' (person's name), 'email' (sender email), 'company' (company name, default to 'Unknown' if not found), "
        "'biggest_challenge' (a summary of their problem or what they need, maximum 2 sentences). "
        "Do not include any explanation or markdown formatting, just the raw JSON object."
    )
    
    response_text = call_llm(system_prompt, email_body, json_response=True)
    if not response_text:
        frappe.throw(_("Failed to communicate with local AI model."))
        
    try:
        # Clean JSON response of possible markdown code blocks
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        data = json.loads(clean_text.strip())
        
        # Verify and create Lead
        lead = frappe.get_doc({
            "doctype": "CRM Lead",
            "name": data.get("name") or "New Ingestion",
            "email": data.get("email"),
            "organization": data.get("company") or "Acme Corp",
            "biggest_challenge": data.get("biggest_challenge")
        })
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return {"status": "success", "lead_name": lead.name, "data": data}
    except Exception as e:
        frappe.log_error(f"Smart Entry Ingestion failed: {str(e)}", "Smart Entry Error")
        frappe.throw(f"Error parsing email or saving lead: {str(e)}")

@frappe.whitelist()
def score_lead(lead_name):
    """Evaluates the lead profile and updates its score."""
    if not lead_name:
        frappe.throw(_("Lead Name is required"))
        
    lead = frappe.get_doc("CRM Lead", lead_name)
    
    lead_info = (
        f"Lead Name: {lead.name}\n"
        f"Organization: {lead.organization}\n"
        f"Email: {lead.email}\n"
        f"Biggest Challenge: {lead.get('biggest_challenge') or 'Not specified'}\n"
        f"Status: {lead.status}\n"
    )
    
    system_prompt = (
        "You are an expert sales analyst. Evaluate the quality of this CRM Lead. "
        "You MUST return a JSON object with the following keys: "
        "'score' (an integer from 0 to 100 representing how likely they are to convert, based on criteria like having a clear challenge and business details), "
        "'explanation' (a brief 1-2 sentence explanation of the score)."
        "Do not include any extra text or markdown formatting, just the raw JSON object."
    )
    
    response_text = call_llm(system_prompt, lead_info, json_response=True)
    if not response_text:
        return {"status": "error", "message": "Failed to get AI score"}
        
    try:
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        data = json.loads(clean_text.strip())
        
        # Save to custom fields
        lead.db_set("ai_score", int(data.get("score", 50)))
        lead.db_set("ai_score_explanation", data.get("explanation", ""))
        frappe.db.commit()
        
        return {"status": "success", "score": data.get("score"), "explanation": data.get("explanation")}
    except Exception as e:
        frappe.log_error(f"Lead scoring logic failed: {str(e)}", "Lead Scoring Error")
        return {"status": "error", "message": str(e)}

@frappe.whitelist()
def recommend_action(lead_name):
    """Generates a suggested personalized follow-up email draft for a stale lead."""
    if not lead_name:
        frappe.throw(_("Lead Name is required"))
        
    lead = frappe.get_doc("CRM Lead", lead_name)
    
    lead_info = (
        f"Lead Name: {lead.name}\n"
        f"Organization: {lead.organization}\n"
        f"Biggest Challenge: {lead.get('biggest_challenge') or 'Not specified'}\n"
    )
    
    system_prompt = (
        "You are an empathetic CRM sales copywriter. Draft a follow-up email to re-engage this lead. "
        "Focus on their 'Biggest Challenge' and mention that we can help them solve it. Keep it short (under 120 words). "
        "You MUST return a JSON object with keys: "
        "'subject' (email subject line), 'body' (email body text, include placeholders like [Your Name])."
        "Do not include extra markdown syntax."
    )
    
    response_text = call_llm(system_prompt, lead_info, json_response=True)
    if not response_text:
        return {"status": "error", "message": "Failed to generate email draft"}
        
    try:
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        data = json.loads(clean_text.strip())
        
        lead.db_set("suggested_followup_subject", data.get("subject", ""))
        lead.db_set("suggested_followup_body", data.get("body", ""))
        frappe.db.commit()
        
        return {"status": "success", "subject": data.get("subject"), "body": data.get("body")}
    except Exception as e:
        frappe.log_error(f"Action recommendation failed: {str(e)}", "Action Recommendation Error")
        return {"status": "error", "message": str(e)}

@frappe.whitelist()
def chat_query(query):
    """AI Chat Assistant that answers analytical questions about the database securely."""
    if not query:
        frappe.throw(_("Query is required"))
        
    # Get general count statistics from the database to supply as context
    lead_count = frappe.db.count("CRM Lead")
    org_count = frappe.db.count("CRM Organization") if frappe.db.exists("DocType", "CRM Organization") else frappe.db.count("CRM Lead")
    
    # Try fetching some sales statistics
    deal_stats = ""
    if frappe.db.exists("DocType", "CRM Deal"):
        deals = frappe.db.get_all("CRM Deal", fields=["status", "count(name) as qty", "sum(deal_value) as val"], group_by="status")
        deal_stats = json.dumps(deals)
        
    system_prompt = (
        f"You are the AI Sales Assistant for the CRM dashboard. "
        f"Here is current summary statistics from the database:\n"
        f"- Total Leads: {lead_count}\n"
        f"- Total Organizations: {org_count}\n"
        f"- Deal Statistics: {deal_stats}\n\n"
        f"Answer the user's question about the CRM data based on this context. "
        f"If the user asks an analytical question that you cannot fully answer with the summary data, "
        f"politely state the limitations. Keep responses concise, clear, and professional."
    )
    
    response = call_llm(system_prompt, query, json_response=False)
    if not response:
        return {"response": "I apologize, I am unable to connect to the AI model right now."}
        
    return {"response": response}
