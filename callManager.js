/**
 * InsureVoice AI - Call Session & Campaign Manager
 * Manages call queues, real-time audio sessions, metrics, and CRM synchronizations.
 */

const FrappeCRMClient = require('./frappeClient');
const voiceAgent = require('./voiceAgent');

class CallManager {
  constructor() {
    this.frappeClient = new FrappeCRMClient();
    this.calls = new Map();
    this.campaigns = this.initCampaigns();
    this.seedHistoricalCalls();
  }

  initCampaigns() {
    return [
      {
        id: 'CAMP-RENEW-01',
        name: 'September Motor & Auto Renewal Blast',
        type: 'policy_renewal',
        audienceCount: 142,
        pendingFollowUps: 38,
        completedCalls: 104,
        conversionRate: '68.4%',
        status: 'Active',
        voiceModel: 'ElevenLabs Turbo v2.5 (Sarah)',
        schedule: 'Daily between 10:00 AM - 6:30 PM',
        frappeFilter: "DocType: CRM Lead | status = 'Renewal Due' AND days_to_expiry <= 15"
      },
      {
        id: 'CAMP-CLAIM-02',
        name: 'Urgent Claims Missing Document Follow-up',
        type: 'claims_assistance',
        audienceCount: 45,
        pendingFollowUps: 11,
        completedCalls: 34,
        conversionRate: '82.1%',
        status: 'Active',
        voiceModel: 'ElevenLabs / OpenAI Realtime (David)',
        schedule: 'Immediate upon Claim Status change in Frappe',
        frappeFilter: "DocType: CRM Lead | custom_claim_status = 'Pending Hospital Bills'"
      },
      {
        id: 'CAMP-QUOTE-03',
        name: 'Hot Web Inbound Quote Instant Follow-up',
        type: 'new_quote_lead',
        audienceCount: 89,
        pendingFollowUps: 6,
        completedCalls: 83,
        conversionRate: '41.2%',
        status: 'Active',
        voiceModel: 'Cartesia Sonic (Maya)',
        schedule: 'Real-time Webhook (< 90 seconds from form submit)',
        frappeFilter: "DocType: CRM Lead | source = 'Website Quote' AND status = 'New'"
      }
    ];
  }

  seedHistoricalCalls() {
    const sampleCalls = [
      {
        id: 'CALL-2026-9812',
        leadId: 'CRM-LEAD-2026-001',
        customerName: 'Alexander Hayes',
        phone: '+1 (555) 234-8910',
        insuranceType: 'Comprehensive Motor Insurance',
        policyNumber: 'MOT-7892-NY',
        campaignType: 'policy_renewal',
        status: 'completed',
        duration: 84,
        sentiment: 'Positive',
        outcome: 'Renewal Promised / Link Sent',
        summary: 'Alexander confirmed satisfaction with previous claim settlement. Agreed to renew with 35% NCB discount. SMS payment link sent to his phone.',
        frappeSyncStatus: 'Synced',
        frappeDocId: 'CALL-LOG-2026-019',
        timestamp: new Date(Date.now() - 1000 * 60 * 35).toISOString(),
        transcript: [
          { speaker: 'ai', text: 'Good day, Alexander. This is Sarah calling from Apex Mutual Insurance regarding your Comprehensive Motor Insurance. Your policy is scheduled for renewal in 7 days on 2026-09-10. We\'ve preserved your 35% No-Claim Bonus for an updated premium of $840.00. Would you like me to send a 1-click renewal link to your phone?', timestamp: '10:14:02' },
          { speaker: 'customer', text: 'Hey Sarah, yes I got the letter. Is the coverage exactly the same as last year?', timestamp: '10:14:18' },
          { speaker: 'ai', text: 'Yes, absolutely! Zero depreciation and 24/7 roadside assistance are fully intact with no reduction in coverage.', timestamp: '10:14:27' },
          { speaker: 'customer', text: 'Great, go ahead and text me the payment link.', timestamp: '10:14:38' },
          { speaker: 'ai', text: 'Wonderful, Alexander! I\'ve just dispatched the secure payment link via SMS to +1 (555) 234-8910. Once completed, your certificate will be emailed instantly.', timestamp: '10:14:48' }
        ]
      },
      {
        id: 'CALL-2026-9813',
        leadId: 'CRM-LEAD-2026-002',
        customerName: 'Elena Rostova',
        phone: '+1 (555) 345-6789',
        insuranceType: 'Family Health Shield 360',
        policyNumber: 'HLT-4401-CA',
        campaignType: 'claims_assistance',
        status: 'completed',
        duration: 62,
        sentiment: 'Positive',
        outcome: 'Claim Link Dispatched',
        summary: 'Customer was relieved to hear cashless claim is almost approved. Clarified that hospital discharge bill is required. WhatsApp upload link delivered.',
        frappeSyncStatus: 'Synced',
        frappeDocId: 'CALL-LOG-2026-020',
        timestamp: new Date(Date.now() - 1000 * 60 * 95).toISOString(),
        transcript: [
          { speaker: 'ai', text: 'Hi Elena, this is David calling from Apex Health Insurance Claims. I\'m following up on your recent claim #CLM-901—our team just needs one quick document to finalize your settlement. Do you have a moment?', timestamp: '09:20:10' },
          { speaker: 'customer', text: 'Hi David, yes, which document is missing? I thought the hospital submitted everything.', timestamp: '09:20:21' },
          { speaker: 'ai', text: 'They submitted the indoor case papers, but the final signed discharge summary was missing page two. Can you snap a photo of it?', timestamp: '09:20:34' },
          { speaker: 'customer', text: 'Yes, I have it right on my desk. Can you send me a WhatsApp link?', timestamp: '09:20:44' },
          { speaker: 'ai', text: 'Sending it right now! As soon as you upload, our audit team will clear the payment in 24 hours.', timestamp: '09:20:53' }
        ]
      },
      {
        id: 'CALL-2026-9814',
        leadId: 'CRM-LEAD-2026-003',
        customerName: 'Marcus Vance',
        phone: '+1 (555) 456-7890',
        insuranceType: 'Term Life Cover ($1.5M)',
        policyNumber: 'NEW-QUOTE-551',
        campaignType: 'new_quote_lead',
        status: 'completed',
        duration: 45,
        sentiment: 'Neutral',
        outcome: 'Callback Scheduled',
        summary: 'Lead was in a board meeting. Requested a callback tomorrow at 3:00 PM EST. Automatic Frappe CRM ToDo task scheduled.',
        frappeSyncStatus: 'Synced',
        frappeDocId: 'CALL-LOG-2026-021',
        timestamp: new Date(Date.now() - 1000 * 60 * 180).toISOString(),
        transcript: [
          { speaker: 'ai', text: 'Hello Marcus! This is Maya with Apex Insurance following up on the Term Life quote you requested on our portal. Do you have 2 minutes to discuss the coverage options?', timestamp: '08:11:00' },
          { speaker: 'customer', text: 'Hi Maya, I\'m actually stepping into a client meeting right now. Can you call me back tomorrow afternoon?', timestamp: '08:11:15' },
          { speaker: 'ai', text: 'I completely understand, Marcus. I will note this down and schedule a callback for tomorrow at 3:00 PM. Have a great meeting!', timestamp: '08:11:26' }
        ]
      },
      {
        id: 'CALL-2026-9815',
        leadId: 'CRM-LEAD-2026-004',
        customerName: 'Sophia Chen-Davies',
        phone: '+1 (555) 567-8901',
        insuranceType: 'Commercial Property & Cyber Liability',
        policyNumber: 'CMP-1029-IL',
        campaignType: 'policy_renewal',
        status: 'completed',
        duration: 110,
        sentiment: 'Hesitant',
        outcome: 'Escalated to Licensed Agent',
        summary: 'Client had complex questions regarding cyber extortion rider clauses. Transferred smoothly to senior corporate underwriter.',
        frappeSyncStatus: 'Synced',
        frappeDocId: 'CALL-LOG-2026-022',
        timestamp: new Date(Date.now() - 1000 * 60 * 240).toISOString(),
        transcript: [
          { speaker: 'ai', text: 'Good morning, Sophia. Sarah calling from Apex regarding your Commercial Property and Cyber policy expiring tomorrow.', timestamp: '07:30:00' },
          { speaker: 'customer', text: 'Hi Sarah, our IT auditors want clarification on the ransomware sub-limits before we wire the renewal fee.', timestamp: '07:30:19' },
          { speaker: 'ai', text: 'Understood. Since cyber riders have specific underwriting clauses, let me transfer you directly to our senior underwriter Mr. Reynolds right away.', timestamp: '07:30:35' }
        ]
      }
    ];

    sampleCalls.forEach(call => {
      this.calls.set(call.id, call);
    });
  }

  getMetrics() {
    const all = Array.from(this.calls.values());
    const completed = all.filter(c => c.status === 'completed');
    const positive = completed.filter(c => c.sentiment === 'Positive' || c.outcome.includes('Renewal') || c.outcome.includes('Dispatched'));
    const totalSeconds = completed.reduce((acc, c) => acc + (c.duration || 0), 0);
    const avgDuration = completed.length > 0 ? Math.round(totalSeconds / completed.length) : 0;
    const syncedCount = all.filter(c => c.frappeSyncStatus === 'Synced').length;

    return {
      totalCalls: all.length,
      connectedCalls: completed.length,
      conversionRate: completed.length > 0 ? `${Math.round((positive.length / completed.length) * 100)}%` : '0%',
      avgDurationSeconds: avgDuration,
      frappeSyncHealth: '100%',
      syncedCallsCount: syncedCount,
      activeVoiceEngine: 'ElevenLabs Turbo v2.5 + Deepgram Nova-2',
      voiceLatency: '480ms (Ultra-Low Sub-Second)'
    };
  }

  getAllCalls(filter = {}) {
    let list = Array.from(this.calls.values());
    if (filter.search) {
      const q = filter.search.toLowerCase();
      list = list.filter(c => 
        c.customerName.toLowerCase().includes(q) || 
        c.phone.includes(q) || 
        c.policyNumber.toLowerCase().includes(q)
      );
    }
    if (filter.sentiment) {
      list = list.filter(c => c.sentiment === filter.sentiment);
    }
    // sort descending by timestamp
    return list.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  }

  getCallById(id) {
    return this.calls.get(id);
  }

  async startCallSession(lead, campaignType = 'policy_renewal') {
    const callId = `CALL-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const opening = voiceAgent.generateOpeningGreeting(lead);

    const callRecord = {
      id: callId,
      leadId: lead.id,
      customerName: lead.name,
      phone: lead.phone,
      insuranceType: lead.policyType,
      policyNumber: lead.policyNumber,
      campaignType: campaignType,
      status: 'in-progress',
      duration: 0,
      sentiment: 'Neutral',
      outcome: 'In Conversation',
      summary: 'Call currently active.',
      frappeSyncStatus: 'Pending',
      frappeDocId: null,
      timestamp: new Date().toISOString(),
      transcript: [opening]
    };

    this.calls.set(callId, callRecord);
    return { callRecord, initialGreeting: opening };
  }

  async submitCustomerTurn(callId, customerSpeechText) {
    const call = this.calls.get(callId);
    if (!call) throw new Error('Call session not found');

    const customerTurn = {
      speaker: 'customer',
      text: customerSpeechText,
      timestamp: new Date().toLocaleTimeString()
    };
    call.transcript.push(customerTurn);

    // Get lead context
    const lead = {
      id: call.leadId,
      name: call.customerName,
      phone: call.phone,
      policyType: call.insuranceType,
      policyNumber: call.policyNumber,
      campaignType: call.campaignType,
      premiumAmount: '$840.00',
      ncbDiscount: '35% NCB'
    };

    const result = voiceAgent.processTurn(lead, customerSpeechText, call.transcript);
    call.transcript.push(result.aiTurn);
    call.sentiment = result.sentiment;
    call.outcome = result.outcome;

    if (result.isCallOver) {
      call.status = 'completed';
      const summaryObj = voiceAgent.summarizeCall(lead, call.transcript, result.sentiment, result.outcome);
      call.summary = summaryObj.frappeSyncPayload.summary;
      call.duration = summaryObj.durationSeconds;

      // Automatically sync to Frappe CRM
      await this.syncCallToFrappe(callId);
    }

    return {
      aiTurn: result.aiTurn,
      intent: result.intent,
      sentiment: result.sentiment,
      outcome: result.outcome,
      isCallOver: result.isCallOver,
      call
    };
  }

  async syncCallToFrappe(callId) {
    const call = this.calls.get(callId);
    if (!call) return { success: false, error: 'Call not found' };

    const result = await this.frappeClient.recordCallLog(call);
    if (result.success) {
      call.frappeSyncStatus = 'Synced';
      call.frappeDocId = result.frappeDoc || result.frappeCallId || 'CALL-LOG-SYNCED';
    } else {
      call.frappeSyncStatus = 'Error';
    }

    return result;
  }
}

module.exports = new CallManager();
