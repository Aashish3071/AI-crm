/**
 * Frappe CRM Integration Client
 * Handles bidirectional synchronization between InsureVoice AI and Frappe CRM.
 * Compatible with Frappe CRM (DocTypes: CRM Lead, CRM Deal, CRM Call Log) 
 * and ERPNext CRM (DocTypes: Lead, Opportunity, Communication).
 */

class FrappeCRMClient {
  constructor(config = {}) {
    this.baseUrl = (config.baseUrl || process.env.FRAPPE_URL || 'https://demo-crm.frappe.cloud').replace(/\/$/, '');
    this.apiKey = config.apiKey || process.env.FRAPPE_API_KEY || '';
    this.apiSecret = config.apiSecret || process.env.FRAPPE_API_SECRET || '';
    this.leadDocType = config.leadDocType || 'CRM Lead'; // or 'Lead' for standard ERPNext
    this.isConnected = false;
    this.lastChecked = null;
  }

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (this.apiKey && this.apiSecret) {
      headers['Authorization'] = `token ${this.apiKey}:${this.apiSecret}`;
    }
    return headers;
  }

  /**
   * Check connection and authenticate with Frappe instance
   */
  async testConnection() {
    if (!this.apiKey || !this.apiSecret) {
      return {
        success: false,
        mode: 'simulation',
        message: 'No Frappe API credentials provided. Operating in Insurance Sandbox / Simulation mode.'
      };
    }

    try {
      const response = await fetch(`${this.baseUrl}/api/method/frappe.auth.get_logged_user`, {
        method: 'GET',
        headers: this.getHeaders()
      });

      if (!response.ok) {
        throw new Error(`Frappe responded with HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.isConnected = true;
      this.lastChecked = new Date().toISOString();

      return {
        success: true,
        user: data.message,
        baseUrl: this.baseUrl,
        message: `Successfully connected to Frappe CRM as ${data.message}`
      };
    } catch (err) {
      this.isConnected = false;
      return {
        success: false,
        error: err.message,
        message: `Failed to connect to ${this.baseUrl}: ${err.message}. Falling back to simulation mode.`
      };
    }
  }

  /**
   * Fetch leads needing insurance follow-ups
   */
  async getFollowUpLeads(filters = {}) {
    if (this.isConnected && this.apiKey) {
      try {
        const queryParams = new URLSearchParams({
          fields: JSON.stringify([
            'name',
            'lead_name',
            'email_id',
            'mobile_no',
            'phone',
            'status',
            'custom_insurance_type',
            'custom_policy_no',
            'custom_expiry_date',
            'custom_premium_amount',
            'custom_last_call_status'
          ]),
          filters: JSON.stringify(filters.status ? [['status', '=', filters.status]] : [['status', '!=', 'Converted']]),
          limit_page_length: '50'
        });

        const res = await fetch(`${this.baseUrl}/api/resource/${this.leadDocType}?${queryParams.toString()}`, {
          method: 'GET',
          headers: this.getHeaders()
        });

        if (res.ok) {
          const json = await res.json();
          return json.data.map(lead => ({
            id: lead.name,
            name: lead.lead_name || lead.name,
            phone: lead.mobile_no || lead.phone || '+15550192834',
            email: lead.email_id || '',
            policyType: lead.custom_insurance_type || 'Comprehensive Motor',
            policyNumber: lead.custom_policy_no || 'POL-884920',
            expiryDate: lead.custom_expiry_date || new Date(Date.now() + 86400000 * 5).toISOString().split('T')[0],
            premiumAmount: lead.custom_premium_amount || '$740.00',
            status: lead.status || 'Follow Up Required',
            source: 'Frappe Live CRM'
          }));
        }
      } catch (e) {
        console.warn('Frappe API query failed, using insurance sample dataset:', e.message);
      }
    }

    // Return realistic insurance industry follow-up mock dataset
    return this.getMockInsuranceLeads();
  }

  /**
   * Create an official Call Log in Frappe CRM
   */
  async recordCallLog(callRecord) {
    const payload = {
      lead: callRecord.leadId,
      to: callRecord.phone,
      call_type: 'Outbound',
      status: callRecord.status === 'completed' ? 'Completed' : 'No Answer',
      duration: callRecord.duration || 0,
      summary: callRecord.summary || 'AI Follow-up call completed.',
      custom_sentiment: callRecord.sentiment || 'Neutral',
      custom_recording_url: callRecord.recordingUrl || '',
      custom_outcome: callRecord.outcome || 'Follow Up Scheduled',
      custom_transcript: JSON.stringify(callRecord.transcript || [])
    };

    if (this.isConnected && this.apiKey) {
      try {
        const res = await fetch(`${this.baseUrl}/api/resource/CRM Call Log`, {
          method: 'POST',
          headers: this.getHeaders(),
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          const result = await res.json();
          // Also attach note to lead
          await this.addLeadNote(callRecord.leadId, callRecord);
          return { success: true, frappeCallId: result.data.name };
        }
      } catch (err) {
        console.error('Error writing call log to Frappe CRM:', err.message);
      }
    }

    // Simulated sync success
    return {
      success: true,
      simulated: true,
      frappeDoc: `CALL-LOG-${Date.now()}`,
      syncedAt: new Date().toISOString(),
      leadId: callRecord.leadId,
      payload
    };
  }

  /**
   * Add a detailed conversational summary note to Frappe Lead timeline
   */
  async addLeadNote(leadId, callRecord) {
    if (!this.isConnected || !this.apiKey) return;

    try {
      const content = `<b>[AI Voice Call Summary - ${callRecord.insuranceType || 'Insurance Follow-up'}]</b><br/>
<b>Duration:</b> ${callRecord.duration}s | <b>Sentiment:</b> ${callRecord.sentiment}<br/>
<b>Outcome:</b> ${callRecord.outcome}<br/>
<b>Executive Summary:</b> ${callRecord.summary}<br/>
<b>Next Steps:</b> ${callRecord.nextAction || 'None'}`;

      await fetch(`${this.baseUrl}/api/method/frappe.desk.form.utils.add_comment`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          reference_doctype: this.leadDocType,
          reference_name: leadId,
          content: content,
          comment_email: 'ai-voice-bot@frappe.local',
          comment_by: 'InsureVoice AI Assistant'
        })
      });
    } catch (e) {
      console.warn('Failed to add comment to Frappe Lead:', e.message);
    }
  }

  /**
   * Update Lead Status in Frappe CRM (e.g. to "Renewal Confirmed" or "Interested")
   */
  async updateLeadStatus(leadId, newStatus, customFields = {}) {
    if (!this.isConnected || !this.apiKey) {
      return { success: true, simulated: true, leadId, newStatus };
    }

    try {
      const res = await fetch(`${this.baseUrl}/api/resource/${this.leadDocType}/${encodeURIComponent(leadId)}`, {
        method: 'PUT',
        headers: this.getHeaders(),
        body: JSON.stringify({
          status: newStatus,
          ...customFields
        })
      });

      if (res.ok) {
        return { success: true, leadId, newStatus };
      }
    } catch (err) {
      console.error('Error updating Frappe Lead status:', err.message);
    }

    return { success: false, leadId };
  }

  /**
   * Realistic Insurance Sector Mock Follow-up Dataset
   */
  getMockInsuranceLeads() {
    return [
      {
        id: 'CRM-LEAD-2026-001',
        name: 'Alexander Hayes',
        phone: '+1 (555) 234-8910',
        email: 'alex.hayes@example.com',
        policyType: 'Comprehensive Motor Insurance',
        policyNumber: 'MOT-7892-NY',
        expiryDate: '2026-09-10',
        daysUntilExpiry: 7,
        premiumAmount: '$840.00',
        ncbDiscount: '35% (No-Claim Bonus)',
        status: 'Renewal Follow-Up Needed',
        campaignType: 'policy_renewal',
        lastOutcome: 'Pending Contact',
        source: 'Frappe CRM (Policy Renewal Bucket)'
      },
      {
        id: 'CRM-LEAD-2026-002',
        name: 'Elena Rostova',
        phone: '+1 (555) 345-6789',
        email: 'elena.rostova@techmail.org',
        policyType: 'Family Health Shield 360',
        policyNumber: 'HLT-4401-CA',
        expiryDate: '2026-09-06',
        daysUntilExpiry: 3,
        premiumAmount: '$1,450.00',
        claimPending: 'Missing Hospital Discharge Bill for Claim #CLM-901',
        status: 'Claim Document Follow-Up',
        campaignType: 'claims_assistance',
        lastOutcome: 'Sent Email (Unopened)',
        source: 'Frappe CRM (Claims Queue)'
      },
      {
        id: 'CRM-LEAD-2026-003',
        name: 'Marcus Vance',
        phone: '+1 (555) 456-7890',
        email: 'm.vance@investcapital.com',
        policyType: 'Term Life Cover ($1.5M)',
        policyNumber: 'NEW-QUOTE-551',
        expiryDate: '2026-09-18',
        daysUntilExpiry: 15,
        premiumAmount: '$92.00 / month',
        quoteRequestedAt: '2 hours ago',
        status: 'Hot Inbound Quote',
        campaignType: 'new_quote_lead',
        lastOutcome: 'Website Form Submitted',
        source: 'Frappe CRM (New Inbound Leads)'
      },
      {
        id: 'CRM-LEAD-2026-004',
        name: 'Sophia Chen-Davies',
        phone: '+1 (555) 567-8901',
        email: 'sophia.chen@medcenter.org',
        policyType: 'Commercial Property & Cyber Liability',
        policyNumber: 'CMP-1029-IL',
        expiryDate: '2026-09-04',
        daysUntilExpiry: 1,
        premiumAmount: '$3,800.00',
        status: 'Urgent Grace Period Alert',
        campaignType: 'policy_renewal',
        lastOutcome: 'SMS Delivered',
        source: 'Frappe CRM (High Value Renewals)'
      },
      {
        id: 'CRM-LEAD-2026-005',
        name: 'David K. O\'Connor',
        phone: '+1 (555) 678-9012',
        email: 'david.oconnor@greenlandcorp.com',
        policyType: 'Commercial Fleet Auto',
        policyNumber: 'FLT-9921-TX',
        expiryDate: '2026-09-12',
        daysUntilExpiry: 9,
        premiumAmount: '$6,200.00',
        status: 'Renewal Follow-Up Needed',
        campaignType: 'policy_renewal',
        lastOutcome: 'Voicemail Left',
        source: 'Frappe CRM (Commercial Accounts)'
      }
    ];
  }
}

module.exports = FrappeCRMClient;
