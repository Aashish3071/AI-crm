/**
 * InsureVoice AI - Voice Engine & Insurance State Machine
 * Handles conversational turns, natural speech styling, objection handling,
 * and intent detection for Insurance follow-ups.
 */

const INSURANCE_PERSONAS = {
  policy_renewal: {
    agentName: 'Sarah Jenkins',
    role: 'Senior Policy Retention Specialist',
    voiceProvider: 'ElevenLabs Turbo v2.5 / Cartesia Sonic',
    voiceId: '21m00Tcm4TlvDq8ikWAM (Rachel - Natural & Reassuring)',
    tone: 'Warm, respectful, articulate, empathetic',
    systemPrompt: `You are Sarah, a licensed customer care specialist calling on behalf of Apex Mutual Insurance.
You are calling {{customer_name}} regarding their {{policy_type}} (Policy #{{policy_number}}), which is due to expire in {{days_until_expiry}} days on {{expiry_date}}.
Key Objectives:
1. Greet warmly and confirm you are speaking with {{customer_name}}.
2. Inform them their renewal premium is {{premium_amount}} and highlight that their {{ncb_discount}} has been preserved.
3. If they ask about price changes, explain inflation adjustments and that keeping continuous coverage prevents penalties or vehicle re-inspection.
4. Offer to send an instant secure payment link via SMS/WhatsApp or take an authorized one-tap renewal.
5. If they are busy, ask for a convenient time to call back and confirm their preference.
6. If they ask to speak to a licensed human underwriter, immediately transfer without hesitation.`
  },
  claims_assistance: {
    agentName: 'David Chen',
    role: 'Claims Expeditor',
    voiceProvider: 'ElevenLabs / OpenAI Realtime',
    voiceId: 'AZnzlk1XvdvUeBnXmlld (Domi - Empathetic & Clear)',
    tone: 'Compassionate, reassuring, problem-solving',
    systemPrompt: `You are David from Apex Health Claims Team calling {{customer_name}} about Claim #CLM-901 for {{policy_type}}.
Key Objectives:
1. Express empathy regarding their recent hospitalization or medical event.
2. Politely inform them that the cashless approval is 90% ready, but our medical audit team is missing: {{claim_pending}}.
3. Offer to text them a direct upload link so they can snap a photo from their phone in 30 seconds.
4. Assure them their settlement will be dispatched within 24 hours of receiving the document.`
  },
  new_quote_lead: {
    agentName: 'Maya Thorne',
    role: 'Insurance Advisory Specialist',
    voiceProvider: 'Cartesia Sonic / Deepgram',
    voiceId: 'EXAVITQu4vr4xnSDxMaL (Bella - Energetic & Knowledgeable)',
    tone: 'Helpful, consultative, clear, attentive',
    systemPrompt: `You are Maya, an insurance advisor following up on the instant quote {{customer_name}} requested on our website for {{policy_type}}.
Key Objectives:
1. Thank them for inquiring with Apex Insurance.
2. Confirm if they need coverage for just themselves or their family.
3. Highlight key benefits: 100% cashless at over 8,500 partner hospitals, instant digital issuance, zero paperwork.
4. Answer any questions regarding pre-existing illness waiting periods or tax deductions.
5. Offer to lock in the special promotional rate of {{premium_amount}} valid for 48 hours.`
  }
};

class VoiceAgentEngine {
  constructor() {
    this.personas = INSURANCE_PERSONAS;
  }

  getPersona(campaignType = 'policy_renewal') {
    return this.personas[campaignType] || this.personas.policy_renewal;
  }

  /**
   * Produce the initial opening greeting turn tailored to the lead
   */
  generateOpeningGreeting(lead) {
    const persona = this.getPersona(lead.campaignType);
    if (lead.campaignType === 'claims_assistance') {
      return {
        speaker: 'ai',
        role: 'agent',
        text: `Hi ${lead.name}, this is ${persona.agentName} calling from Apex Health Insurance Claims. I hope you're feeling better today. I'm following up on your recent claim #${lead.policyNumber || 'CLM-901'}—our team just needs one quick document to finalize your settlement. Do you have a quick moment?`,
        timestamp: new Date().toISOString(),
        audioLengthMs: 4200
      };
    } else if (lead.campaignType === 'new_quote_lead') {
      return {
        speaker: 'ai',
        role: 'agent',
        text: `Hello ${lead.name}! This is ${persona.agentName} with Apex Insurance. I noticed you just requested a customized quote for ${lead.policyType} on our portal. I wanted to see if you had any quick questions about the policy benefits or need help locking in the promotional rate?`,
        timestamp: new Date().toISOString(),
        audioLengthMs: 4500
      };
    } else {
      // Default: Policy Renewal
      return {
        speaker: 'ai',
        role: 'agent',
        text: `Good day, ${lead.name}. This is ${persona.agentName} calling from Apex Mutual Insurance regarding your ${lead.policyType}. Your policy is scheduled for renewal in ${lead.daysUntilExpiry || 7} days on ${lead.expiryDate}. We've preserved your ${lead.ncbDiscount || 'No-Claim Bonus discount'} for an updated premium of ${lead.premiumAmount}. Would you like me to send a 1-click renewal link to your phone?`,
        timestamp: new Date().toISOString(),
        audioLengthMs: 5100
      };
    }
  }

  /**
   * Process customer response and return next AI turn, detected intent, and sentiment
   */
  processTurn(lead, customerText, conversationHistory = []) {
    const textLower = (customerText || '').toLowerCase();
    const persona = this.getPersona(lead.campaignType);

    let intent = 'inquiry';
    let sentiment = 'Neutral';
    let aiResponse = '';
    let outcome = 'Follow Up In Progress';
    let isCallOver = false;

    // Intent Detection Heuristics
    const isAffirmative = ['yes', 'send it', 'renew', 'payment link', 'sounds good', 'sounds great', 'text me', 'sure', 'okay', 'proceed', 'go ahead', 'link', 'do that']
      .some(phrase => textLower.includes(phrase));

    if (isAffirmative) {
      intent = 'confirm_renewal';
      sentiment = 'Positive';
      outcome = 'Renewal Promised / Link Sent';
      aiResponse = `Wonderful, ${lead.name}! I've just dispatched the secure payment link via SMS to ${lead.phone}. Once you click and complete it, your updated policy certificate will be instantly delivered to your email. Thank you for continuing your journey with Apex Insurance!`;
      isCallOver = true;
    } else if (textLower.includes('busy') || textLower.includes('driving') || textLower.includes('call later') || textLower.includes('call back') || textLower.includes('meeting')) {
      intent = 'request_reschedule';
      sentiment = 'Neutral';
      outcome = 'Callback Scheduled';
      aiResponse = `I completely understand, ${lead.name}. I will note this down in our system and schedule a callback for tomorrow afternoon. Drive safe and have a great rest of your day!`;
      isCallOver = true;
    } else if (textLower.includes('why') || textLower.includes('increase') || textLower.includes('expensive') || textLower.includes('high') || textLower.includes('price')) {
      intent = 'price_objection';
      sentiment = 'Hesitant';
      outcome = 'Price Objection Handled';
      aiResponse = `I completely understand your concern about premium rates. The modest adjustment accounts for medical inflation and revised parts coverage, but we have applied your maximum ${lead.ncbDiscount || 'discount'} to keep it as low as possible. We can also explore adjusting your voluntary deductible to lower the premium by 15%. Would you like to review those options?`;
    } else if (textLower.includes('human') || textLower.includes('agent') || textLower.includes('speak to') || textLower.includes('advisor') || textLower.includes('manager')) {
      intent = 'escalate_human';
      sentiment = 'Neutral';
      outcome = 'Escalated to Licensed Agent';
      aiResponse = `Of course! Let me connect you directly to our senior licensed underwriting specialist who can guide you through every line item. Transferring your line right now... please stay on hold.`;
      isCallOver = true;
    } else if (textLower.includes('not interested') || textLower.includes('sold') || textLower.includes('cancel') || textLower.includes('switched') || textLower.includes('no thanks')) {
      intent = 'opt_out';
      sentiment = 'Negative';
      outcome = 'Not Renewing / Opt-out';
      aiResponse = `Understood, ${lead.name}. I will update your Frappe account record so you won't receive further renewal reminders for this policy. If you ever need coverage in the future, we'll be here. Thank you for your time.`;
      isCallOver = true;
    } else if (textLower.includes('which document') || textLower.includes('what document') || textLower.includes('whatsapp') || textLower.includes('upload')) {
      intent = 'claims_doc_query';
      sentiment = 'Positive';
      outcome = 'Claim Link Dispatched';
      aiResponse = `We just need a clear photo of the original hospital discharge summary and detailed indoor case papers. I have just texted a secure 1-click camera upload link to ${lead.phone}. You can snap the photo directly without downloading any app!`;
    } else {
      // General natural conversational continuity
      aiResponse = `I hear you, ${lead.name}. To ensure you don't face any lapse in coverage or vehicle inspection delays, our priority is keeping your protection active with zero friction. Can I assist with the renewal or would you prefer our team to email you the complete breakdown?`;
    }

    return {
      aiTurn: {
        speaker: 'ai',
        role: 'agent',
        agentName: persona.agentName,
        text: aiResponse,
        timestamp: new Date().toISOString(),
        audioLengthMs: Math.min(6500, Math.max(2800, aiResponse.length * 50))
      },
      intent,
      sentiment,
      outcome,
      isCallOver
    };
  }

  /**
   * Generate realistic simulated audio waveform bars for UI visualization
   */
  generateWaveformData(length = 32) {
    const bars = [];
    for (let i = 0; i < length; i++) {
      // Dynamic frequency-like distribution
      const height = Math.floor(Math.random() * 75) + 15;
      bars.push(height);
    }
    return bars;
  }

  /**
   * Produce comprehensive post-call analytical summary
   */
  summarizeCall(lead, fullTranscript, finalSentiment, finalOutcome) {
    return {
      leadId: lead.id,
      customerName: lead.name,
      policyNumber: lead.policyNumber,
      insuranceType: lead.policyType,
      durationSeconds: fullTranscript.reduce((acc, t) => acc + (t.audioLengthMs ? Math.round(t.audioLengthMs / 1000) : 4), 0),
      sentiment: finalSentiment || 'Positive',
      outcome: finalOutcome || 'Renewal Follow-Up Completed',
      keyPointsDiscussed: [
        `Verified policyholder identity for ${lead.name}`,
        `Discussed renewal premium ${lead.premiumAmount} for ${lead.policyType}`,
        `Handled policy queries and shared digital action link`
      ],
      frappeSyncPayload: {
        doctype: 'CRM Call Log',
        lead: lead.id,
        status: 'Completed',
        summary: `AI voice follow-up successfully conducted. Outcome: ${finalOutcome}. Customer sentiment: ${finalSentiment}.`,
        duration: 48,
        custom_sentiment: finalSentiment,
        custom_outcome: finalOutcome,
        custom_insurance_policy: lead.policyNumber
      }
    };
  }
}

module.exports = new VoiceAgentEngine();
