/**
 * InsureVoice AI - Frontend Application Logic
 */

let currentActiveCallId = null;
let currentLeadData = null;
let allLeads = [];
let allCalls = [];
let searchTimeout = null;

// Initialization
document.addEventListener('DOMContentLoaded', async () => {
  await loadMetrics();
  await loadCalls();
  await loadLeads();
  await loadCampaigns();
});

// Tab Navigation
function switchTab(tabId) {
  const tabs = ['dashboard', 'leads', 'campaigns', 'frappe'];
  tabs.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const btn = document.getElementById(`tab-btn-${t}`);
    if (el) el.classList.toggle('hidden', t !== tabId);
    if (btn) {
      if (t === tabId) {
        btn.classList.add('active-tab', 'border-blue-500', 'text-blue-400');
        btn.classList.remove('border-transparent', 'text-slate-400');
      } else {
        btn.classList.remove('active-tab', 'border-blue-500', 'text-blue-400');
        btn.classList.add('border-transparent', 'text-slate-400');
      }
    }
  });
}

// -------------------------------------------------------------
// 1. DATA LOADERS (METRICS & CALLS)
// -------------------------------------------------------------

async function loadMetrics() {
  try {
    const res = await fetch('/api/metrics');
    if (!res.ok) return;
    const data = await res.json();
    document.getElementById('metric-total-calls').innerText = data.totalCalls;
    document.getElementById('metric-conversion-rate').innerText = data.conversionRate;
    document.getElementById('metric-avg-duration').innerText = `${data.avgDurationSeconds}s`;
    document.getElementById('metric-sync-health').innerText = data.frappeSyncHealth;
  } catch (err) {
    console.error('Failed to load metrics:', err);
  }
}

async function loadCalls() {
  try {
    const searchVal = document.getElementById('calls-search-input')?.value || '';
    const sentimentVal = document.getElementById('sentiment-filter')?.value || '';
    const query = new URLSearchParams({ search: searchVal, sentiment: sentimentVal });

    const res = await fetch(`/api/calls?${query.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    allCalls = data.calls || [];

    renderCallsTable(allCalls);
  } catch (err) {
    console.error('Failed to load calls:', err);
  }
}

function renderCallsTable(calls) {
  const tbody = document.getElementById('calls-table-body');
  if (!tbody) return;

  if (calls.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="py-8 text-center text-slate-500">No calls matching your criteria.</td></tr>`;
    return;
  }

  tbody.innerHTML = calls.map(c => {
    let sentimentBadge = 'bg-slate-800 text-slate-400 border-slate-700';
    if (c.sentiment === 'Positive') sentimentBadge = 'bg-emerald-950/50 text-emerald-400 border-emerald-500/30';
    if (c.sentiment === 'Hesitant') sentimentBadge = 'bg-amber-950/50 text-amber-400 border-amber-500/30';
    if (c.sentiment === 'Negative') sentimentBadge = 'bg-rose-950/50 text-rose-400 border-rose-500/30';

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3.5 px-6">
          <div class="font-bold text-white">${escapeHtml(c.customerName)}</div>
          <div class="text-[11px] text-slate-400">${escapeHtml(c.phone)}</div>
        </td>
        <td class="py-3.5 px-6">
          <div class="text-slate-200 font-medium">${escapeHtml(c.insuranceType)}</div>
          <div class="text-[11px] font-mono text-cyan-400">${escapeHtml(c.policyNumber)}</div>
        </td>
        <td class="py-3.5 px-6">
          <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-200 border border-slate-700">
            ${escapeHtml(c.outcome)}
          </span>
        </td>
        <td class="py-3.5 px-6">
          <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${sentimentBadge}">
            ${escapeHtml(c.sentiment)}
          </span>
        </td>
        <td class="py-3.5 px-6 font-mono text-slate-300">
          ${c.duration}s
        </td>
        <td class="py-3.5 px-6">
          <div class="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
            <svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
            <span>Frappe CRM</span>
          </div>
          <div class="text-[10px] font-mono text-slate-500">${c.frappeDocId || 'DocType: CRM Call Log'}</div>
        </td>
        <td class="py-3.5 px-6 text-right space-x-2">
          <button onclick="viewCallDetail('${c.id}')" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-cyan-300 rounded text-xs font-semibold border border-slate-700 transition">
            Transcript
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function debounceSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(loadCalls, 300);
}

// -------------------------------------------------------------
// 2. FRAPPE LEADS QUEUE
// -------------------------------------------------------------

async function loadLeads() {
  try {
    const res = await fetch('/api/leads');
    if (!res.ok) return;
    const data = await res.json();
    allLeads = data.leads || [];

    const grid = document.getElementById('leads-grid');
    const select = document.getElementById('sim-lead-select');

    if (select) {
      select.innerHTML = allLeads.map(l => `
        <option value="${l.id}">${escapeHtml(l.name)} (${escapeHtml(l.policyType)})</option>
      `).join('');
    }

    if (!grid) return;
    grid.innerHTML = allLeads.map(lead => `
      <div class="bg-[#131E32] border border-slate-800 rounded-2xl p-5 space-y-4 hover:border-slate-700 transition flex flex-col justify-between">
        <div class="space-y-2">
          <div class="flex items-start justify-between">
            <div>
              <h3 class="font-bold text-base text-white">${escapeHtml(lead.name)}</h3>
              <div class="text-xs text-slate-400 font-mono">${escapeHtml(lead.phone)}</div>
            </div>
            <span class="px-2 py-0.5 text-[10px] uppercase font-bold tracking-wider rounded bg-blue-500/10 text-cyan-400 border border-cyan-500/30">
              ${escapeHtml(lead.status)}
            </span>
          </div>
          
          <div class="p-3 bg-slate-900/60 rounded-xl space-y-1 text-xs text-slate-300">
            <div class="flex justify-between"><span class="text-slate-500">Policy:</span> <span class="font-semibold text-white">${escapeHtml(lead.policyType)}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Policy #:</span> <span class="font-mono text-cyan-300">${escapeHtml(lead.policyNumber)}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Premium:</span> <span class="font-bold text-emerald-400">${escapeHtml(lead.premiumAmount)}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Expiry Date:</span> <span class="text-amber-400 font-medium">${escapeHtml(lead.expiryDate)} (${lead.daysUntilExpiry || 7} days left)</span></div>
          </div>
        </div>

        <div class="pt-2 flex items-center justify-between border-t border-slate-800">
          <span class="text-[11px] text-slate-500">Frappe CRM Lead</span>
          <button onclick="launchDirectCall('${lead.id}')" class="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg transition flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" /></svg>
            Dial AI Call
          </button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load leads:', err);
  }
}

async function refreshLeads() {
  await loadLeads();
  alert('Successfully synced with Frappe CRM leads queue.');
}

// -------------------------------------------------------------
// 3. CAMPAIGNS
// -------------------------------------------------------------

async function loadCampaigns() {
  try {
    const res = await fetch('/api/campaigns');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('campaigns-list');
    if (!container) return;

    container.innerHTML = (data.campaigns || []).map(camp => `
      <div class="bg-[#131E32] border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition flex flex-col justify-between">
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">${escapeHtml(camp.status)}</span>
            <span class="text-xs text-slate-400 font-mono">${escapeHtml(camp.voiceModel)}</span>
          </div>
          <h3 class="font-bold text-lg text-white">${escapeHtml(camp.name)}</h3>
          
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-slate-900/80 p-2.5 rounded-lg">
              <div class="text-slate-500">Pending Leads</div>
              <div class="text-lg font-bold text-amber-400">${camp.pendingFollowUps}</div>
            </div>
            <div class="bg-slate-900/80 p-2.5 rounded-lg">
              <div class="text-slate-500">Conversion</div>
              <div class="text-lg font-bold text-emerald-400">${camp.conversionRate}</div>
            </div>
          </div>

          <div class="text-xs text-slate-400 space-y-1">
            <div><strong>Schedule:</strong> ${escapeHtml(camp.schedule)}</div>
            <div class="font-mono text-[11px] text-cyan-400/80">${escapeHtml(camp.frappeFilter)}</div>
          </div>
        </div>

        <div class="pt-3 border-t border-slate-800">
          <button onclick="runCampaign('${camp.id}')" class="w-full py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold uppercase tracking-wider transition">
            Trigger Batch Voice Dispatch
          </button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load campaigns:', err);
  }
}

async function runCampaign(campId) {
  try {
    const res = await fetch(`/api/campaigns/${campId}/run`, { method: 'POST' });
    const data = await res.json();
    alert(data.message || 'Campaign calls triggered');
    await loadMetrics();
    await loadCalls();
    await loadCampaigns();
  } catch (e) {
    alert('Error triggering campaign');
  }
}

// -------------------------------------------------------------
// 4. LIVE INTERACTIVE AI VOICE CALL SIMULATOR
// -------------------------------------------------------------

function openCallSimulatorModal() {
  document.getElementById('call-simulator-modal').classList.remove('hidden');
  onSimulatorLeadChange();
}

function closeCallSimulatorModal() {
  document.getElementById('call-simulator-modal').classList.add('hidden');
}

function onSimulatorLeadChange() {
  const selId = document.getElementById('sim-lead-select').value;
  currentLeadData = allLeads.find(l => l.id === selId) || allLeads[0];
}

function launchDirectCall(leadId) {
  openCallSimulatorModal();
  document.getElementById('sim-lead-select').value = leadId;
  onSimulatorLeadChange();
  startSimulatedCall();
}

async function startSimulatedCall() {
  if (!currentLeadData) onSimulatorLeadChange();
  const btnStart = document.getElementById('btn-start-call');
  const btnHangup = document.getElementById('btn-hangup-call');
  const inputPanel = document.getElementById('sim-input-panel');
  const dialogueStream = document.getElementById('sim-dialogue-stream');
  const statusDot = document.getElementById('sim-status-dot');
  const statusLabel = document.getElementById('sim-status-label');

  btnStart.classList.add('hidden');
  btnHangup.classList.remove('hidden');
  statusDot.className = 'w-3 h-3 rounded-full bg-emerald-400 animate-pulse';
  statusLabel.innerText = `Connected with ${currentLeadData.name} (${currentLeadData.phone})`;
  statusLabel.className = 'text-xs font-semibold text-emerald-400';

  dialogueStream.innerHTML = `
    <div class="text-center text-xs text-slate-500 py-3 flex items-center justify-center gap-2">
      <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
      Call Connected. Sarah (Apex AI Specialist) is speaking...
    </div>
  `;

  // Start waveform animation
  animateWaveform(true);

  // Trigger initiate API
  const res = await fetch('/api/calls/initiate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead: currentLeadData, campaignType: currentLeadData.campaignType || 'policy_renewal' })
  });

  const data = await res.json();
  currentActiveCallId = data.callRecord.id;

  // Render initial greeting
  setTimeout(() => {
    animateWaveform(false);
    renderDialogueTurn('ai', data.initialGreeting.text, 'Sarah (Apex AI)');
    inputPanel.classList.remove('opacity-50', 'pointer-events-none');
  }, 1200);
}

function renderDialogueTurn(speaker, text, label) {
  const stream = document.getElementById('sim-dialogue-stream');
  const isAi = speaker === 'ai';

  const div = document.createElement('div');
  div.className = `flex ${isAi ? 'justify-start' : 'justify-end'} animate-fade-in`;
  div.innerHTML = `
    <div class="max-w-[82%] rounded-2xl p-3.5 text-xs shadow-sm ${
      isAi 
        ? 'bg-[#162238] border border-blue-500/20 text-slate-100 rounded-tl-sm' 
        : 'bg-blue-600 text-white rounded-tr-sm'
    }">
      <div class="text-[10px] font-bold ${isAi ? 'text-cyan-400' : 'text-blue-200'} mb-1 flex items-center gap-1.5">
        ${isAi ? '🎙️ ' + label : '👤 ' + label}
      </div>
      <p class="leading-relaxed">${escapeHtml(text)}</p>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
}

async function sendQuickCustomerTurn(text) {
  if (!currentActiveCallId) return;
  await processCustomerInput(text);
}

async function handleCustomCustomerTurn(e) {
  e.preventDefault();
  const input = document.getElementById('sim-custom-speech');
  const text = input.value.trim();
  if (!text || !currentActiveCallId) return;
  input.value = '';
  await processCustomerInput(text);
}

async function processCustomerInput(customerSpeech) {
  const inputPanel = document.getElementById('sim-input-panel');
  inputPanel.classList.add('opacity-50', 'pointer-events-none');

  // Render Customer turn
  renderDialogueTurn('customer', customerSpeech, currentLeadData.name);

  // Show waveform
  animateWaveform(true);

  // Send turn to backend
  const res = await fetch(`/api/calls/${currentActiveCallId}/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customerSpeech })
  });

  const data = await res.json();

  setTimeout(() => {
    animateWaveform(false);
    renderDialogueTurn('ai', data.aiTurn.text, data.aiTurn.agentName || 'Sarah (Apex AI)');

    if (data.isCallOver) {
      const stream = document.getElementById('sim-dialogue-stream');
      const note = document.createElement('div');
      note.className = 'text-center text-xs p-3 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 font-semibold my-2';
      note.innerHTML = `
        🎉 Call Successfully Concluded! Outcome: <strong>${data.outcome}</strong>.<br/>
        Automatically synced into Frappe CRM (<code class="font-mono text-cyan-300">CRM Call Log</code>).
      `;
      stream.appendChild(note);
      stream.scrollTop = stream.scrollHeight;

      // End call UI
      document.getElementById('btn-start-call').classList.remove('hidden');
      document.getElementById('btn-hangup-call').classList.add('hidden');
      document.getElementById('sim-status-label').innerText = 'Call Ended & Synced with Frappe CRM';
      document.getElementById('sim-status-dot').className = 'w-3 h-3 rounded-full bg-slate-600';

      loadMetrics();
      loadCalls();
    } else {
      inputPanel.classList.remove('opacity-50', 'pointer-events-none');
    }
  }, 1000);
}

function hangupSimulatedCall() {
  document.getElementById('btn-start-call').classList.remove('hidden');
  document.getElementById('btn-hangup-call').classList.add('hidden');
  document.getElementById('sim-input-panel').classList.add('opacity-50', 'pointer-events-none');
  document.getElementById('sim-status-label').innerText = 'Call Terminated by User';
  document.getElementById('sim-status-dot').className = 'w-3 h-3 rounded-full bg-slate-600';
  animateWaveform(false);
}

function animateWaveform(isActive) {
  const container = document.getElementById('sim-waveform-bars');
  if (!container) return;
  const bars = container.children;
  container.style.opacity = isActive ? '1' : '0.4';

  for (let i = 0; i < bars.length; i++) {
    if (isActive) {
      bars[i].style.height = `${Math.floor(Math.random() * 26) + 6}px`;
    } else {
      bars[i].style.height = '4px';
    }
  }
}

// -------------------------------------------------------------
// 5. CALL DETAIL & TRANSCRIPT MODAL
// -------------------------------------------------------------

async function viewCallDetail(callId) {
  try {
    const res = await fetch(`/api/calls/${callId}`);
    if (!res.ok) return;
    const data = await res.json();
    const call = data.call;

    document.getElementById('modal-detail-customer').innerText = `${call.customerName} - ${call.insuranceType}`;
    document.getElementById('modal-detail-sub').innerText = `Phone: ${call.phone} | Policy #${call.policyNumber}`;
    document.getElementById('modal-detail-summary').innerText = call.summary || 'Summary unavailable.';
    document.getElementById('modal-detail-outcome').innerText = call.outcome;
    document.getElementById('modal-detail-sentiment').innerText = call.sentiment;
    document.getElementById('modal-detail-frappedoc').innerText = call.frappeDocId || 'CALL-LOG-FRAPPE';

    const transcriptBox = document.getElementById('modal-detail-transcript');
    transcriptBox.innerHTML = (call.transcript || []).map(t => `
      <div class="p-2.5 rounded-lg ${t.speaker === 'ai' ? 'bg-slate-900 border border-slate-800' : 'bg-blue-950/40 border border-blue-800/40'}">
        <div class="flex justify-between text-[10px] text-slate-400 mb-1">
          <span class="font-bold ${t.speaker === 'ai' ? 'text-cyan-400' : 'text-blue-300'}">
            ${t.speaker === 'ai' ? '🤖 InsureVoice AI' : '👤 ' + call.customerName}
          </span>
          <span>${t.timestamp || ''}</span>
        </div>
        <p class="text-slate-200">${escapeHtml(t.text)}</p>
      </div>
    `).join('');

    const payloadBox = document.getElementById('modal-detail-payload');
    payloadBox.innerText = JSON.stringify({
      doctype: "CRM Call Log",
      lead: call.leadId,
      customer_name: call.customerName,
      policy_no: call.policyNumber,
      call_type: "Outbound",
      duration: call.duration,
      status: "Completed",
      custom_outcome: call.outcome,
      custom_sentiment: call.sentiment,
      summary: call.summary,
      synced_at: new Date().toISOString()
    }, null, 2);

    document.getElementById('call-detail-modal').classList.remove('hidden');
  } catch (e) {
    console.error(e);
  }
}

function closeCallDetailModal() {
  document.getElementById('call-detail-modal').classList.add('hidden');
}

// -------------------------------------------------------------
// 6. FRAPPE SETTINGS & UTILS
// -------------------------------------------------------------

async function handleFrappeConnect(e) {
  e.preventDefault();
  const feedback = document.getElementById('frappe-test-feedback');
  const btn = document.getElementById('btn-test-frappe');

  btn.disabled = true;
  feedback.innerText = 'Verifying connection to Frappe CRM...';
  feedback.className = 'text-xs text-cyan-400 font-medium';

  const baseUrl = document.getElementById('cfg-frappe-url').value;
  const apiKey = document.getElementById('cfg-frappe-key').value;
  const apiSecret = document.getElementById('cfg-frappe-secret').value;

  try {
    const res = await fetch('/api/frappe/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ baseUrl, apiKey, apiSecret })
    });

    const data = await res.json();
    if (data.success) {
      feedback.innerText = '✅ ' + data.message;
      feedback.className = 'text-xs text-emerald-400 font-medium';
      document.getElementById('frappe-status-text').innerText = 'Connected (Live)';
    } else {
      feedback.innerText = 'ℹ️ Sandbox Mode: ' + (data.message || 'Credentials validated.');
      feedback.className = 'text-xs text-amber-400 font-medium';
    }
  } catch (err) {
    feedback.innerText = 'Connection test failed: ' + err.message;
    feedback.className = 'text-xs text-rose-400 font-medium';
  } finally {
    btn.disabled = false;
  }
}

function copyServerScript() {
  const code = document.getElementById('server-script-code').innerText;
  navigator.clipboard.writeText(code);
  alert('Frappe Server Script copied to clipboard!');
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
