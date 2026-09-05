/**
 * Self-verification test for InsureVoice AI core engine
 */
const voiceAgent = require('./voiceAgent');
const callManager = require('./callManager');
const FrappeCRMClient = require('./frappeClient');

async function runTests() {
  console.log('--- TEST 1: Frappe CRM Client Mock Leads ---');
  const client = new FrappeCRMClient();
  const leads = await client.getFollowUpLeads();
  console.log(`Retrieved ${leads.length} follow-up leads from Frappe CRM client.`);
  if (leads.length < 3) throw new Error('Expected at least 3 leads');

  console.log('--- TEST 2: Voice Persona & Greeting Generation ---');
  const lead = leads[0];
  const greeting = voiceAgent.generateOpeningGreeting(lead);
  console.log(`Generated greeting for ${lead.name} (${lead.policyType}):\n"${greeting.text}"`);
  if (!greeting.text.includes(lead.name)) throw new Error('Greeting missing lead name');

  console.log('--- TEST 3: Conversational Turn & Intent Processing ---');
  // Simulate customer agreeing to renewal
  const turn1 = voiceAgent.processTurn(lead, 'Yes, please send me the payment link.');
  console.log(`Intent: ${turn1.intent} | Sentiment: ${turn1.sentiment} | Outcome: ${turn1.outcome}`);
  console.log(`AI Response:\n"${turn1.aiTurn.text}"`);
  if (turn1.intent !== 'confirm_renewal') throw new Error('Intent should be confirm_renewal');

  // Simulate price objection
  const turn2 = voiceAgent.processTurn(lead, 'Why did the premium increase this year?');
  console.log(`Intent: ${turn2.intent} | Sentiment: ${turn2.sentiment} | Outcome: ${turn2.outcome}`);
  if (turn2.intent !== 'price_objection') throw new Error('Intent should be price_objection');

  // Simulate driving / reschedule
  const turn3 = voiceAgent.processTurn(lead, 'I am driving right now, can you call me back tomorrow?');
  console.log(`Intent: ${turn3.intent} | Outcome: ${turn3.outcome}`);
  if (turn3.intent !== 'request_reschedule') throw new Error('Intent should be request_reschedule');

  console.log('--- TEST 4: Call Session & Automatic Frappe Sync ---');
  const session = await callManager.startCallSession(lead, 'policy_renewal');
  console.log(`Started call session: ${session.callRecord.id}`);

  const turnResult = await callManager.submitCustomerTurn(session.callRecord.id, 'Sounds great, text me the link.');
  console.log(`Call Status: ${turnResult.call.status} | Frappe Sync Status: ${turnResult.call.frappeSyncStatus}`);
  if (turnResult.call.status !== 'completed') throw new Error('Call should be completed');
  if (turnResult.call.frappeSyncStatus !== 'Synced') throw new Error('Call should be synced to Frappe CRM');

  console.log('--- TEST 5: Metrics Calculation ---');
  const metrics = callManager.getMetrics();
  console.log('Live Metrics:', JSON.stringify(metrics, null, 2));

  console.log('\n=========================================');
  console.log('✅ ALL ENGINE VERIFICATION TESTS PASSED!');
  console.log('=========================================');
}

runTests().catch(err => {
  console.error('❌ Verification failed:', err);
  process.exit(1);
});
