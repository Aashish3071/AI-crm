// InsureCRM Enterprise Platform
// Corporate Operations Engine: Confirmed Stages, Triage Tasks, Polymorphic Notes & Contextual UX

let currentView = 'dashboard';
let leadViewMode = 'list'; // 'list' or 'kanban'
let cachedLeads = [];
let cachedNotes = [];
let cachedTasks = [];
let activeQuickFilter = null;
let leadPage = 1;
let leadPageMeta = {page: 1, totalPages: 1, total: 0};
let savedLeadFilters = [];
let activeTaskTab = 'all';
let editingLeadId = null;

const STAGES = ["New", "Contacted", "Risk / Underwriting", "Quotation Sent", "Won", "Lost"];

// The broker roster comes from the users table, so adding or renaming a team member
// flows through every owner dropdown instead of needing a code change.
let brokerRoster = [];

async function loadBrokerRoster() {
    try {
        const users = await apiJson('/api/users?activeOnly=true');
        brokerRoster = users.map(u => u.name).filter(Boolean);
    } catch (e) {
        brokerRoster = [];
    }
    document.querySelectorAll('[data-roster]').forEach(select => {
        const keepAll = select.getAttribute('data-roster') === 'with-all';
        const current = select.value;
        select.innerHTML = (keepAll ? '<option value="">All Brokers</option>' : '')
            + brokerRoster.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
        if (current && brokerRoster.includes(current)) select.value = current;
    });
}

function ownerFieldOptions() {
    return brokerRoster.length ? `select:${brokerRoster.join('|')}` : 'text';
}

function formatDaysLeft(days) {
    if (days === null || days === undefined) return 'No renewal date';
    if (days < 0) return `${Math.abs(days)}d overdue`;
    if (days === 0) return 'Expires today';
    return `${days}d left`;
}

let applicationStarted = false;
let signedInUser = null;

document.addEventListener('DOMContentLoaded', async () => {
    initNav();
    initFilters();
    if (!await ensureAuthenticated()) return;
    await startApplication();
});

async function startApplication() {
    if (applicationStarted) return;
    applicationStarted = true;
    await loadBrokerRoster();
    switchView('dashboard');
    refreshNotificationBadge();
    refreshDemoCleanupLink();
    // Escalations run on the server every few minutes; keep the badge in step.
    setInterval(refreshNotificationBadge, 60000);
    if (localStorage.getItem('insurecrm_onboarding_dismissed') !== 'true') openOnboardingGuide();
}

function setSignedInUser(user) {
    signedInUser = user;
    if (!user) return;
    const initials = String(user.name || 'U').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase();
    const set = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
    set('current-user-initials', initials); set('current-user-name', user.name); set('current-user-role', user.role);
}

async function ensureAuthenticated() {
    const status = await fetch('/api/auth/status').then(r => r.json()).catch(() => ({authenticationRequired:true}));
    if (!status.authenticationRequired) return true;
    if (status.setupRequired) { showAuthGate(true); return false; }
    const me = await fetch('/api/auth/me').then(async r => r.ok ? r.json() : null).catch(() => null);
    if (!me?.user) { showAuthGate(false); return false; }
    setSignedInUser(me.user);
    return true;
}

function showAuthGate(setup) {
    const gate = document.getElementById('auth-gate');
    gate.classList.remove('hidden');
    document.getElementById('login-form').classList.toggle('hidden', setup);
    document.getElementById('bootstrap-form').classList.toggle('hidden', !setup);
    document.getElementById('auth-title').textContent = setup ? 'Set up InsureCRM securely' : 'Sign in to InsureCRM';
    document.getElementById('auth-subtitle').textContent = setup ? 'Create the first company and administrator.' : 'Use your company account to continue.';
    setTimeout(() => gate.querySelector('input:not([type=hidden])')?.focus(), 50);
}

async function authSubmit(url, form, errorId) {
    const error = document.getElementById(errorId); error.classList.add('hidden');
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(new FormData(form).entries()))});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { error.textContent = data.detail || 'Could not continue'; error.classList.remove('hidden'); return; }
    setSignedInUser(data.user);
    document.getElementById('auth-gate').classList.add('hidden');
    await startApplication();
}

function submitLogin(event) { event.preventDefault(); return authSubmit('/api/auth/login', event.currentTarget, 'login-error'); }
function submitBootstrap(event) { event.preventDefault(); return authSubmit('/api/auth/bootstrap', event.currentTarget, 'bootstrap-error'); }

async function logout() {
    try { await apiJson('/api/auth/logout', {method:'POST'}); } catch (_) {}
    location.reload();
}

function confirmLogout() {
    if (confirm('Sign out of InsureCRM?')) logout();
}

function switchSettingsTo(tab) {
    openSettingsModal();
    switchSettingTab(tab);
}

async function refreshNotificationBadge() {
    try {
        const unread = await apiJson('/api/notifications?unreadOnly=true');
        const badge = document.getElementById('notification-count');
        const bell = document.getElementById('notification-bell');
        if (!badge || !bell) return;
        badge.textContent = unread.length > 9 ? '9+' : String(unread.length);
        badge.classList.toggle('hidden', unread.length === 0);
        bell.classList.toggle('has-unread', unread.length > 0);
        bell.title = unread.length ? `${unread.length} notification${unread.length === 1 ? '' : 's'} needing attention` : 'Notifications';
    } catch (e) { /* the badge is non-critical; never block the app on it */ }
}

// ── Guided walkthrough ───────────────────────────────────────────────
// One step at a time, following a policy's real path: enquiry → underwriting →
// quotation → issued policy → renewal. Each step names the screen it happens on.
const ONBOARDING_STEPS = [
    {
        view: 'leads', screen: 'Leads & Accounts', heading: 'Capture the enquiry',
        summary: 'Every enquiry starts here — typed in directly, or imported in bulk from your existing spreadsheet.',
        points: [
            'New Lead records the client, organization, policy category and renewal date',
            'Import from spreadsheet brings your whole book across, skipping or updating duplicates',
            'The organization and contact records are created for you automatically'
        ],
        note: 'A lead with no renewal date stays out of the renewal radar until you set one.',
        hint: 'Start with New Lead in the top right, or Import to bring across an existing book.'
    },
    {
        view: 'leads', screen: 'Leads & Accounts', heading: 'Move the stage, schedule the next action',
        summary: 'Click any stage pill to advance the lead. The CRM will not let you leave without deciding what happens next.',
        points: [
            'Six stages: New → Contacted → Risk / Underwriting → Quotation Sent → Won or Lost',
            'Every transition needs a next action and a due date — this is what stops leads going quiet',
            'Marking a lead Lost requires a reason, so you can review why business is being lost'
        ],
        note: 'Each transition writes a timestamped memo to the account timeline and raises the matching task.',
        hint: 'Try it: click a coloured stage pill on any row in the leads table.'
    },
    {
        view: 'tasks', screen: 'Action Tasks', heading: 'Work the daily queue',
        summary: 'Every scheduled next action lands here, sorted by urgency rather than by account.',
        points: [
            'Triaged into Overdue, Due Today, Upcoming and Completed',
            'Tick a task off and the lead’s next action is marked done at the same time',
            'Click any task to jump straight into that client’s full record'
        ],
        note: 'Overdue renewal actions also raise an entry in the Notification inbox.',
        hint: 'This is the screen to open first thing each morning.'
    },
    {
        view: 'leads', screen: 'Lead 360° drawer', heading: 'Work the account in one place',
        summary: 'Click a client’s name to open their full record without leaving the list.',
        points: [
            'Pinned next action, policy schedule, premium and renewal countdown',
            'Upload KYC, RC books and surveyor reports — each re-upload is kept as a new version',
            'Full chronological history of notes, stage changes and communications'
        ],
        note: 'Consent is recorded per channel here; an opted-out client is blocked from outbound WhatsApp or email.',
        hint: 'Click any client name in the leads table to open their drawer.'
    },
    {
        view: 'policies', screen: 'Policies', heading: 'Convert and issue the policy',
        summary: 'When business is won, convert the lead into a customer with a real policy against it.',
        points: [
            'Conversion creates the customer, the policy and the closed deal together',
            'Issuance is gated on your document checklist and the policy number',
            'Premium, GST and total payable are calculated on the policy record'
        ],
        note: 'The original lead stays linked, so you keep the full history from first enquiry to issued policy.',
        hint: 'Convert from the lead drawer, then complete issuance on the Policies screen.'
    },
    {
        view: 'renewals', screen: 'Renewals & Quotations', heading: 'Protect the renewal',
        summary: 'Renewals are generated ahead of expiry so no policy lapses unnoticed.',
        points: [
            'Generate 60-day renewals sweeps every policy approaching expiry',
            'Log competing insurer quotations side by side and select the winner',
            'Completing a renewal issues the new policy and retires the old one, chained together'
        ],
        note: 'Retention rate and premium retained are tracked on the renewal report.',
        hint: 'The Dashboard flags anything expiring within 15 days.'
    }
];

let onboardingIndex = 0;

function openOnboardingGuide() {
    const checkbox = document.getElementById('onboarding-dismiss');
    if (checkbox) checkbox.checked = localStorage.getItem('insurecrm_onboarding_dismissed') === 'true';
    onboardingIndex = 0;
    renderOnboardingStep();
    document.getElementById('onboarding-modal')?.classList.remove('hidden');
}

function closeOnboardingGuide() {
    if (document.getElementById('onboarding-dismiss')?.checked) localStorage.setItem('insurecrm_onboarding_dismissed', 'true');
    document.getElementById('onboarding-modal')?.classList.add('hidden');
}

function onboardingStep(direction) {
    const target = onboardingIndex + direction;
    if (target < 0) return;
    if (target >= ONBOARDING_STEPS.length) {
        goFromGuide(ONBOARDING_STEPS[ONBOARDING_STEPS.length - 1].view);
        return;
    }
    onboardingIndex = target;
    renderOnboardingStep();
}

function goToOnboardingStep(index) {
    onboardingIndex = Math.max(0, Math.min(index, ONBOARDING_STEPS.length - 1));
    renderOnboardingStep();
}

function renderOnboardingStep() {
    const step = ONBOARDING_STEPS[onboardingIndex];
    const isLast = onboardingIndex === ONBOARDING_STEPS.length - 1;
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };

    set('onboarding-index', `Step ${onboardingIndex + 1} of ${ONBOARDING_STEPS.length}`);
    set('onboarding-heading', step.heading);
    set('onboarding-summary', step.summary);
    set('onboarding-screen', step.screen);
    set('onboarding-note', step.note);
    set('onboarding-hint', step.hint);

    const points = document.getElementById('onboarding-points');
    if (points) points.innerHTML = step.points.map(p => `<li>${esc(p)}</li>`).join('');

    const progress = document.getElementById('onboarding-progress');
    if (progress) {
        progress.innerHTML = ONBOARDING_STEPS.map((s, i) => `
            <button type="button" class="onboarding-tick ${i === onboardingIndex ? 'is-current' : ''} ${i < onboardingIndex ? 'is-done' : ''}"
                onclick="goToOnboardingStep(${i})" aria-label="Step ${i + 1}: ${esc(s.heading)}" title="${esc(s.heading)}">
                <span class="onboarding-tick-dot">${i + 1}</span>
                <span class="onboarding-tick-label">${esc(s.screen)}</span>
            </button>`).join('');
    }

    const back = document.getElementById('onboarding-back');
    if (back) back.disabled = onboardingIndex === 0;
    const next = document.getElementById('onboarding-next');
    if (next) next.textContent = isLast ? 'Finish & open Renewals' : 'Next step';
    const openBtn = document.getElementById('onboarding-open-btn');
    if (openBtn) openBtn.onclick = () => goFromGuide(step.view);
}

function goFromGuide(viewName) {
    closeOnboardingGuide();
    switchView(viewName);
}

function initNav() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        const visibleLabel = btn.querySelector('span')?.textContent?.trim();
        if (visibleLabel && !btn.hasAttribute('aria-label')) btn.setAttribute('aria-label', visibleLabel);
        if (visibleLabel && !btn.hasAttribute('title')) btn.setAttribute('title', visibleLabel);
        btn.addEventListener('click', () => {
            const v = btn.getAttribute('data-view');
            if (v) switchView(v);
        });
    });
}

function initFilters() {
    const debounced = debounce(loadLeads, 200);
    document.getElementById('leads-search')?.addEventListener('input', () => { leadPage = 1; debounced(); });
    document.getElementById('leads-status-filter')?.addEventListener('change', () => { activeQuickFilter = null; leadPage = 1; loadLeads(); });
    document.getElementById('leads-owner-filter')?.addEventListener('change', () => { activeQuickFilter = null; leadPage = 1; loadLeads(); });
    document.getElementById('deals-search')?.addEventListener('input', debounce(loadDeals, 200));

    document.getElementById('select-all-leads')?.addEventListener('change', (e) => {
        const checked = e.target.checked;
        document.querySelectorAll('.lead-row-check').forEach(cb => cb.checked = checked);
        updateLeadSelectionBar();
    });
}

function debounce(fn, ms) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}

let globalSearchTimer = null;
async function runGlobalSearch(value) {
    clearTimeout(globalSearchTimer);
    const input=document.getElementById('global-search'), root=document.getElementById('global-search-results');
    const query=value.trim();
    if(query.length<2){root.classList.add('hidden');input.setAttribute('aria-expanded','false');return;}
    globalSearchTimer=setTimeout(async()=>{
        try{
            const items=await apiJson(`/api/search?q=${encodeURIComponent(query)}`);
            root.innerHTML=items.map((item,index)=>`<button role="option" data-search-index="${index}" onclick="openGlobalResult(decodeURIComponent('${encodeURIComponent(JSON.stringify(item))}'))" class="w-full text-left px-3 py-2 border-b last:border-0 hover:bg-slate-50 focus:bg-slate-50"><span class="text-[10px] uppercase text-slate-400">${esc(item.type)}</span><strong class="block text-xs">${esc(item.title)}</strong><span class="block text-[11px] text-slate-500 truncate">${esc(item.subtitle||'')}</span></button>`).join('')||'<div class="p-4 text-xs text-slate-500">No matching records.</div>';
            root.classList.remove('hidden');input.setAttribute('aria-expanded','true');
        }catch(e){root.innerHTML=`<div class="p-4 text-xs text-rose-700">${esc(e.message)}</div>`;root.classList.remove('hidden');}
    },220);
}

function handleGlobalSearchKeys(event){if(event.key==='Escape'){document.getElementById('global-search-results').classList.add('hidden');event.currentTarget.setAttribute('aria-expanded','false');}}
async function openGlobalResult(serialized){
    const item=JSON.parse(serialized);document.getElementById('global-search-results').classList.add('hidden');document.getElementById('global-search').value='';
    switchView(item.view);
    if(item.type==='Lead') setTimeout(()=>openLeadDrawer(item.id),100);
    if(item.type==='Customer') setTimeout(()=>openCustomer360(item.id),150);
}

// ─── Contextual Action Handler (Only show New Lead on Leads & Account) ───
function handlePrimaryAction() {
    if (currentView === 'leads') {
        openCreateModal();
    } else if (currentView === 'notes') {
        openCreateNoteModal();
    } else if (currentView === 'tasks') {
        openCreateTaskModal();
    }
}

// ─── View Switching ───
function switchView(viewName) {
    document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));
    const panel = document.getElementById(`view-${['policies','renewals'].includes(viewName) ? 'insurance' : viewName}`);
    if (panel) panel.classList.remove('hidden');

    document.querySelectorAll('.nav-btn').forEach(btn => {
        const isCurrent = btn.getAttribute('data-view') === viewName;
        btn.classList.toggle('active-nav', isCurrent);
        btn.classList.toggle('bg-brandNavHover', isCurrent);
        btn.classList.toggle('text-white', isCurrent);
        btn.classList.toggle('text-slate-400', !isCurrent);
    });

    const labels = {
        'dashboard': 'Dashboard',
        'leads': 'Leads & Accounts',
        'deals': 'Pipeline Deals',
        'policies': 'Policies',
        'renewals': 'Renewals',
        'customers': 'Customers',
        'contacts': 'Contacts',
        'organizations': 'Organizations',
        'notes': 'Activity Notes',
        'tasks': 'Action Tasks',
        'notifications': 'Notification Inbox',
        'channels': 'Lead Sources',
        'calendar': 'Calendar'
    };
    const breadcrumbModule = document.getElementById('breadcrumb-module');
    const breadcrumbSeparator = document.getElementById('breadcrumb-module-separator');
    breadcrumbModule.textContent = labels[viewName] || viewName;
    breadcrumbModule.classList.toggle('hidden', viewName === 'dashboard');
    breadcrumbSeparator.classList.toggle('hidden', viewName === 'dashboard');
    document.getElementById('breadcrumb-view-label').textContent = viewName === 'dashboard' ? 'Overview' : (viewName === 'leads' ? (leadViewMode === 'kanban' ? 'Pipeline Stages' : 'All Records') : 'List');

    // Contextual Header Elements
    const headerToggle = document.getElementById('header-view-toggle');
    if (headerToggle) headerToggle.style.display = viewName === 'leads' ? 'inline-flex' : 'none';

    // Primary Contextual Action Button
    const primaryBtn = document.getElementById('primary-action-btn');
    const primaryLabel = document.getElementById('primary-action-label');
    if (primaryBtn && primaryLabel) {
        if (viewName === 'leads') {
            primaryBtn.style.display = 'flex';
            primaryLabel.textContent = 'New Lead';
        } else if (viewName === 'notes') {
            primaryBtn.style.display = 'flex';
            primaryLabel.textContent = 'New Note';
        } else if (viewName === 'tasks') {
            primaryBtn.style.display = 'flex';
            primaryLabel.textContent = 'New Task';
        } else {
            primaryBtn.style.display = 'none';
        }
    }

    currentView = viewName;
    closeDrawer();

    switch (viewName) {
        case 'leads': loadLeads(); break;
        case 'dashboard': loadDashboard(); break;
        case 'deals': loadDeals(); break;
        case 'policies': configureInsuranceWorkspace('policies'); loadInsuranceOperations(); break;
        case 'renewals': configureInsuranceWorkspace('renewals'); loadInsuranceOperations(); break;
        case 'customers': loadCustomers(); break;
        case 'contacts': loadContacts(); break;
        case 'organizations': loadOrganizations(); break;
        case 'notes': loadNotes(); break;
        case 'tasks': loadTasks(); break;
        case 'notifications': loadNotifications(); break;
        case 'channels': loadChannels(); break;
        case 'calendar': loadCalendar(); break;
    }
}

function refreshCurrentView() {
    switchView(currentView);
}

function configureInsuranceWorkspace(mode){
    const policies=mode==='policies';
    document.getElementById('insurance-workspace-title').textContent=policies?'Policies':'Renewals & Quotations';
    document.getElementById('policy-register-section').classList.toggle('hidden',!policies);
    document.getElementById('communication-section').classList.toggle('hidden',!policies);
    document.getElementById('renewal-pipeline-section').classList.toggle('hidden',policies);
    document.getElementById('quotation-section').classList.toggle('hidden',policies);
    document.getElementById('generate-renewals-button').classList.toggle('hidden',policies);
    document.getElementById('policy-service-section').classList.toggle('hidden',!policies);
}

// ═══════════════════════════════════════════════════════════════════
// CORE INSURANCE OPERATIONS
// ═══════════════════════════════════════════════════════════════════
let cachedPolicies = [];
let cachedRenewals = [];

async function apiJson(url, options = {}) {
    options.headers = {...(options.headers || {})};
    if ((options.method || 'GET').toUpperCase() !== 'GET') {
        const csrf = document.cookie.split('; ').find(value => value.startsWith('crm_csrf='))?.split('=').slice(1).join('=') || '';
        if (csrf) options.headers['X-CSRF-Token'] = decodeURIComponent(csrf);
    }
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) showAuthGate(false);
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    return data;
}

async function loadInsuranceOperations() {
    try {
        const [policies, renewals, report, communications, quotations, services] = await Promise.all([
            apiJson('/api/policies'), apiJson('/api/renewals'), apiJson('/api/renewals/report'), apiJson('/api/communications'), apiJson('/api/quotations'), apiJson('/api/service-requests')
        ]);
        cachedPolicies = policies;
        cachedRenewals = renewals;
        renderInsuranceKpis(report, policies, communications);
        renderPolicies(policies);
        renderRenewals(renewals);
        renderCommunications(communications);
        renderQuotationComparison(quotations, renewals);
        renderServiceRequests(services);
    } catch (e) {
        showToast(e.message);
    }
}

function renderQuotationComparison(quotes, renewals) {
    const root = document.getElementById('quotation-comparison');
    if (!root) return;
    const lowest = quotes.length ? Math.min(...quotes.map(q=>Number(q.premium||0))) : 0;
    root.innerHTML = quotes.length ? quotes.map(q => {
        const renewal = renewals.find(r => r.id === q.renewalId) || {};
        const selected = renewal.selectedQuotationId === q.id;
        return `<div class="border ${selected ? 'border-emerald-500 ring-1 ring-emerald-200' : 'border-slate-200'} rounded-lg p-3">
            <div class="flex justify-between gap-2"><div><div class="font-semibold">${esc(q.insurer)}</div><div class="text-[11px] text-slate-500">${esc(renewal.customerName || q.renewalId)}</div></div><div class="font-mono font-semibold">₹${Number(q.premium || 0).toLocaleString('en-IN')}</div></div>
            <div class="text-[10px] mt-2 ${Number(q.premium||0)===lowest?'text-emerald-700 font-semibold':'text-slate-500'}">${Number(q.premium||0)===lowest?'Lowest premium':`₹${(Number(q.premium||0)-lowest).toLocaleString('en-IN')} above lowest`}</div>
            <div class="text-[11px] text-slate-600 mt-2">Sum insured: ₹${Number(q.sumInsured || 0).toLocaleString('en-IN')} · Deductible: ₹${Number(q.deductible || 0).toLocaleString('en-IN')}</div>
            <div class="text-[11px] text-slate-500 mt-1">${esc(q.coverageSummary || 'No coverage summary')}</div>
            ${renewal.approvalHistory?.length?`<div class="text-[10px] text-slate-400 mt-2">${renewal.approvalHistory.length} approval event(s) recorded</div>`:''}
            <button onclick="selectQuotation('${q.renewalId}','${q.id}')" class="mt-3 w-full py-1.5 rounded text-xs font-semibold ${selected ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-900 text-white'}">${selected ? 'Selected' : 'Select quotation'}</button>
        </div>`;
    }).join('') : '<div class="text-xs text-slate-400">No quotations recorded yet.</div>';
}

async function selectQuotation(renewalId, quotationId) {
    try { await apiJson(`/api/renewals/${renewalId}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({selectedQuotationId:quotationId, stage:'Quotation Sent'})}); showToast('Quotation selected'); await loadInsuranceOperations(); }
    catch (e) { showToast(e.message); }
}

function renderInsuranceKpis(report, policies, communications) {
    const items = [
        ['Policies', policies.length], ['Open renewals', report.total - report.closed], ['Renewed', report.renewed],
        ['Retention', `${report.retentionRate}%`], ['Messages', communications.length]
    ];
    document.getElementById('insurance-kpis').innerHTML = items.map(([label, value]) => `
        <div class="bg-white border border-slateBorder rounded-lg p-3 shadow-xs"><div class="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">${label}</div><div class="text-xl font-semibold mt-1 num-tabular">${value}</div></div>`).join('');
}

function renderPolicies(items) {
    const body = document.getElementById('policies-table-body');
    body.innerHTML = items.length ? items.map(p => `<tr>
        <td><div class="font-medium">${esc(p.policyNumber || 'Draft policy')}</div><div class="text-[11px] text-slate-500">${esc(p.policyType)}</div></td>
        <td><div>${esc(p.customerName)}</div><div class="text-[11px] text-slate-500">${esc(p.organization)}</div></td>
        <td class="font-mono text-xs">${esc(p.expiryDate || '—')}</td><td><span class="px-2 py-0.5 rounded border border-slate-200 bg-slate-50 text-[11px]">${esc(p.issuanceStatus)}</span></td>
        <td><div class="flex gap-2"><button onclick="editPolicy('${p.id}')" class="text-[11px] font-semibold">Edit</button><button onclick="openCalendarEventForm('Policy','${p.id}')" class="text-[11px] font-semibold">Schedule</button>${p.issuanceStatus !== 'Issued' ? `<button onclick="issuePolicy('${p.id}')" class="text-[11px] font-semibold text-emerald-700">Issue</button>` : ''}</div></td>
    </tr>`).join('') : '<tr><td colspan="5" class="text-center py-10 text-slate-400">No policies yet. Import existing lead policies or create one.</td></tr>';
}

function renderRenewals(items) {
    const body = document.getElementById('renewals-table-body');
    const stages = ['Upcoming', 'Due Soon', 'Contacted', 'Quotation Requested', 'Quotation Sent', 'Negotiation', 'Renewed', 'Lost', 'Lapsed'];
    body.innerHTML = items.length ? items.map(r => `<tr>
        <td><div class="font-medium">${esc(r.customerName)}</div><div class="text-[11px] text-slate-500">${esc(r.policyNumber || 'Policy')}</div></td>
        <td class="font-mono text-xs">${esc(r.expiryDate || '—')}</td><td>${esc(r.assignedTo)}</td>
        <td><div>${esc(r.nextAction)}</div><div class="text-[11px] text-slate-500">${esc(r.nextActionDate || 'No date')}</div></td>
        <td class="font-mono">₹${Number(r.targetPremium || 0).toLocaleString('en-IN')}</td>
        <td><select class="corp-input py-1 text-[11px]" onchange="changeRenewalStage('${r.id}', this.value)">${stages.map(s => `<option ${s === r.stage ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
        <td><div class="flex gap-2"><button onclick="addQuotation('${r.id}')" class="text-[11px] font-semibold text-slate-700 hover:text-black">Add quote</button><button onclick="openCalendarEventForm('Renewal','${r.id}')" class="text-[11px] font-semibold">Schedule</button>${r.selectedQuotationId && r.stage !== 'Renewed' ? `<button onclick="completeRenewal('${r.id}')" class="text-[11px] font-semibold text-emerald-700">Complete</button>` : ''}</div></td>
    </tr>`).join('') : '<tr><td colspan="7" class="text-center py-10 text-slate-400">No renewals generated yet.</td></tr>';
}

function renderCommunications(items) {
    const list = document.getElementById('communications-list');
    list.innerHTML = items.length ? items.map(c => `<div class="p-3 flex items-start justify-between gap-3">
        <div class="min-w-0"><div class="font-medium text-xs">${esc(c.channel)} · ${esc(c.recipient)}</div><div class="text-[11px] text-slate-600 mt-1 truncate">${esc(c.subject || c.content)}</div><div class="text-[10px] text-slate-400 mt-1">${timeAgo(c.createdAt)} · ${esc(c.status)}</div></div>
        ${c.status === 'Queued' ? `<button onclick="sendCommunication('${c.id}')" class="text-[11px] font-semibold">Send</button>` : ''}
    </div>`).join('') : '<div class="p-10 text-center text-xs text-slate-400">No communications recorded.</div>';
}

function renderServiceRequests(items) {
    const root=document.getElementById('policy-service-list'); if(!root)return;
    root.innerHTML=items.length?items.map(item=>`<div class="p-3 flex flex-wrap items-start justify-between gap-3"><div><div class="flex items-center gap-2"><strong class="text-xs">${esc(item.requestType)}</strong><span class="px-1.5 py-0.5 rounded bg-slate-100 text-[10px]">${esc(item.status)}</span></div><p class="text-xs text-slate-600 mt-1">${esc(item.customerName)} · ${esc(item.policyNumber||item.policyId)}</p><p class="text-[11px] text-slate-500 mt-1">${esc(item.description)}</p></div><button onclick="updateServiceRequest('${item.id}','${item.status}')" class="text-[11px] font-semibold">Update</button></div>`).join(''):'<div class="p-8 text-center text-xs text-slate-400">No policy service requests.</div>';
}

function openServiceRequestPrompt(){
    const choices=cachedPolicies.filter(p=>p.customerId).map(p=>`${p.id}::${p.policyNumber||'Draft'} — ${p.customerName}`).join('|');
    if(!choices)return showToast('Create or repair a customer-linked policy first');
    openInsuranceForm('New policy service request', [['policyId','Policy','selectpairs:'+choices,true],['requestType','Request type','select:Endorsement|Claim Assistance|Certificate|Policy Document|Cancellation|Reinstatement|Other',true],['description','Request details','textarea',true],['priority','Priority','select:High|Medium|Low',true],['dueDate','Due date','date',false],['assignedTo','Owner',ownerFieldOptions(),false]], async values=>{
        const policy=cachedPolicies.find(p=>p.id===values.policyId); values.customerId=policy?.customerId||'';
        return apiJson('/api/service-requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
    });
}

function updateServiceRequest(id,current){
    openInsuranceForm('Update service request',[['status','Status','select:Open|In Progress|Waiting on Client|Waiting on Insurer|Completed|Cancelled',true]],values=>apiJson(`/api/service-requests/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)}),{status:current});
}

async function migrateLeadPolicies() {
    try { const data = await apiJson('/api/policies/migrate-leads', { method: 'POST' }); showToast(`${data.createdCount} policies imported`); await loadInsuranceOperations(); }
    catch (e) { showToast(e.message); }
}

async function generateRenewals() {
    try { const data = await apiJson('/api/renewals/generate?days=60', { method: 'POST' }); showToast(`${data.createdCount} renewals generated`); await apiJson('/api/notifications/run-escalations', { method: 'POST' }); await loadInsuranceOperations(); }
    catch (e) { showToast(e.message); }
}

async function changeRenewalStage(id, stage) {
    if (stage === 'Lost' || stage === 'Lapsed') {
        return openInsuranceForm(`Record ${stage.toLowerCase()} renewal`, [['outcomeReason','Outcome reason','textarea',true]], values => apiJson(`/api/renewals/${id}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage,outcomeReason:values.outcomeReason})}));
    }
    try { await apiJson(`/api/renewals/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({stage}) }); showToast('Renewal updated'); await loadInsuranceOperations(); }
    catch (e) { showToast(e.message); await loadInsuranceOperations(); }
}

async function addQuotation(renewalId) {
    openInsuranceForm('Add insurer quotation', [
        ['insurer','Insurer','text',true], ['premium','Quoted premium','number',true], ['sumInsured','Sum insured','number',false],
        ['deductible','Deductible','number',false], ['validityDate','Valid until','date',false], ['coverageSummary','Coverage summary','textarea',false]
    ], async values => {
        values.renewalId = renewalId; values.status = 'Received';
        await apiJson('/api/quotations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(values)});
        await apiJson(`/api/renewals/${renewalId}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({stage:'Quotation Requested'})});
    });
}

async function openNewPolicyPrompt() {
    const customers=await apiJson('/api/customers');
    if(!customers.length){switchView('customers');return showToast('Create or convert a customer before adding a policy');}
    const choices=customers.map(c=>`${c.id}::${c.name}${c.organization?' — '+c.organization:''}`).join('|');
    openInsuranceForm('Create policy', [
        ['customerId','Customer','selectpairs:'+choices,true], ['policyType','Policy type','text',true],
        ['policyNumber','Policy number','text',false], ['insurer','Insurer','text',false], ['premium','Premium','number',false],
        ['sumInsured','Sum insured','number',false], ['startDate','Start date','date',false], ['expiryDate','Expiry date','date',true]
    ], values => {const c=customers.find(x=>x.id===values.customerId);return apiJson('/api/policies', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...values,customerName:c?.name||'',organization:c?.organization||''})})});
}

async function openCommunicationPrompt() {
    openInsuranceForm('Compose communication', [
        ['associatedId','Lead or customer ID','text',true], ['channel','Channel','select:Email|WhatsApp',true],
        ['recipient','Recipient','text',true], ['subject','Subject','text',false], ['content','Message','textarea',true]
    ], values => apiJson('/api/communications', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(values)}));
}

let insuranceFormBackHandler = null;

function setInsuranceFormBack(handler = null, label = 'Back') {
    insuranceFormBackHandler = handler;
    const button = document.getElementById('insurance-form-back');
    if (button) {
        button.textContent = `← ${label}`;
        button.setAttribute('aria-label', label === 'Back' ? 'Go back' : label);
    }
}

function handleInsuranceFormBack() {
    if (insuranceFormBackHandler) insuranceFormBackHandler();
    else closeInsuranceForm();
}

function openInsuranceForm(title, fields, submitter, initial = {}) {
    const modal = document.getElementById('insurance-form-modal');
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = title;
    setInsuranceFormBack(() => closeInsuranceForm(), 'Back');
    form.innerHTML = fields.map(([name,label,type,required]) => {
        const attrs = `name="${name}" ${required ? 'required' : ''} class="corp-input"`;
        let control;
        const value = initial[name] ?? '';
        if (type === 'textarea') control = `<textarea ${attrs} rows="3">${esc(value)}</textarea>`;
        else if (type.startsWith('selectpairs:')) control = `<select ${attrs}>${type.slice(12).split('|').map(pair => {const [v,label]=pair.split('::');return `<option value="${esc(v)}" ${String(value) === v ? 'selected' : ''}>${esc(label||v)}</option>`}).join('')}</select>`;
        else if (type.startsWith('select:')) control = `<select ${attrs}>${type.slice(7).split('|').map(v => `<option value="${v}" ${String(value) === v ? 'selected' : ''}>${v}</option>`).join('')}</select>`;
        else if (type === 'checkbox') control = `<input type="checkbox" name="${name}" ${value ? 'checked' : ''} class="rounded">`;
        else control = `<input type="${type}" ${attrs} value="${esc(value)}">`;
        return `<label class="block text-xs font-medium text-slate-700"><span class="block mb-1">${label}${required ? ' *' : ''}</span>${control}</label>`;
    }).join('') + `<div class="pt-3 border-t border-slateBorder flex justify-end gap-2"><button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button><button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save</button></div>`;
    form.onsubmit = async event => {
        event.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries());
        ['premium','sumInsured','deductible'].forEach(k => { if (values[k] !== undefined) values[k] = Number(values[k] || 0); });
        fields.filter(f => f[2] === 'checkbox').forEach(f => values[f[0]] = form.elements[f[0]].checked);
        try { await submitter(values); closeInsuranceForm(); showToast(`${title} saved`); if(['policies','renewals'].includes(currentView)) await loadInsuranceOperations(); else if(currentView==='customers') await loadCustomers(); else if(currentView==='deals') await loadDeals(); else if(currentView==='contacts') await loadContacts(); else if(currentView==='organizations') await loadOrganizations(); else if(currentView==='notifications') await loadNotifications(); else if(currentView==='leads') await loadLeads(); }
        catch (e) { showToast(e.message); }
    };
    modal.classList.remove('hidden');
}

function closeInsuranceForm() {
    document.getElementById('insurance-form-modal')?.classList.add('hidden');
    insuranceFormBackHandler = null;
}

async function sendCommunication(id) {
    try { await apiJson(`/api/communications/${id}/send`, {method:'POST'}); showToast('Delivery recorded in simulation mode'); await loadInsuranceOperations(); }
    catch (e) { showToast(e.message); }
}

async function convertLeadToPolicy(id) {
    const lead = cachedLeads.find(item => item.id === id);
    if (!lead) return;
    if (lead.convertedPolicyId) return showToast('This lead is already converted');
    const premium = Number((lead.premium || '').toString().replace(/[^0-9.]/g, '')) || 0;
    openInsuranceForm('Convert lead — confirm customer and draft policy', [
        ['customerName','Customer','text',true],['organization','Organization','text',false],['policyType','Policy product','text',true],
        ['insurer','Insurer','text',false],['premium','Net premium','number',false],['sumInsured','Sum insured','number',false],['startDate','Start date','date',false],['expiryDate','Expiry date','date',true],['assignedTo','Owner',ownerFieldOptions(),true]
    ], values => apiJson(`/api/leads/${id}/convert`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)}), {
        customerName:lead.name, organization:lead.organization, policyType:lead.policyType, premium, expiryDate:lead.expiryDate, assignedTo:lead.assignedTo
    });
}

function editPolicy(id) {
    const p = cachedPolicies.find(x => x.id === id); if (!p) return;
    openInsuranceForm('Edit policy', [['policyNumber','Policy number','text',false],['insurer','Insurer','text',true],['premium','Net premium','number',false],['sumInsured','Sum insured','number',false],['startDate','Start date','date',true],['expiryDate','Expiry date','date',true],['assignedTo','Owner',ownerFieldOptions(),true]], values => apiJson(`/api/policies/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)}), p);
}

function issuePolicy(id) {
    const p = cachedPolicies.find(x => x.id === id); if (!p) return;
    openInsuranceForm('Issue policy — document checklist', [['policyNumber','Final policy number','text',true],['proposalForm','Proposal form verified','checkbox',true],['kyc','KYC verified','checkbox',true],['payment','Payment confirmed','checkbox',true],['schedule','Policy schedule received','checkbox',true]], values => {
        const documentChecklist={proposalForm:values.proposalForm,kyc:values.kyc,payment:values.payment,schedule:values.schedule};
        return apiJson(`/api/policies/${id}/issue`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({policyNumber:values.policyNumber,documentChecklist})});
    }, {policyNumber:p.policyNumber});
}

function completeRenewal(id) {
    const fields=[['policyNumber','New policy number','text',true],['startDate','New start date','date',true],['expiryDate','New expiry date','date',true],['proposalForm','Proposal form verified','checkbox',true],['kyc','KYC verified','checkbox',true],['payment','Payment confirmed','checkbox',true],['schedule','Policy schedule received','checkbox',true]];
    openInsuranceForm('Complete renewal and create successor policy', fields, values => {const documentChecklist={proposalForm:values.proposalForm,kyc:values.kyc,payment:values.payment,schedule:values.schedule};return apiJson(`/api/renewals/${id}/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...values,documentChecklist})})});
}

// ═══════════════════════════════════════════════════════════════════
// 1. LEADS & ACCOUNTS WORKSPACE
// ═══════════════════════════════════════════════════════════════════
function setLeadViewMode(mode) {
    leadViewMode = mode;
    const listBtn = document.getElementById('view-mode-list-btn');
    const kanbanBtn = document.getElementById('view-mode-kanban-btn');
    const listContainer = document.getElementById('leads-list-container');
    const kanbanContainer = document.getElementById('leads-kanban-container');

    if (mode === 'kanban') {
        listBtn.classList.remove('bg-white', 'text-slate-900', 'shadow-xs');
        listBtn.classList.add('text-slate-600');
        kanbanBtn.classList.add('bg-white', 'text-slate-900', 'shadow-xs');
        kanbanBtn.classList.remove('text-slate-600');
        listContainer.classList.add('hidden');
        kanbanContainer.classList.remove('hidden');
        document.getElementById('breadcrumb-view-label').textContent = 'Pipeline Stages';
        renderLeadsKanban(cachedLeads);
    } else {
        kanbanBtn.classList.remove('bg-white', 'text-slate-900', 'shadow-xs');
        kanbanBtn.classList.add('text-slate-600');
        listBtn.classList.add('bg-white', 'text-slate-900', 'shadow-xs');
        listBtn.classList.remove('text-slate-600');
        kanbanContainer.classList.add('hidden');
        listContainer.classList.remove('hidden');
        document.getElementById('breadcrumb-view-label').textContent = 'All Records';
        renderLeadsTable(cachedLeads);
    }
    leadPage = 1;
    loadLeads();
}

async function loadLeads() {
    const search = document.getElementById('leads-search')?.value.trim() || '';
    const status = document.getElementById('leads-status-filter')?.value || '';
    const owner = document.getElementById('leads-owner-filter')?.value || '';

    try {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        if (owner) params.set('assignedTo', owner);
        if (search) params.set('search', search);
        if (activeQuickFilter) params.set('filter', activeQuickFilter);
        params.set('paginated', 'true');
        params.set('page', String(leadPage));
        params.set('pageSize', leadViewMode === 'kanban' ? '200' : '25');

        const result = await apiJson(`/api/leads?${params}`);
        cachedLeads = result.items;
        leadPageMeta = result;

        if (leadViewMode === 'kanban') {
            renderLeadsKanban(cachedLeads);
        } else {
            renderLeadsTable(cachedLeads);
        }

        const first = result.total ? ((result.page - 1) * result.pageSize) + 1 : 0;
        const last = Math.min(result.total, result.page * result.pageSize);
        document.getElementById('leads-count-info').textContent = `Displaying ${first}–${last} of ${result.total} commercial accounts`;
        document.getElementById('lead-page-label').textContent = `Page ${result.page} of ${result.totalPages}`;
        document.getElementById('lead-page-prev').disabled = result.page <= 1;
        document.getElementById('lead-page-next').disabled = result.page >= result.totalPages;
        document.getElementById('lead-pagination').classList.toggle('hidden', leadViewMode === 'kanban');
        if (!savedLeadFilters.length) loadSavedLeadFilters();
    } catch (e) {
        console.error('Failed to load leads:', e);
    }
}

function changeLeadPage(direction) {
    const target = leadPage + direction;
    if (target < 1 || target > leadPageMeta.totalPages) return;
    leadPage = target; loadLeads(); document.getElementById('leads-list-container')?.scrollTo({top:0});
}

function currentLeadFilterCriteria() {
    return {search: document.getElementById('leads-search')?.value.trim() || '',
        status: document.getElementById('leads-status-filter')?.value || '',
        assignedTo: document.getElementById('leads-owner-filter')?.value || '', quickFilter: activeQuickFilter || ''};
}

async function loadSavedLeadFilters() {
    try {
        savedLeadFilters = await apiJson('/api/saved-filters?module=leads');
        const select = document.getElementById('saved-lead-filter');
        const current = select.value;
        select.innerHTML = '<option value="">Saved views</option>' + savedLeadFilters.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
        if (savedLeadFilters.some(item => item.id === current)) select.value = current;
    } catch (_) {}
}

function saveCurrentLeadFilter() {
    openInsuranceForm('Save current lead view', [['name','View name','text',true]], async values => {
        await apiJson('/api/saved-filters', {method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name:values.name,module:'leads',criteria:currentLeadFilterCriteria()})});
        savedLeadFilters = []; await loadSavedLeadFilters();
    });
}

function applySavedLeadFilter(id) {
    const item = savedLeadFilters.find(value => value.id === id); if (!item) return;
    const criteria = item.criteria || {};
    document.getElementById('leads-search').value = criteria.search || '';
    document.getElementById('leads-status-filter').value = criteria.status || '';
    document.getElementById('leads-owner-filter').value = criteria.assignedTo || '';
    activeQuickFilter = criteria.quickFilter || null; leadPage = 1;
    ['expiring','due-today','overdue'].forEach(key => document.getElementById(`pill-${key}`)?.classList.remove('bg-slate-900','text-white'));
    if (activeQuickFilter) {
        const ids={expiring_soon:'pill-expiring',due_today:'pill-due-today',overdue:'pill-overdue'};
        document.getElementById(ids[activeQuickFilter])?.classList.add('bg-slate-900','text-white');
    }
    loadLeads();
}

function renderLeadsTable(leads) {
    const tbody = document.getElementById('leads-table-body');
    if (!leads || leads.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-12 text-slate-400 text-xs">No matching commercial records found</td></tr>';
        return;
    }

    const todayStr = localCalendarDate();

    tbody.innerHTML = leads.map(l => {
        const init = getInitials(l.name);
        const isOverdue = l.nextActionDate && l.nextActionDate < todayStr && !l.nextActionCompleted;
        const isDueToday = l.nextActionDate === todayStr;

        return `
            <tr class="hover:bg-slate-50 transition-colors group cursor-pointer text-xs" onclick="handleRowClick(event, '${l.id}')">
                <td class="px-4 py-2.5 border-r border-slateBorder text-center w-10" onclick="event.stopPropagation()">
                    <input type="checkbox" value="${l.id}" onchange="updateLeadSelectionBar()" class="lead-row-check rounded cursor-pointer">
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder">
                    <div class="flex items-center gap-2.5">
                        <div class="w-6 h-6 rounded bg-slate-800 text-white font-semibold text-[10px] flex items-center justify-center flex-shrink-0">
                            ${init}
                        </div>
                        <div>
                            <div class="font-semibold text-slate-900 group-hover:text-black transition-colors">${esc(l.name)}</div>
                            <div class="text-[11px] text-slate-500 font-medium">${esc(l.policyType)}</div>
                        </div>
                    </div>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-800 font-medium">
                    ${esc(l.organization || 'Individual')}
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder" onclick="event.stopPropagation()">
                    <button onclick="openStageTransitionModal('${l.id}', '${l.status}')" class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium transition-all ${stagePillClass(l.status)}" title="Click to transition stage">
                        <span>${esc(l.status)}</span>
                        <svg class="w-2.5 h-2.5 opacity-60 ml-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder">
                    <div class="flex items-center justify-between gap-2">
                        <span class="text-slate-800 font-medium truncate max-w-[230px]" title="${esc(l.nextAction)}">${esc(l.nextAction || 'Follow-up discussion')}</span>
                        <span class="text-[10px] px-1.5 py-0.2 rounded font-mono font-medium flex-shrink-0 ${isOverdue ? 'bg-rose-50 text-rose-700 border border-rose-200 font-bold' : (isDueToday ? 'bg-amber-50 text-amber-800 border border-amber-200' : 'bg-slate-100 text-slate-600')}">
                            ${formatDueBadge(l.nextActionDate, l.daysRemaining)}
                        </span>
                    </div>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono font-semibold text-slate-900 num-tabular">
                    ${esc(l.premium)}
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-700 font-medium">
                    ${esc(l.assignedTo || 'Sarah Connor')}
                </td>
                <td class="px-2 py-2.5 text-center" onclick="event.stopPropagation()">
                    ${!l.convertedPolicyId ? `<button onclick="convertLeadToPolicy('${l.id}')" class="p-1 text-slate-400 hover:text-emerald-700 rounded" title="Convert to policy">
                        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M20 13c0 5-3.5 7.5-7.7 9C7.5 20.5 4 18 4 13V6l8-3 8 3z"/><path d="M9 12l2 2 4-4"/></svg>
                    </button>` : ''}
                    <button onclick="openLeadDrawer('${l.id}')" class="p-1 text-slate-400 hover:text-slate-900 rounded" title="View Account 360°">
                        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><polyline points="9 18 15 12 9 6"/></svg>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function selectedLeadIds() {
    return [...document.querySelectorAll('.lead-row-check:checked')].map(cb => cb.value);
}

function updateLeadSelectionBar() {
    const ids = selectedLeadIds();
    const bar = document.getElementById('lead-selection-bar');
    const selected = ids.length === 1 ? cachedLeads.find(l => l.id === ids[0]) : null;
    document.getElementById('lead-selection-count').textContent = ids.length > 1
        ? `${ids.length} leads selected — conversion is completed one lead at a time`
        : `${ids.length} lead${ids.length === 1 ? '' : 's'} selected`;
    const convert = document.getElementById('convert-selected-lead');
    if (convert) convert.classList.toggle('hidden', ids.length !== 1 || Boolean(selected?.convertedPolicyId));
    bar.classList.toggle('hidden', ids.length === 0); bar.classList.toggle('flex', ids.length > 0);
}

function convertSelectedLead() {
    const ids = selectedLeadIds();
    if (ids.length !== 1) return showToast('Select exactly one lead to convert');
    convertLeadToPolicy(ids[0]);
}

function startCustomerConversion() {
    switchView('leads');
    clearLeadSelection();
    showToast('Select one lead, then choose “Convert to Customer” in the dark action bar');
    const table = document.getElementById('leads-list-container');
    table?.classList.add('conversion-guidance');
    setTimeout(() => table?.classList.remove('conversion-guidance'), 3500);
}

function clearLeadSelection() {
    document.querySelectorAll('.lead-row-check, #select-all-leads').forEach(cb => cb.checked = false);
    updateLeadSelectionBar();
}

async function bulkLeadUpdate(updates, successMessage) {
    const ids = selectedLeadIds(); if (!ids.length) return;
    const data = await apiJson('/api/leads/bulk-update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids,updates})});
    clearLeadSelection(); showToast(`${data.updatedCount} lead(s) ${successMessage}`); await loadLeads();
}

function bulkAssignLeads() {
    openInsuranceForm('Assign selected leads', [['assignedTo','Assigned broker',ownerFieldOptions(),true]], values => bulkLeadUpdate(values,'assigned'));
}

function bulkScheduleLeads() {
    openInsuranceForm('Schedule selected leads', [['nextAction','Follow-up action','text',true],['nextActionDate','Due date','date',true],['priority','Priority','select:High|Medium|Low',true]], values => bulkLeadUpdate(values,'scheduled'));
}

async function deleteSelectedLeads() {
    const ids = selectedLeadIds(); if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} selected lead${ids.length === 1 ? '' : 's'} and their linked operational records? Activity notes will be archived and retained.`)) return;
    try {
        const results = [];
        for (const id of ids) results.push(await apiJson(`/api/leads/${id}`, {method:'DELETE'}));
        const archived = results.reduce((n,r) => n + Number(r.affected?.notesArchived || 0), 0);
        clearLeadSelection(); showToast(`${ids.length} lead(s) deleted; ${archived} note(s) archived`); await loadLeads();
    } catch (e) { showToast(e.message); }
}

// ─── KANBAN BOARD VIEW ───
function renderLeadsKanban(leads) {
    const boardEl = document.getElementById('leads-kanban-board');
    boardEl.innerHTML = STAGES.map(stg => {
        const stageLeads = (leads || []).filter(l => (l.status || 'New').toLowerCase() === stg.toLowerCase());
        return `
            <div class="w-72 kanban-col flex flex-col max-h-full flex-shrink-0">
                <div class="p-3 border-b border-slateBorder flex items-center justify-between bg-white rounded-t-lg">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold text-slate-900 text-xs">${stg}</span>
                        <span class="text-[10px] font-mono font-semibold px-1.5 py-0.2 rounded bg-slate-100 text-slate-600">${stageLeads.length}</span>
                    </div>
                    <button onclick="openCreateModal()" class="text-slate-400 hover:text-slate-800 text-xs font-bold" title="Add lead">+</button>
                </div>

                <div class="p-2 space-y-2 overflow-y-auto flex-1 max-h-[calc(100vh-210px)]" ondragover="event.preventDefault()" ondrop="handleKanbanDrop(event, '${stg}')">
                    ${stageLeads.map(l => `
                        <div draggable="true" ondragstart="event.dataTransfer.setData('text/plain', '${l.id}')" onclick="openLeadDrawer('${l.id}')" class="kanban-card p-3 cursor-pointer space-y-2">
                            <div>
                                <div class="font-semibold text-slate-900 text-xs truncate">${esc(l.name)}</div>
                                <div class="text-[11px] text-slate-500 font-medium truncate">${esc(l.organization || 'Individual')}</div>
                            </div>

                            <div class="p-1.5 rounded bg-slate-50 border border-slate-100 text-[11px] space-y-0.5">
                                <div class="text-[10px] text-slate-400 uppercase font-medium">Next Action</div>
                                <div class="text-slate-800 font-medium truncate">${esc(l.nextAction || 'Follow-up discussion')}</div>
                                <div class="text-[10px] text-slate-500 font-mono">${esc(l.nextActionDate || 'Pending date')}</div>
                            </div>

                            <div class="flex items-center justify-between pt-1 text-[11px]">
                                <span class="font-mono font-bold text-slate-900 num-tabular">${esc(l.premium)}</span>
                                <span class="text-[10px] text-slate-400">${esc(l.assignedTo)}</span>
                            </div>
                        </div>
                    `).join('')}

                    ${stageLeads.length === 0 ? '<div class="text-center py-8 text-[11px] text-slate-400 italic">No records in this stage</div>' : ''}
                </div>
            </div>
        `;
    }).join('');
}

function handleKanbanDrop(e, targetStage) {
    e.preventDefault();
    const leadId = e.dataTransfer.getData('text/plain');
    if (!leadId) return;
    openStageTransitionModal(leadId, targetStage);
}

function handleRowClick(e, leadId) {
    if (e.target.closest('input, button, select')) return;
    openLeadDrawer(leadId);
}

// ─── Quick Filter Action Pills ───
function applyQuickFilter(type) {
    activeQuickFilter = type;
    leadPage = 1;
    document.querySelectorAll('#pill-expiring, #pill-due-today, #pill-overdue').forEach(p => {
        p.classList.remove('bg-slate-900', 'text-white');
        p.classList.add('border-slate-200', 'text-slate-600');
    });

    const activeBtn = document.getElementById(type === 'expiring_soon' ? 'pill-expiring' : (type === 'due_today' ? 'pill-due-today' : 'pill-overdue'));
    if (activeBtn) {
        activeBtn.classList.add('bg-slate-900', 'text-white');
        activeBtn.classList.remove('border-slate-200', 'text-slate-600');
    }
    loadLeads();
}

function resetLeadsFilters() {
    activeQuickFilter = null;
    leadPage = 1;
    document.querySelectorAll('#pill-expiring, #pill-due-today, #pill-overdue').forEach(p => {
        p.classList.remove('bg-slate-900', 'text-white');
        p.classList.add('border-slate-200', 'text-slate-600');
    });
    document.getElementById('leads-search').value = '';
    document.getElementById('leads-status-filter').value = '';
    document.getElementById('leads-owner-filter').value = '';
    document.getElementById('saved-lead-filter').value = '';
    loadLeads();
}

// ═══════════════════════════════════════════════════════════════════
// 2. STAGE TRANSITION & NEXT ACTION DISCIPLINE MODAL
// ═══════════════════════════════════════════════════════════════════
function openStageTransitionModal(leadId, targetStage) {
    const lead = cachedLeads.find(l => l.id === leadId);
    if (!lead) return;

    document.getElementById('stage-modal-lead-id').value = lead.id;
    document.getElementById('stage-modal-lead-name').textContent = `${lead.name} (${lead.organization})`;
    document.getElementById('stage-modal-old-stage').textContent = lead.status;
    document.getElementById('stage-modal-new-stage').value = targetStage || lead.status;

    const nextActionSelect = document.getElementById('stage-modal-next-action-select');
    const customInput = document.getElementById('stage-modal-custom-action');
    customInput.classList.add('hidden');

    const stageDefaults = {
        'Contacted': 'Collect Fleet RC Books & NCB Proof',
        'Risk / Underwriting': 'Dispatch Surveyor for On-site Inspection',
        'Quotation Sent': 'Deliver Comparative Quotation to Client',
        'Won': 'Collect Payment & Issue Policy Schedule',
        'Lost': 'Lost to Competitor'
    };

    if (stageDefaults[targetStage]) {
        nextActionSelect.value = stageDefaults[targetStage];
    } else {
        nextActionSelect.value = 'custom';
        customInput.classList.remove('hidden');
        customInput.value = lead.nextAction || '';
    }

    const d = new Date();
    d.setDate(d.getDate() + 2);
    document.getElementById('stage-modal-action-date').value = d.toISOString().split('T')[0];
    document.getElementById('stage-modal-note').value = '';

    const lostContainer = document.getElementById('stage-modal-lost-container');
    if (targetStage === 'Lost') lostContainer.classList.remove('hidden');
    else lostContainer.classList.add('hidden');

    document.getElementById('stage-transition-modal').classList.remove('hidden');
}

function closeStageTransitionModal() {
    document.getElementById('stage-transition-modal').classList.add('hidden');
}

function handleNextActionSelectChange(val) {
    const custom = document.getElementById('stage-modal-custom-action');
    if (val === 'custom') {
        custom.classList.remove('hidden');
        custom.focus();
    } else {
        custom.classList.add('hidden');
    }
}

async function handleStageTransitionSubmit(e) {
    e.preventDefault();
    const leadId = document.getElementById('stage-modal-lead-id').value;
    const newStage = document.getElementById('stage-modal-new-stage').value;
    const selectAction = document.getElementById('stage-modal-next-action-select').value;
    const customAction = document.getElementById('stage-modal-custom-action').value.trim();
    const nextAction = (selectAction === 'custom' ? customAction : selectAction) || 'Follow-up discussion';
    const nextActionDate = document.getElementById('stage-modal-action-date').value;
    const stageNote = document.getElementById('stage-modal-note').value.trim();
    const lostReason = newStage === 'Lost' ? document.getElementById('stage-modal-lost-reason').value : '';

    try {
        await apiJson(`/api/leads/${leadId}/stage`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                status: newStage,
                nextAction,
                nextActionDate,
                stageNote,
                lostReason,
                author: signedInUser?.name || 'System'
            })
        });

        closeStageTransitionModal();
        showToast(`Stage updated to "${newStage}". Next action scheduled.`);
        loadLeads();
        if (document.getElementById('detail-drawer')?.classList.contains('translate-x-0')) {
            openLeadDrawer(leadId);
        }
    } catch (err) {
        showToast(err.message || 'Could not update the stage.');
    }
}

// ═══════════════════════════════════════════════════════════════════
// 3. 360° LEAD DETAIL DRAWER
// ═══════════════════════════════════════════════════════════════════
async function openLeadDrawer(leadId) {
    try {
        const res = await fetch(`/api/leads/${leadId}`);
        if (!res.ok) return;
        const data = await res.json();
        const l = data.lead;
        const notes = data.notes || [];
        const documents = await apiJson(`/api/documents?associatedId=${encodeURIComponent(leadId)}`);

        document.getElementById('drawer-title').textContent = l.name;
        document.getElementById('drawer-org').textContent = `${l.organization || 'Corporate Account'} • ${l.territory || 'India'}`;

        const content = document.getElementById('drawer-content');
        content.innerHTML = `
            <div class="flex justify-end gap-2"><button onclick="openCalendarEventForm('Lead','${l.id}')" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold">Schedule activity</button><button onclick="openEditLead('${l.id}')" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Edit lead details</button></div>
            <!-- Stage Chevron Progression -->
            <div class="space-y-1.5 pb-3 border-b border-slateBorder">
                <div class="text-[10px] uppercase font-semibold text-slate-500">Pipeline Stage</div>
                <div class="grid grid-cols-6 gap-1">
                    ${STAGES.map(stg => {
                        const isCurrent = l.status === stg;
                        return `
                            <button onclick="openStageTransitionModal('${l.id}', '${stg}')" class="stage-step ${isCurrent ? 'active' : ''} text-[10px] py-1">
                                ${stg.split(' ')[0]}
                            </button>
                        `;
                    }).join('')}
                </div>
            </div>

            <div class="border border-slateBorder rounded-lg p-3 bg-white space-y-2">
                <div class="flex justify-between"><span class="text-[11px] font-bold uppercase tracking-wider">Documents (${documents.filter(d=>d.status==='Active').length})</span></div>
                <div class="flex flex-wrap gap-2"><select id="lead-document-category" class="corp-input flex-1"><option>KYC</option><option>Proposal Form</option><option>Quote</option><option>Policy Schedule</option><option>Claims History</option><option>Other</option></select><input id="lead-document-file" type="file" class="corp-input flex-[2]" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.csv,.txt"><button onclick="uploadLeadDocument('${l.id}')" class="px-3 bg-slate-900 text-white rounded text-xs font-semibold">Upload</button></div>
                <div class="space-y-1">${documents.filter(d=>d.status==='Active').map(d=>`<div class="text-xs flex justify-between border-t pt-1"><a class="font-medium underline" href="/api/documents/${d.id}/content" target="_blank">${esc(d.originalName)}</a><span class="text-slate-400">${esc(d.category)} · v${d.version}</span></div>`).join('')||'<p class="text-xs text-slate-400">No documents uploaded.</p>'}</div>
            </div>

            <!-- Prominent Next Action Card -->
            <div class="p-3 rounded-lg border border-slate-300 bg-slate-50/70 space-y-2">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Scheduled Next Action</span>
                    <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white border border-slate-200 font-bold ${l.daysRemaining <= 10 ? 'text-rose-600' : 'text-slate-800'}">
                        Due: ${esc(l.nextActionDate)}
                    </span>
                </div>
                <div class="font-semibold text-slate-900 text-xs">${esc(l.nextAction)}</div>
                <div class="flex items-center justify-between pt-1 border-t border-slate-200 text-[11px]">
                    <span class="text-slate-500">Assigned: <strong>${esc(l.assignedTo)}</strong></span>
                    <button onclick="openStageTransitionModal('${l.id}', '${l.status}')" class="text-black font-semibold hover:underline">
                        Reschedule / Update →
                    </button>
                </div>
            </div>

            <!-- Commercial Policy Schedule -->
            <div class="border border-slateBorder rounded-lg p-3 bg-white space-y-2 text-xs">
                <div class="text-[11px] font-bold text-slate-800 uppercase tracking-wider">Commercial Policy Schedule</div>
                <div class="grid grid-cols-2 gap-2">
                    <div>
                        <span class="text-slate-400 block text-[10px]">Contact Mobile</span>
                        <span class="font-mono text-slate-800 font-medium">${esc(l.mobile)}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[10px]">Contact Email</span>
                        <span class="font-mono text-slate-800 truncate block">${esc(l.email || '-')}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[10px]">Policy Category</span>
                        <span class="text-slate-900 font-medium">${esc(l.policyType)}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[10px]">Annual Premium</span>
                        <span class="text-slate-900 font-bold font-mono num-tabular">${esc(l.premium)}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[10px]">Expiry / Renewal Due</span>
                        <span class="text-slate-800 font-mono">${l.expiryDate ? `${esc(l.expiryDate)} (${formatDaysLeft(l.daysRemaining)})` : 'Not set'}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[10px]">Policy Number</span>
                        <span class="text-slate-800 font-mono">${esc(l.policyNumber || '-')}</span>
                    </div>
                </div>
            </div>

            ${Object.keys(l.customFields || {}).length ? `
            <!-- Columns carried over from the client's own spreadsheet -->
            <div class="p-3 rounded-lg border border-slateBorder bg-white space-y-2">
                <div class="flex items-center justify-between">
                    <div class="text-[11px] font-bold text-slate-800 uppercase tracking-wider">Extra Details</div>
                    <span class="text-[10px] text-slate-400">From imported file</span>
                </div>
                <div class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                    ${Object.entries(l.customFields).map(([key, value]) => `
                        <div>
                            <span class="text-slate-400 block text-[10px]">${esc(key)}</span>
                            <span class="text-slate-800">${esc(value)}</span>
                        </div>`).join('')}
                </div>
            </div>` : ''}

            <!-- Action Buttons -->
            <div class="flex items-center gap-2 pt-1">
                <button onclick="openCreateNoteModal('Lead', '${l.id}')" class="flex-1 py-1.5 px-3 bg-white border border-slate-300 hover:bg-slate-50 text-slate-800 font-semibold rounded text-xs shadow-xs text-center">
                    + Log Activity Note
                </button>
                <button onclick="openSendMessage('${l.id}')" class="flex-1 py-1.5 px-3 bg-white border border-slate-300 hover:bg-slate-50 text-slate-800 font-semibold rounded text-xs shadow-xs text-center">
                    Send Message
                </button>
                <button onclick="openCreateTaskModal('Lead', '${l.id}')" class="flex-1 py-1.5 px-3 bg-white border border-slate-300 hover:bg-slate-50 text-slate-800 font-semibold rounded text-xs shadow-xs text-center">
                    + Schedule Task
                </button>
            </div>

            <!-- Chronological Activity Feed -->
            <div class="space-y-2 pt-2 border-t border-slateBorder">
                <div class="text-[11px] font-bold text-slate-800 uppercase tracking-wider">Activity History (${notes.length})</div>
                <div class="space-y-2 max-h-56 overflow-y-auto pr-1">
                    ${notes.length ? notes.map(n => `
                        <div class="p-2.5 rounded bg-slate-50 border border-slate-200 text-xs space-y-1">
                            <div class="flex items-center justify-between font-semibold text-slate-900">
                                <span>${esc(n.title)}</span>
                                <span class="text-[9px] px-1.5 py-0.2 rounded bg-white border border-slate-200 text-slate-600 font-normal">${esc(n.category || 'Note')}</span>
                            </div>
                            <div class="text-slate-700 leading-relaxed">${esc(n.content)}</div>
                            <div class="text-[10px] text-slate-400 pt-1 border-t border-slate-200 flex justify-between font-mono">
                                <span>${esc(n.author)}</span>
                                <span>${timeAgo(n.createdAt)}</span>
                            </div>
                        </div>
                    `).join('') : '<div class="text-slate-400 italic py-2">No activity notes recorded yet.</div>'}
                </div>
            </div>
        `;

        document.getElementById('detail-drawer').classList.remove('translate-x-full');
    } catch (e) {
        console.error('Error opening drawer:', e);
    }
}

async function uploadLeadDocument(leadId){
    const input=document.getElementById('lead-document-file'); const file=input?.files?.[0]; if(!file)return showToast('Choose a document first');
    try{await apiJson(`/api/documents?associatedId=${encodeURIComponent(leadId)}&associatedType=Lead&category=${encodeURIComponent(document.getElementById('lead-document-category').value)}&filename=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});showToast('Document uploaded');await openLeadDrawer(leadId)}catch(e){showToast(e.message)}
}

function closeDrawer() {
    document.getElementById('detail-drawer')?.classList.add('translate-x-full');
}

// ═══════════════════════════════════════════════════════════════════
// 4. ACTIVITY NOTES (ENHANCED CORPORATE UX)
// ═══════════════════════════════════════════════════════════════════
async function loadNotes() {
    try {
        const res = await fetch('/api/notes');
        cachedNotes = await res.json();
        renderNotesGrid(cachedNotes);
    } catch (e) { console.error(e); }
}

function renderNotesGrid(notes) {
    const grid = document.getElementById('notes-grid');
    const badge = document.getElementById('notes-count-badge');
    if (badge) badge.textContent = `${notes.length} total notes`;

    if (!notes.length) {
        grid.innerHTML = '<div class="col-span-3 py-16 text-center text-slate-400 text-xs">No activity notes found. Click "New Activity Note" to log an underwriting memo or call summary.</div>';
        return;
    }

    grid.innerHTML = notes.map(n => {
        const catColor = getCategoryColor(n.category);
        return `
            <div class="border border-slateBorder rounded-lg p-4 bg-white hover:border-slate-400 transition-all flex flex-col justify-between shadow-xs space-y-3 cursor-pointer group" onclick="handleNoteCardClick('${n.associatedId}')">
                <div class="space-y-2">
                    <!-- Prominent Clickable Account Link -->
                    <div class="flex items-start justify-between gap-1.5 border-b border-slate-100 pb-2">
                        <button onclick="event.stopPropagation(); openLeadDrawer('${n.associatedId}')" class="font-bold text-slate-900 group-hover:text-black hover:underline text-xs flex items-center gap-1.5 text-left truncate" title="View Account 360°">
                            <span class="w-1.5 h-1.5 rounded-full bg-slate-800"></span>
                            <span class="truncate">${esc(n.associatedTitle || 'General Account')}</span>
                        </button>
                        <span class="px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${catColor}">
                            ${esc(n.category || 'Note')}
                        </span>
                    </div>

                    <!-- Note Title & Content -->
                    <div>
                        <h4 class="font-semibold text-slate-900 text-xs">${esc(n.title)}</h4>
                        <p class="text-xs text-slate-600 line-clamp-3 leading-relaxed mt-1">${esc(n.content)}</p>
                    </div>
                </div>

                <!-- Footer with Author, Date and Action -->
                <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
                    <span class="font-medium text-slate-600">${esc(n.author || 'Sarah Connor')}</span>
                    <div class="flex items-center gap-2">
                        <span>${timeAgo(n.createdAt)}</span>
                        <button onclick="event.stopPropagation(); archiveNoteAction('${n.id}')" class="note-action" title="Archive this note — it stays on the record's history">Archive</button>
                        <button onclick="event.stopPropagation(); deleteNoteAction('${n.id}')" class="note-action is-delete" title="Delete this note permanently">Delete</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function handleNoteCardClick(associatedId) {
    if (associatedId) {
        openLeadDrawer(associatedId);
    }
}

function filterNotesList() {
    const q = document.getElementById('notes-search-input')?.value.trim().toLowerCase() || '';
    const cat = document.getElementById('notes-category-filter')?.value || '';

    const filtered = cachedNotes.filter(n => {
        const matchesQ = !q || n.title.toLowerCase().includes(q) || n.content.toLowerCase().includes(q) || (n.associatedTitle || '').toLowerCase().includes(q);
        const matchesCat = !cat || n.category === cat;
        return matchesQ && matchesCat;
    });
    renderNotesGrid(filtered);
}

async function openCreateNoteModal(prefillType = '', prefillId = '') {
    const modal = document.getElementById('note-modal');
    modal.classList.remove('hidden');

    const select = document.getElementById('note-modal-entity');
    select.innerHTML = '<option value="">Select Account / Record...</option>';

    try {
        const res = await fetch('/api/entities');
        const entities = await res.json();
        entities.forEach(ent => {
            const opt = document.createElement('option');
            opt.value = `${ent.type}:${ent.id}`;
            opt.textContent = `[${ent.type}] ${ent.title}`;
            if (prefillType && prefillId && ent.type === prefillType && ent.id === prefillId) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });
    } catch (e) { console.error(e); }
}

function closeNoteModal() {
    document.getElementById('note-modal')?.classList.add('hidden');
    document.getElementById('note-modal-title').value = '';
    document.getElementById('note-modal-content').value = '';
}

async function handleNoteSubmit(e) {
    e.preventDefault();
    const title = document.getElementById('note-modal-title').value.trim();
    const entityVal = document.getElementById('note-modal-entity').value;
    const category = document.getElementById('note-modal-category').value;
    const content = document.getElementById('note-modal-content').value.trim();
    const pinned = document.getElementById('note-modal-pin').checked;

    let associatedType = 'Lead';
    let associatedId = '';
    if (entityVal.includes(':')) {
        [associatedType, associatedId] = entityVal.split(':');
    }

    const selectEl = document.getElementById('note-modal-entity');
    const selectedText = selectEl.options[selectEl.selectedIndex]?.text || '';
    const associatedTitle = selectedText.replace(/^\[.*?\]\s*/, '') || 'Account';

    try {
        await apiJson('/api/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                associatedType,
                associatedId,
                associatedTitle,
                category,
                content,
                pinned,
                author: signedInUser?.name || 'System'
            })
        });
        closeNoteModal();
        showToast('Activity note saved.');
        if (currentView === 'notes') loadNotes();
    } catch (err) { showToast(err.message || 'Could not save note.'); }
}

// Archive keeps the record as evidence; delete removes it. The dialog says which is which,
// because on a client's account these are very different decisions.
async function archiveNoteAction(id) {
    const ok = await confirmDestructive({
        title: 'Archive this note?',
        body: 'It disappears from the Activity Notes list but stays attached to the record for audit. You can restore it later.',
        confirmLabel: 'Archive note', tone: 'neutral'
    });
    if (!ok) return;
    try {
        await apiJson(`/api/notes/${id}/archive`, { method: 'POST' });
        showToast('Note archived.');
        loadNotes();
    } catch (e) { showToast(e.message || 'Could not archive note.'); }
}

async function deleteNoteAction(id) {
    const ok = await confirmDestructive({
        title: 'Delete this note permanently?',
        body: 'This cannot be undone. If you only want it out of the way, archive it instead — that keeps it on the record.',
        confirmLabel: 'Delete permanently', tone: 'danger'
    });
    if (!ok) return;
    try {
        await apiJson(`/api/notes/${id}`, { method: 'DELETE' });
        showToast('Note deleted.');
        loadNotes();
    } catch (e) { showToast(e.message || 'Could not delete note.'); }
}

// One dialog for every destructive action, so the wording and the stakes are consistent.
function confirmDestructive({ title, body, confirmLabel = 'Confirm', tone = 'danger' }) {
    return new Promise(resolve => {
        const existing = document.getElementById('confirm-overlay');
        if (existing) existing.remove();
        const overlay = document.createElement('div');
        overlay.id = 'confirm-overlay';
        overlay.className = 'confirm-overlay';
        overlay.innerHTML = `
            <div class="confirm-box" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
                <h3 id="confirm-title">${esc(title)}</h3>
                <p>${esc(body)}</p>
                <div class="confirm-actions">
                    <button type="button" class="confirm-cancel">Cancel</button>
                    <button type="button" class="confirm-go ${tone === 'danger' ? 'is-danger' : ''}">${esc(confirmLabel)}</button>
                </div>
            </div>`;
        const close = value => { overlay.remove(); document.removeEventListener('keydown', onKey); resolve(value); };
        const onKey = e => { if (e.key === 'Escape') close(false); };
        overlay.querySelector('.confirm-cancel').onclick = () => close(false);
        overlay.querySelector('.confirm-go').onclick = () => close(true);
        overlay.onclick = e => { if (e.target === overlay) close(false); };
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
        overlay.querySelector('.confirm-go').focus();
    });
}

// ═══════════════════════════════════════════════════════════════════
// 5. ACTION TASKS (TRIAGED CORPORATE UX)
// ═══════════════════════════════════════════════════════════════════
async function loadTasks() {
    try {
        cachedTasks = (await apiJson('/api/tasks')).filter(task => task.status !== 'Archived');
        renderTasksList();
    } catch (e) { console.error(e); }
}

function setTaskTab(tab) {
    activeTaskTab = tab;
    document.querySelectorAll('#task-tab-all, #task-tab-overdue, #task-tab-today, #task-tab-upcoming, #task-tab-completed').forEach(b => {
        b.classList.remove('bg-slate-200/80', 'text-slate-900', 'font-semibold');
        b.classList.add('text-slate-600', 'font-medium');
    });
    const activeBtn = document.getElementById(`task-tab-${tab}`);
    if (activeBtn) {
        activeBtn.classList.add('bg-slate-200/80', 'text-slate-900', 'font-semibold');
        activeBtn.classList.remove('text-slate-600', 'font-medium');
    }
    renderTasksList();
}

function renderTasksList() {
    const listEl = document.getElementById('tasks-list');
    const todayStr = localCalendarDate();

    // Counts
    const all = cachedTasks.length;
    const overdue = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate && t.dueDate < todayStr).length;
    const today = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate === todayStr).length;
    const upcoming = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate && t.dueDate > todayStr).length;
    const completed = cachedTasks.filter(t => t.status === 'Completed').length;

    document.getElementById('task-badge-all').textContent = `(${all})`;
    document.getElementById('task-badge-overdue').textContent = overdue > 0 ? `(${overdue})` : '';
    document.getElementById('task-badge-today').textContent = today > 0 ? `(${today})` : '';
    document.getElementById('task-badge-upcoming').textContent = `(${upcoming})`;
    document.getElementById('task-badge-completed').textContent = `(${completed})`;

    let filtered = cachedTasks;
    if (activeTaskTab === 'overdue') {
        filtered = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate && t.dueDate < todayStr);
    } else if (activeTaskTab === 'today') {
        filtered = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate === todayStr);
    } else if (activeTaskTab === 'upcoming') {
        filtered = cachedTasks.filter(t => t.status !== 'Completed' && t.dueDate && t.dueDate > todayStr);
    } else if (activeTaskTab === 'completed') {
        filtered = cachedTasks.filter(t => t.status === 'Completed');
    }

    if (!filtered.length) {
        listEl.innerHTML = '<div class="p-12 text-center text-slate-400 text-xs">No tasks in this triage category. Click "Schedule Task" to add a new action item.</div>';
        return;
    }

    listEl.innerHTML = filtered.map(t => {
        const isDone = t.status === 'Completed';
        const isOver = !isDone && t.dueDate && t.dueDate < todayStr;
        const isToday = !isDone && t.dueDate === todayStr;

        return `
            <div class="p-3 rounded-lg border border-slateBorder bg-white hover:border-slate-400 transition-all flex items-center justify-between text-xs group cursor-pointer shadow-xs" onclick="handleTaskRowClick('${t.associatedId}', '${t.associatedType}')">
                <div class="flex items-center gap-3 min-w-0">
                    <!-- Interactive Checkbox -->
                    <input type="checkbox" ${isDone ? 'checked' : ''} onclick="event.stopPropagation()" onchange="toggleTaskStatus('${t.id}', this.checked)" class="rounded text-black cursor-pointer w-4 h-4">
                    
                    <div class="space-y-1 min-w-0">
                        <div class="flex items-center gap-2 flex-wrap">
                            <!-- Clickable Account Link -->
                            <button onclick="event.stopPropagation(); handleTaskRowClick('${t.associatedId}', '${t.associatedType}')" class="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-800 font-semibold text-[11px] truncate max-w-[200px]" title="Open related record">
                                🏢 ${esc(t.associatedTitle || 'General')}
                            </button>
                            <span class="${isDone ? 'line-through text-slate-400' : 'font-semibold text-slate-900'} truncate">${esc(t.title)}</span>
                        </div>
                        <div class="text-[11px] text-slate-400 flex items-center gap-2 font-mono">
                            <span>${esc(t.activityType || 'Follow-up')} · Assigned: ${esc(t.assignedTo)}</span>
                        </div>
                    </div>
                </div>

                <div class="flex items-center gap-2.5 flex-shrink-0" onclick="event.stopPropagation()">
                    <!-- Due Date Badge -->
                    <span class="text-[11px] px-2 py-0.5 rounded font-mono font-medium ${isOver ? 'bg-rose-50 text-rose-700 border border-rose-200 font-bold' : (isToday ? 'bg-amber-50 text-amber-800 border border-amber-200' : 'bg-slate-100 text-slate-600')}">
                        ${isOver ? `Overdue (${t.dueDate})` : (isToday ? 'Due Today' : t.dueDate)}
                    </span>
                    <span class="text-[10px] font-semibold px-2 py-0.5 rounded ${t.priority === 'High' ? 'bg-rose-100 text-rose-800' : 'bg-slate-100 text-slate-700'}">
                        ${esc(t.priority)}
                    </span>
                    <button onclick="deleteTaskAction('${t.id}')" class="text-slate-300 hover:text-rose-600 p-1 opacity-0 group-hover:opacity-100 transition-opacity" title="Delete Task">
                        ✕
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function handleTaskRowClick(associatedId, associatedType = 'Lead') {
    if (associatedId) {
        openCalendarLink(associatedType, associatedId);
    }
}

async function toggleTaskStatus(id, isDone) {
    try {
        await apiJson(`/api/tasks/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: isDone ? 'Completed' : 'Pending' })
        });
        showToast(isDone ? 'Task marked completed.' : 'Task reopened.');
        loadTasks();
        refreshNotificationBadge();
    } catch (e) { showToast(e.message || 'Could not update task.'); loadTasks(); }
}

async function openCreateTaskModal(prefillType = '', prefillId = '') {
    const modal = document.getElementById('task-modal');
    modal.classList.remove('hidden');

    const select = document.getElementById('task-modal-entity');
    select.innerHTML = '<option value="">Select Account / Record...</option>';

    try {
        const res = await fetch('/api/entities');
        const entities = await res.json();
        entities.forEach(ent => {
            const opt = document.createElement('option');
            opt.value = `${ent.type}:${ent.id}`;
            opt.textContent = `[${ent.type}] ${ent.title}`;
            if (prefillType && prefillId && ent.type === prefillType && ent.id === prefillId) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });
    } catch (e) { console.error(e); }

    const d = new Date();
    d.setDate(d.getDate() + 1);
    document.getElementById('task-modal-date').value = d.toISOString().split('T')[0];
}

function closeTaskModal() {
    document.getElementById('task-modal')?.classList.add('hidden');
    document.getElementById('task-modal-title').value = '';
}

async function handleTaskSubmit(e) {
    e.preventDefault();
    const title = document.getElementById('task-modal-title').value.trim();
    const entityVal = document.getElementById('task-modal-entity').value;
    const priority = document.getElementById('task-modal-priority').value;
    const dueDate = document.getElementById('task-modal-date').value;
    const assignedTo = document.getElementById('task-modal-assignee').value;
    const activityType = document.getElementById('task-modal-type').value;

    let associatedType = 'Lead';
    let associatedId = '';
    if (entityVal.includes(':')) {
        [associatedType, associatedId] = entityVal.split(':');
    }

    const selectEl = document.getElementById('task-modal-entity');
    const selectedText = selectEl.options[selectEl.selectedIndex]?.text || '';
    const associatedTitle = selectedText.replace(/^\[.*?\]\s*/, '') || 'Account';

    try {
        await apiJson('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                associatedType,
                associatedId,
                associatedTitle,
                priority,
                dueDate,
                assignedTo
                ,activityType
            })
        });
        closeTaskModal();
        showToast('Action task scheduled.');
        if (currentView === 'tasks') loadTasks();
        else refreshCurrentView();
    } catch (err) { showToast(err.message || 'Could not schedule task.'); }
}

async function deleteTaskAction(id) {
    if (!confirm('Delete this task?')) return;
    try {
        await apiJson(`/api/tasks/${id}`, { method: 'DELETE' });
        showToast('Task removed.');
        loadTasks();
    } catch (e) { showToast(e.message || 'Could not delete task.'); }
}

// ═══════════════════════════════════════════════════════════════════
// 6. CREATE LEAD FORM SUBMISSION
// ═══════════════════════════════════════════════════════════════════
function openCreateModal() {
    editingLeadId = null;
    document.getElementById('lead-form-title').textContent = 'New Insurance Lead';
    document.getElementById('lead-form-submit').textContent = 'Save Lead';
    document.querySelector('#create-modal form').reset();
    document.getElementById('lead-next-action').value = 'Initial Discovery Discussion';
    document.getElementById('lead-next-action-date').value = new Date().toISOString().split('T')[0];
    document.getElementById('create-modal')?.classList.remove('hidden');
}

async function openEditLead(id) {
    const data = await apiJson(`/api/leads/${id}`); const l = data.lead; editingLeadId = id;
    document.getElementById('lead-form-title').textContent = 'Edit Lead'; document.getElementById('lead-form-submit').textContent = 'Save Changes';
    const values = { 'lead-name':l.name, 'lead-organization':l.organization, 'lead-mobile':l.mobile, 'lead-email':l.email, 'lead-policy-type':l.policyType,
        'lead-premium':l.premium, 'lead-expiry':l.expiryDate, 'lead-owner':l.assignedTo, 'lead-next-action':l.nextAction, 'lead-next-action-date':l.nextActionDate };
    Object.entries(values).forEach(([key,value]) => { const el=document.getElementById(key); if(el) el.value=value||''; });
    document.getElementById('lead-notes').value=''; document.getElementById('create-modal').classList.remove('hidden');
}

function closeCreateModal() {
    document.getElementById('create-modal')?.classList.add('hidden');
}

async function handleCreateLeadSubmit(e) {
    e.preventDefault();
    const fullName = document.getElementById('lead-name').value.trim();
    const org = document.getElementById('lead-organization').value.trim();
    const mobile = document.getElementById('lead-mobile').value.trim();
    const email = document.getElementById('lead-email').value.trim();
    const policyType = document.getElementById('lead-policy-type').value;
    const premium = document.getElementById('lead-premium').value.trim() || '₹ 50,000';
    const expiryDate = document.getElementById('lead-expiry').value || '';
    const assignedTo = document.getElementById('lead-owner').value;
    const nextAction = document.getElementById('lead-next-action').value.trim();
    const nextActionDate = document.getElementById('lead-next-action-date').value;
    const notes = document.getElementById('lead-notes').value.trim();

    try {
        await apiJson(editingLeadId ? `/api/leads/${editingLeadId}` : '/api/leads', {
            method: editingLeadId ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                firstName: fullName, name: fullName,
                organization: org,
                mobile,
                email,
                policyType,
                premium,
                expiryDate,
                assignedTo,
                nextAction,
                nextActionDate,
                notes
            })
        });

        closeCreateModal();
        showToast(editingLeadId ? 'Lead details updated and synchronized.' : 'Commercial lead created. Account and contact synced.');
        editingLeadId = null;
        loadLeads();
    } catch (err) { showToast(err.message || 'Could not save lead.'); }
}

// ═══════════════════════════════════════════════════════════════════
// 7. DASHBOARD, DEALS, CONTACTS & ORGANIZATIONS
// ═══════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════
// DASHBOARD — the day's work first, configurable per person
// ═══════════════════════════════════════════════════════════════════
let dashboardLayout = null;

async function loadDashboard() {
    try {
        const [data, layout] = await Promise.all([apiJson('/api/dashboard'), apiJson('/api/dashboard/layout')]);
        dashboardLayout = layout;
        window.crmDashboard = data;

        const hour = new Date().getHours();
        const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
        const who = (document.getElementById('current-user-name')?.textContent || '').split(' ')[0];
        document.getElementById('dash-greeting').textContent = who ? `${greeting}, ${who}` : 'Your day';
        document.getElementById('dash-date').textContent = new Date().toLocaleDateString('en-IN',
            { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });

        const hidden = new Set(layout.hidden || []);
        document.getElementById('dashboard-panels').innerHTML =
            layout.order.filter(id => !hidden.has(id)).map(id => renderDashboardPanel(id, data)).join('')
            || '<div class="text-xs text-slate-400 text-center py-10">Every panel is hidden. Use Customise to bring some back.</div>';
        drawWorkTrend(data.workTrend || []);
    } catch (e) { console.error(e); }
}

function dashPanel(title, subtitle, body, action = '') {
    return `<section class="bg-white border border-slateBorder rounded-lg">
        <div class="flex items-start justify-between gap-3 px-4 py-3 border-b border-slateBorder">
            <div><h2 class="text-xs font-semibold uppercase tracking-wider text-slate-900">${esc(title)}</h2>
                 <p class="text-[11px] text-slate-500 mt-0.5">${esc(subtitle)}</p></div>
            ${action}
        </div>
        <div class="p-4">${body}</div>
    </section>`;
}

function taskLine(t, tone) {
    const overdue = tone === 'overdue';
    return `<button onclick="openLeadDrawer('${t.associatedId || ''}')" class="w-full text-left flex items-center justify-between gap-3 py-2 border-b border-slate-100 last:border-0 hover:bg-slate-50 px-1 -mx-1 rounded">
        <span class="min-w-0">
            <span class="block text-xs font-medium text-slate-800 truncate">${esc(t.title || '')}</span>
            <span class="block text-[11px] text-slate-500 truncate">${esc(t.associatedTitle || '')}${t.assignedTo ? ` · ${esc(t.assignedTo)}` : ''}</span>
        </span>
        <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0 ${overdue ? 'bg-rose-50 text-rose-700 border border-rose-200' : 'bg-slate-100 text-slate-600'}">
            ${overdue ? 'Overdue' : esc(t.dueDate || '')}
        </span>
    </button>`;
}

function renderDashboardPanel(id, d) {
    const c = d.todayCounts || {};
    if (id === 'today') {
        const tiles = [
            ['Overdue', c.overdue, 'is-critical', "switchView('tasks')"],
            ['Due today', c.dueToday, 'is-warning', "switchView('tasks')"],
            ['Completed today', c.completedToday, 'is-good', "switchView('tasks')"],
            ['Next 7 days', c.next7Days, '', "switchView('calendar')"],
        ];
        return dashPanel('Today at a glance', 'Your workload right now',
            `<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
                ${tiles.map(([label, value, tone, go]) => `
                    <button onclick="${go}" class="day-tile ${tone}">
                        <strong>${value ?? 0}</strong><span>${label}</span>
                    </button>`).join('')}
            </div>`);
    }
    if (id === 'myDay') {
        const items = d.myDay || [];
        const today = d.today;
        return dashPanel('My day', 'Overdue first, then due today',
            items.length ? items.map(t => taskLine(t, (t.dueDate || '') < today ? 'overdue' : 'today')).join('')
                         : '<p class="text-xs text-slate-400 py-6 text-center">Nothing outstanding. Everything due today is done.</p>',
            `<button onclick="switchView('tasks')" class="text-[11px] font-semibold text-slate-600">All tasks</button>`);
    }
    if (id === 'renewals') {
        const items = d.renewalsDueThisWeek || [];
        return dashPanel('Renewal radar', 'Policies expiring within 15 days',
            items.length ? items.slice(0, 8).map(l => `
                <button onclick="openLeadDrawer('${l.id}')" class="w-full text-left flex items-center justify-between gap-3 py-2 border-b border-slate-100 last:border-0 hover:bg-slate-50 px-1 -mx-1 rounded">
                    <span class="min-w-0"><span class="block text-xs font-medium text-slate-800 truncate">${esc(l.name)}</span>
                    <span class="block text-[11px] text-slate-500 truncate">${esc(l.organization || '')} · ${esc(l.policyType || '')} · ${esc(l.premium || '')}</span></span>
                    <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0 bg-rose-50 text-rose-700 border border-rose-200">${esc(formatDaysLeft(l.daysRemaining))}</span>
                </button>`).join('')
                : '<p class="text-xs text-slate-400 py-6 text-center">No policy expires in the next 15 days.</p>',
            `<button onclick="switchView('renewals')" class="text-[11px] font-semibold text-slate-600">Renewals</button>`);
    }
    if (id === 'trend') {
        return dashPanel('Work trend', 'Scheduled versus completed, last 7 days',
            `<div id="work-trend" class="viz-root"></div>`);
    }
    if (id === 'pipeline') {
        const stages = d.pipelineByStage || {};
        const max = Math.max(1, ...Object.values(stages));
        const total = Object.values(stages).reduce((a, b) => a + b, 0);
        return dashPanel('Pipeline by stage', `${total} accounts · open value ${esc(d.pipelineValue || '')}`,
            `<div class="space-y-2">${Object.entries(stages).map(([stage, n]) => `
                <button onclick="filterLeadsByStage('${esc(stage)}')" class="w-full text-left group">
                    <div class="flex items-center justify-between text-xs mb-1">
                        <span class="text-slate-700 group-hover:text-slate-900">${esc(stage)}</span>
                        <span class="num-tabular text-slate-500">${n}</span>
                    </div>
                    <div class="h-2 bg-slate-100 rounded overflow-hidden"><div class="h-full rounded" style="width:${Math.round(n / max * 100)}%;background:var(--viz-series-1)"></div></div>
                </button>`).join('')}</div>`);
    }
    if (id === 'upcoming') {
        const items = d.upcomingTasks || [];
        return dashPanel('Coming up', 'Scheduled for the next 7 days',
            items.length ? items.map(t => taskLine(t, 'future')).join('')
                         : '<p class="text-xs text-slate-400 py-6 text-center">Nothing scheduled in the next week.</p>',
            `<button onclick="switchView('calendar')" class="text-[11px] font-semibold text-slate-600">Calendar</button>`);
    }
    if (id === 'activity') {
        const feed = d.recentActivity || [];
        return dashPanel('Recent activity', 'From the audit ledger',
            feed.length ? feed.map(a => `
                <div class="flex items-center justify-between gap-3 py-1.5 border-b border-slate-100 last:border-0 text-xs">
                    <span class="text-slate-700 truncate">${esc(a.description)}</span>
                    <span class="text-[10px] text-slate-400 font-mono whitespace-nowrap">${esc(a.actor || '')} · ${esc(a.time || '')}</span>
                </div>`).join('')
                : '<p class="text-xs text-slate-400 py-6 text-center">No activity recorded yet.</p>');
    }
    return '';
}

function filterLeadsByStage(stage) {
    switchView('leads');
    setTimeout(() => {
        const select = document.getElementById('leads-status-filter');
        if (select) { select.value = stage; loadLeads(); }
    }, 200);
}

// Grouped bars: two series, one shared count axis. Colours are the validated
// categorical slots 1 and 2; identity is carried by a legend AND direct labels.
function drawWorkTrend(trend) {
    const host = document.getElementById('work-trend');
    if (!host || !trend.length) return;
    const max = Math.max(1, ...trend.map(d => Math.max(d.due, d.completed)));
    const H = 120;
    host.innerHTML = `
        <div class="viz-legend">
            <span><i style="background:var(--viz-series-1)"></i>Scheduled</span>
            <span><i style="background:var(--viz-series-2)"></i>Completed</span>
        </div>
        <div class="viz-bars" role="img" aria-label="Tasks scheduled versus completed over the last seven days">
            ${trend.map(d => `
                <div class="viz-day">
                    <div class="viz-pair" style="height:${H}px">
                        <div class="viz-bar" style="height:${Math.round(d.due / max * H)}px;background:var(--viz-series-1)" title="${d.due} scheduled on ${d.label}"><span>${d.due || ''}</span></div>
                        <div class="viz-bar" style="height:${Math.round(d.completed / max * H)}px;background:var(--viz-series-2)" title="${d.completed} completed on ${d.label}"><span>${d.completed || ''}</span></div>
                    </div>
                    <span class="viz-day-label">${esc(d.label)}</span>
                </div>`).join('')}
        </div>`;
}

async function openDashboardCustomiser() {
    const layout = dashboardLayout || await apiJson('/api/dashboard/layout');
    const hidden = new Set(layout.hidden || []);
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = 'Customise dashboard';
    const byId = Object.fromEntries(layout.panels.map(p => [p.id, p]));
    form.innerHTML = `
        <p class="text-xs text-slate-500">Choose which panels appear and in what order. This is yours alone — it does not change anyone else's dashboard.</p>
        <div id="panel-list" class="space-y-2">
            ${layout.order.map((id, i) => `
                <div class="panel-row" data-panel="${id}">
                    <label class="flex items-start gap-2 min-w-0">
                        <input type="checkbox" ${hidden.has(id) ? '' : 'checked'} class="mt-0.5 rounded">
                        <span class="min-w-0"><span class="block text-xs font-medium text-slate-800">${esc(byId[id]?.label || id)}</span>
                        <span class="block text-[11px] text-slate-500">${esc(byId[id]?.description || '')}</span></span>
                    </label>
                    <span class="flex gap-1 shrink-0">
                        <button type="button" onclick="movePanel('${id}',-1)" class="rule-move">↑</button>
                        <button type="button" onclick="movePanel('${id}',1)" class="rule-move">↓</button>
                    </span>
                </div>`).join('')}
        </div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-between gap-2">
            <button type="button" onclick="resetDashboardLayout()" class="text-xs font-semibold text-slate-600">Reset to default</button>
            <div class="flex gap-2">
                <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
                <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save layout</button>
            </div>
        </div>`;
    form.onsubmit = async e => {
        e.preventDefault();
        const rows = [...document.querySelectorAll('#panel-list .panel-row')];
        await apiJson('/api/dashboard/layout', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order: rows.map(r => r.dataset.panel),
                                   hidden: rows.filter(r => !r.querySelector('input').checked).map(r => r.dataset.panel) }) });
        closeInsuranceForm(); showToast('Dashboard updated'); loadDashboard();
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

function movePanel(id, delta) {
    const list = document.getElementById('panel-list');
    const row = list.querySelector(`[data-panel="${id}"]`);
    const rows = [...list.children];
    const at = rows.indexOf(row);
    const to = at + delta;
    if (to < 0 || to >= rows.length) return;
    delta < 0 ? list.insertBefore(row, rows[to]) : list.insertBefore(rows[to], row);
}

async function resetDashboardLayout() {
    await apiJson('/api/dashboard/layout', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order: dashboardLayout.panels.map(p => p.id), hidden: [] }) });
    closeInsuranceForm(); showToast('Dashboard reset'); loadDashboard();
}

async function loadDeals() {
    const search = document.getElementById('deals-search')?.value.trim() || '';
    try {
        const res = await fetch(`/api/deals?search=${encodeURIComponent(search)}`);
        const deals = await res.json(); window.crmDeals = deals;
        const tbody = document.getElementById('deals-table-body');
        if (!deals.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center py-12 text-slate-400 text-xs">No active pipeline deals</td></tr>';
            return;
        }
        tbody.innerHTML = deals.map(d => `
            <tr class="hover:bg-slate-50 text-xs">
                <td class="px-4 py-2.5 border-r border-slateBorder font-semibold text-slate-900">${esc(d.organization)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-700">${esc(d.dealName || 'Commercial Policy')}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono font-semibold text-slate-900 num-tabular">${esc(d.annualRevenue)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder">
                    <span class="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-800 border border-slate-200">${esc(d.status)}</span>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-700">${esc(d.assignedTo)}</td>
                <td><button onclick="editDeal('${d.id}')" class="text-[11px] font-semibold">Edit</button></td>
            </tr>
        `).join('');
    } catch (e) { console.error(e); }
}

async function loadContacts() {
    try {
        const res = await fetch('/api/contacts');
        const contacts = await res.json(); window.crmContacts = contacts;
        const tbody = document.getElementById('contacts-table-body');
        tbody.innerHTML = contacts.map(c => `
            <tr class="hover:bg-slate-50 text-xs">
                <td class="px-4 py-2.5 border-r border-slateBorder font-semibold text-slate-900">${esc(c.name)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono text-slate-600">${esc(c.email)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono text-slate-700">${esc(c.phone)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-800">${esc(c.organization)} (${esc(c.designation)})</td>
                <td><button onclick="editContact('${c.id}')" class="text-[11px] font-semibold">Edit</button></td>
            </tr>
        `).join('');
    } catch (e) { console.error(e); }
}

async function loadOrganizations() {
    try {
        const res = await fetch('/api/organizations');
        const orgs = await res.json(); window.crmOrganizations = orgs;
        const tbody = document.getElementById('orgs-table-body');
        tbody.innerHTML = orgs.map(o => `
            <tr class="hover:bg-slate-50 text-xs">
                <td class="px-4 py-2.5 border-r border-slateBorder font-semibold text-slate-900">${esc(o.name)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono text-slate-500">${esc(o.website)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-700">${esc(o.industry)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono font-semibold text-slate-900 num-tabular">${esc(o.annualRevenue)}</td>
                <td><button onclick="editOrganization('${o.id}')" class="text-[11px] font-semibold">Edit</button></td>
            </tr>
        `).join('');
    } catch (e) { console.error(e); }
}

function editDeal(id) {
    const d=(window.crmDeals||[]).find(x=>x.id===id); if(!d)return;
    openInsuranceForm('Edit pipeline deal',[['dealName','Deal name','text',true],['organization','Organization','text',true],['annualRevenue','Expected premium / value','text',false],['status','Stage','select:New|Contacted|Risk / Underwriting|Quotation Sent|Won|Lost',true],['assignedTo','Owner',ownerFieldOptions(),true],['expectedCloseDate','Expected close','date',false]],v=>apiJson(`/api/deals/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}),d);
}

function editContact(id) {
    const c=(window.crmContacts||[]).find(x=>x.id===id); if(!c)return;
    openInsuranceForm('Edit contact',[['name','Name','text',true],['email','Email','email',false],['phone','Phone','text',true],['organization','Organization','text',false],['designation','Designation','text',false],['status','Status','select:Active|Inactive',true],['isPrimary','Primary contact','checkbox',false],['isDecisionMaker','Decision maker','checkbox',false]],v=>apiJson(`/api/contacts/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}),c);
}

function editOrganization(id) {
    const o=(window.crmOrganizations||[]).find(x=>x.id===id); if(!o)return;
    openInsuranceForm('Edit organization',[['name','Organization name','text',true],['website','Website','text',false],['industry','Industry','text',false],['annualRevenue','Annual revenue','text',false],['territory','Territory','text',false],['noOfEmployees','Employees','text',false],['gstNumber','GST number','text',false],['address','Address','textarea',false]],v=>apiJson(`/api/organizations/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}),o);
}

async function loadCustomers() {
    try {
        const search=document.getElementById('customers-search')?.value||''; const customers=await apiJson(`/api/customers?search=${encodeURIComponent(search)}`); window.crmCustomers=customers;
        const policies=await apiJson('/api/policies'); const body=document.getElementById('customers-table-body');
        body.innerHTML=customers.length?customers.map(c=>`<tr><td><div class="font-semibold">${esc(c.name)}</div><div class="text-[11px] text-slate-500">${esc(c.id)}</div></td><td>${esc(c.organization||'Individual')}</td><td><div>${esc(c.email||'—')}</div><div class="text-[11px]">${esc(c.mobile||'')}</div></td><td>${esc(c.status||'Active')}</td><td>${policies.filter(p=>p.customerId===c.id).length}</td><td><div class="flex gap-2"><button onclick="openCustomer360('${c.id}')" class="text-[11px] font-semibold">360°</button><button onclick="editCustomer('${c.id}')" class="text-[11px] font-semibold">Edit</button></div></td></tr>`).join(''):'<tr><td colspan="6" class="text-center py-12"><div class="font-semibold text-slate-700">No converted customers yet</div><div class="text-xs text-slate-500 mt-1">A customer is created when a lead is won and converted into a policy.</div><button onclick="startCustomerConversion()" class="mt-3 px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Open leads to convert</button></td></tr>';
    } catch(e){showToast(e.message)}
}

function editCustomer(id) {
    const c=(window.crmCustomers||[]).find(x=>x.id===id); if(!c)return;
    openInsuranceForm('Edit customer profile',[['name','Customer name','text',true],['organization','Organization','text',false],['email','Email','email',false],['mobile','Mobile','text',false],['status','Status','select:Active|Inactive',true],['assignedTo','Account owner',ownerFieldOptions(),false],['gstNumber','GST number','text',false],['address','Address','textarea',false]],v=>apiJson(`/api/customers/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}),c);
}

function createCustomer() {
    openInsuranceForm('New customer', [['name','Customer name','text',true],['organization','Organization','text',false],['email','Email','email',false],['mobile','Mobile','text',false],['assignedTo','Account owner',ownerFieldOptions(),false],['gstNumber','GST number','text',false],['address','Address','textarea',false]],
        values => apiJson('/api/customers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)}));
}

async function openCustomer360(id) {
    try { const c=await apiJson(`/api/customers/${id}`); const root=document.getElementById('customer-360'); root.classList.remove('hidden');
        const activity=[...(c.auditHistory||[]).map(x=>({at:x.createdAt,label:x.action,detail:x.actor})),...(c.notes||[]).map(x=>({at:x.createdAt,label:x.title,detail:x.author})),...(c.communications||[]).map(x=>({at:x.createdAt,label:`${x.channel} · ${x.status}`,detail:x.subject||x.content}))].sort((a,b)=>String(b.at).localeCompare(String(a.at))).slice(0,12);
        root.innerHTML=`<div class="flex flex-wrap justify-between gap-3"><div><h2 class="font-semibold text-base">${esc(c.name)}</h2><p class="text-xs text-slate-500">${esc(c.organization||'Individual')} · ${esc(c.email||'No email')} · ${esc(c.mobile||'No mobile')}</p></div><div class="flex gap-2"><button onclick="openCalendarEventForm('Customer','${c.id}')" class="px-2.5 py-1 border rounded text-xs font-semibold">Schedule</button><button onclick="editCustomer('${c.id}')" class="px-2.5 py-1 border rounded text-xs font-semibold">Edit profile</button><button onclick="switchView('policies')" class="px-2.5 py-1 border rounded text-xs font-semibold">Policies</button><button aria-label="Close customer profile" onclick="document.getElementById('customer-360').classList.add('hidden')">✕</button></div></div>
        <div class="grid grid-cols-2 md:grid-cols-5 gap-2 mt-4">${[['Contacts',c.contacts.length],['Policies',c.policies.length],['Renewals',c.renewals.length],['Open tasks',c.tasks.filter(x=>x.status!=='Completed').length],['Documents',c.documents.filter(x=>x.status!=='Archived').length]].map(x=>`<div class="bg-slate-50 border rounded p-2"><div class="text-[10px] uppercase text-slate-500">${x[0]}</div><strong class="text-lg">${x[1]}</strong></div>`).join('')}</div>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-3"><section class="border rounded p-3"><h3 class="text-xs font-bold uppercase text-slate-500">Contacts</h3>${c.contacts.map(x=>`<div class="text-xs mt-2"><strong>${esc(x.name)}</strong><div class="text-slate-500">${esc(x.designation||'')} · ${esc(x.phone||x.email||'')}</div></div>`).join('')||'<p class="text-xs text-slate-400 mt-2">None linked</p>'}</section><section class="border rounded p-3"><h3 class="text-xs font-bold uppercase text-slate-500">Policies & renewals</h3>${c.policies.map(x=>`<button onclick="switchView('policies')" class="block text-left text-xs mt-2"><strong>${esc(x.policyNumber||'Draft')}</strong><span class="block text-slate-500">${esc(x.policyType)} · ${esc(x.issuanceStatus)}</span></button>`).join('')||'<p class="text-xs text-slate-400 mt-2">No policies</p>'}</section><section class="border rounded p-3"><h3 class="text-xs font-bold uppercase text-slate-500">Pipeline & service</h3><p class="text-xs mt-2">${c.deals.length} deal(s) · ${c.quotations.length} quote(s)</p><p class="text-xs text-slate-500 mt-1">${c.renewals.filter(x=>!['Renewed','Lost','Lapsed'].includes(x.stage)).length} open renewal(s)</p></section></div>
        <section class="border rounded p-3 mt-3"><h3 class="text-xs font-bold uppercase text-slate-500">Upcoming meetings & follow-ups</h3>${(c.calendarEvents||[]).filter(x=>!['Completed','Archived','Cancelled'].includes(x.status)).sort((a,b)=>`${a.date}${a.time}`.localeCompare(`${b.date}${b.time}`)).map(x=>`<div class="flex justify-between gap-3 border-t first:border-0 py-2 text-xs"><div><strong>${esc(x.title)}</strong><div class="text-slate-500">${esc(x.type)} · ${esc(x.assignedTo||'Unassigned')}</div></div><time class="text-[11px] text-slate-500 shrink-0">${esc(x.date)} ${esc(x.time||'')}</time></div>`).join('')||'<p class="text-xs text-slate-400 mt-2">Nothing scheduled.</p>'}</section>
        <section class="border rounded p-3 mt-3"><h3 class="text-xs font-bold uppercase text-slate-500">Chronological activity</h3>${activity.map(x=>`<div class="flex justify-between gap-3 border-t first:border-0 py-2 text-xs"><div><strong>${esc(x.label)}</strong><div class="text-slate-500 truncate max-w-xl">${esc(x.detail||'')}</div></div><time class="text-[11px] text-slate-400 shrink-0">${esc((x.at||'').slice(0,10))}</time></div>`).join('')||'<p class="text-xs text-slate-400 mt-2">No activity yet.</p>'}</section>`;
    } catch(e){showToast(e.message)}
}

async function loadNotifications(){
    try { const items=await apiJson('/api/notifications'); const root=document.getElementById('notifications-list'); root.innerHTML=items.length?items.map(n=>`<div class="p-4 flex flex-wrap items-start justify-between gap-3 ${n.read?'opacity-60':''}"><div><div class="font-semibold">${esc(n.title)}</div><div class="text-xs text-slate-600 mt-1">${esc(n.message)}</div><div class="text-[11px] text-slate-400 mt-1">${esc(n.severity)} · ${esc(n.assignedTo||'Unassigned')} ${n.snoozedUntil?'· Snoozed until '+esc(n.snoozedUntil):''}</div></div><div class="flex gap-2"><button onclick="updateNotification('${n.id}',{read:${!n.read}})" class="text-xs font-semibold">${n.read?'Unread':'Read'}</button><button onclick="snoozeNotification('${n.id}')" class="text-xs font-semibold">Snooze</button><button onclick="assignNotification('${n.id}')" class="text-xs font-semibold">Assign</button></div></div>`).join(''):'<div class="p-10 text-center text-xs text-slate-400">No notifications need attention.</div>';}catch(e){showToast(e.message)}
}
async function updateNotification(id,values){await apiJson(`/api/notifications/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});await loadNotifications();refreshNotificationBadge()}
function snoozeNotification(id){openInsuranceForm('Snooze notification',[['snoozedUntil','Snooze until','date',true]],v=>updateNotification(id,v))}
function assignNotification(id){openInsuranceForm('Assign notification',[['assignedTo','Owner',ownerFieldOptions(),true]],v=>updateNotification(id,v))}
async function runNotificationEscalations(){const r=await apiJson('/api/notifications/run-escalations',{method:'POST'});showToast(`${r.createdCount} new escalation(s)`);await loadNotifications();refreshNotificationBadge()}

// ═══════════════════════════════════════════════════════════════════
// 8. SETTINGS & SPREADSHEET IMPORT
// ═══════════════════════════════════════════════════════════════════
function openSettingsModal() {
    document.getElementById('settings-modal')?.classList.remove('hidden');
    switchSettingTab('import');
}

function closeSettingsModal() {
    document.getElementById('settings-modal')?.classList.add('hidden');
}

// A tab clicked while another is still loading must win — otherwise the slower
// render lands after it and the user is left looking at the wrong pane.
let settingTabToken = 0;

async function switchSettingTab(tab) {
    const pane = document.getElementById('setting-pane-content');
    const token = ++settingTabToken;
    const stillCurrent = () => token === settingTabToken;
    document.querySelectorAll('.setting-tab-btn').forEach(button => {
        const active = button.dataset.settingTab === tab;
        button.classList.toggle('bg-white', active);
        button.classList.toggle('text-slate-900', active);
        button.classList.toggle('shadow-xs', active);
        button.classList.toggle('text-slate-600', !active);
    });
    if (tab === 'import') {
        renderImportStep1(stillCurrent);
    } else if (tab === 'profile') {
        const [me, users] = await Promise.all([apiJson('/api/profile'), apiJson('/api/users')]);
        if (!stillCurrent()) return;
        pane.innerHTML = `
            <div class="space-y-4">
                <div>
                    <h3 class="font-semibold text-slate-900 text-sm">My profile</h3>
                    <p class="text-xs text-slate-500 mt-0.5">Your details as they appear on records you own and on messages you send.</p>
                </div>
                <div class="flex items-center gap-3 p-3 border border-slateBorder rounded bg-slate-50">
                    <div class="w-11 h-11 rounded-full bg-slate-900 text-white flex items-center justify-center font-semibold text-sm">${esc(getInitials(me.name))}</div>
                    <div class="min-w-0">
                        <div class="font-semibold text-slate-900 text-sm">${esc(me.name)}</div>
                        <div class="text-[11px] text-slate-500">${esc(me.role || '')}${me.managerName ? ` · reports to ${esc(me.managerName)}` : ''}</div>
                    </div>
                    <div class="ml-auto grid grid-cols-3 gap-2 text-center shrink-0">
                        ${[['openLeads', 'Open leads'], ['wonLeads', 'Won'], ['openTasks', 'Open tasks']].map(([k, l]) =>
                            `<div class="px-2"><strong class="block text-base font-semibold num-tabular">${me.stats[k]}</strong><span class="text-[10px] text-slate-400 uppercase tracking-wider">${l}</span></div>`).join('')}
                    </div>
                </div>
                <form onsubmit="saveProfile(event)" class="space-y-3">
                    <div class="grid grid-cols-2 gap-3">
                        <label class="block text-xs font-medium text-slate-700">Full name<input id="prof-name" class="corp-input mt-1" value="${esc(me.name)}" required></label>
                        <label class="block text-xs font-medium text-slate-700">Email<input id="prof-email" type="email" class="corp-input mt-1" value="${esc(me.email || '')}"></label>
                        <label class="block text-xs font-medium text-slate-700">Phone<input id="prof-phone" class="corp-input mt-1" value="${esc(me.phone || '')}"></label>
                        <label class="block text-xs font-medium text-slate-700">Job title<input id="prof-role" class="corp-input mt-1" value="${esc(me.role || '')}"></label>
                    </div>
                    <p class="text-[11px] text-slate-500">Renaming yourself moves every lead, task and policy you own to the new name.</p>
                    <button class="px-4 py-2 bg-slate-900 text-white rounded text-xs font-semibold">Save profile</button>
                </form>
                ${me.directReports.length ? `<div><h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Reports to me</h4>
                    <div class="space-y-1">${me.directReports.map(r => `<div class="text-xs border border-slateBorder rounded px-2.5 py-1.5">${esc(r.name)} <span class="text-slate-400">· ${esc(r.role || '')}</span></div>`).join('')}</div></div>` : ''}
                <div class="pt-3 border-t border-slateBorder">
                    <label class="block text-xs font-medium text-slate-700">Viewing the CRM as
                        <span class="block text-[11px] font-normal text-slate-500 mb-1">Until individual sign-ins are rolled out to your team, this decides whose name new work is recorded under.</span>
                        <select class="corp-input" onchange="switchActiveUser(this.value)">
                            ${users.map(u => `<option value="${esc(u.id)}" ${u.id === me.id ? 'selected' : ''}>${esc(u.name)}${u.status === 'Inactive' ? ' (inactive)' : ''}</option>`).join('')}
                        </select>
                    </label>
                </div>
            </div>`;
    } else if (tab === 'users') {
        const [users, leads] = await Promise.all([apiJson('/api/users'), apiJson('/api/leads')]);
        if (!stillCurrent()) return;
        const load = name => leads.filter(l => l.assignedTo === name && !['Won', 'Lost'].includes(l.status)).length;
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div>
                        <h3 class="font-semibold text-slate-900 text-sm">Users</h3>
                        <p class="text-xs text-slate-500 mt-0.5">Everyone who works the pipeline. Owners across the CRM come from this list.</p>
                    </div>
                    <button onclick="addUser()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold shrink-0">Add user</button>
                </div>
                <div class="space-y-2">
                    ${users.map(u => `
                        <div class="flex items-center justify-between gap-3 border border-slateBorder rounded p-3">
                            <div class="flex items-center gap-2.5 min-w-0">
                                <div class="w-8 h-8 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center text-[10px] font-semibold shrink-0">${esc(getInitials(u.name))}</div>
                                <div class="min-w-0">
                                    <div class="text-xs font-semibold text-slate-900 truncate">${esc(u.name)} ${u.status === 'Inactive' ? '<span class="text-[10px] text-slate-400">(inactive)</span>' : ''}</div>
                                    <div class="text-[11px] text-slate-500 truncate">${esc(u.role || '')}${u.email ? ` · ${esc(u.email)}` : ''} · ${load(u.name)} open leads</div>
                                </div>
                            </div>
                            <div class="flex items-center gap-2 shrink-0 text-[11px] font-semibold">
                                <button onclick="editUser('${u.id}')" class="text-slate-700">Edit</button>
                                ${u.status === 'Inactive'
                                    ? `<button onclick="reactivateUser('${u.id}')" class="text-slate-700">Reactivate</button>`
                                    : `<button onclick="deactivateUser('${u.id}','${esc(u.name)}')" class="text-rose-600">Deactivate</button>`}
                            </div>
                        </div>`).join('')}
                </div>
            </div>`;
    } else if (tab === 'hierarchy') {
        const [data, users] = await Promise.all([apiJson('/api/users/hierarchy'), apiJson('/api/users')]);
        if (!stillCurrent()) return;
        const node = (n, depth) => `
            <div class="hier-node" style="margin-left:${depth * 18}px">
                <div class="hier-card">
                    <div class="min-w-0">
                        <div class="text-xs font-semibold text-slate-900 truncate">${esc(n.name)}</div>
                        <div class="text-[11px] text-slate-500 truncate">${esc(n.role || '')}</div>
                    </div>
                    <div class="flex items-center gap-3 shrink-0">
                        <span class="text-[11px] text-slate-500 num-tabular" title="Their own book">${n.own.open} open</span>
                        ${n.reports.length ? `<span class="hier-team num-tabular" title="Including everyone reporting to them">team ${n.team.open}</span>` : ''}
                        <button onclick="setManager('${n.id}')" class="text-[11px] font-semibold text-slate-700">Move</button>
                    </div>
                </div>
                ${n.reports.map(r => node(r, depth + 1)).join('')}
            </div>`;
        pane.innerHTML = `
            <div class="space-y-4">
                <div>
                    <h3 class="font-semibold text-slate-900 text-sm">Sales hierarchy</h3>
                    <p class="text-xs text-slate-500 mt-0.5">Who reports to whom. Open-lead counts roll up, so a manager's figure includes their whole team.</p>
                </div>
                <div class="space-y-1.5">${data.tree.map(n => node(n, 0)).join('') || '<p class="text-xs text-slate-400">No active users.</p>'}</div>
                <p class="text-[11px] text-slate-500 border-t border-slateBorder pt-3">Use <strong>Move</strong> to place someone under a manager. Reporting loops are refused.</p>
            </div>`;
    } else if (tab === 'rules') {
        const [rules, opts] = await Promise.all([apiJson('/api/assignment-rules'), apiJson('/api/assignment-rules/options')]);
        if (!stillCurrent()) return;
        window.crmRuleOptions = opts;
        const methodLabel = m => (opts.methods.find(x => x.method === m) || {}).label || m;
        const readable = r => (r.conditions || []).length
            ? (r.conditions || []).map(c => {
                const f = (opts.fields.find(x => x.field === c.field) || {}).label || c.field;
                const o = (opts.operators.find(x => x.op === c.operator) || {}).label || c.operator;
                return `${f} ${o}${c.value ? ` “${c.value}”` : ''}`;
              }).join(' and ')
            : 'Every new enquiry';
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div>
                        <h3 class="font-semibold text-slate-900 text-sm">Assignment rules</h3>
                        <p class="text-xs text-slate-500 mt-0.5">Decide who new enquiries go to automatically. Rules are checked top to bottom and the first match wins — anything unmatched is balanced across the team as usual.</p>
                    </div>
                    <button onclick="editAssignmentRule()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold shrink-0">New rule</button>
                </div>
                <div class="space-y-2">
                    ${rules.map((r, i) => `
                        <div class="rule-card ${r.enabled === false ? 'is-off' : ''}">
                            <div class="flex items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <span class="rule-order">${i + 1}</span>
                                        <strong class="text-xs text-slate-900">${esc(r.name)}</strong>
                                        ${r.enabled === false ? '<span class="rule-pill">Off</span>' : ''}
                                        ${r.matchCount ? `<span class="rule-pill is-count">${r.matchCount} assigned</span>` : ''}
                                    </div>
                                    <p class="text-[11.5px] text-slate-600 mt-1.5 leading-relaxed">
                                        <span class="text-slate-400">When</span> ${esc(readable(r))}
                                        <span class="text-slate-400">→ give it to</span> ${esc((r.assignees || []).join(', '))}
                                        <span class="text-slate-400">(${esc(methodLabel(r.method).toLowerCase())})</span>
                                        ${r.createTask ? `<br><span class="text-slate-400">and raise a task:</span> ${esc(r.taskTitle || 'Follow up')} in ${r.taskDueInDays || 1} day(s)` : ''}
                                        ${(r.days || []).length ? `<br><span class="text-slate-400">only on:</span> ${esc((r.days || []).join(', '))}` : ''}
                                    </p>
                                </div>
                                <div class="flex flex-col items-end gap-1.5 shrink-0 text-[11px] font-semibold">
                                    <div class="flex gap-1">
                                        <button onclick="moveRule('${r.id}','up')" title="Higher priority" class="rule-move">↑</button>
                                        <button onclick="moveRule('${r.id}','down')" title="Lower priority" class="rule-move">↓</button>
                                    </div>
                                    <button onclick="toggleRule('${r.id}', ${r.enabled === false})" class="text-slate-700">${r.enabled === false ? 'Turn on' : 'Turn off'}</button>
                                    <button onclick="editAssignmentRule('${r.id}')" class="text-slate-700">Edit</button>
                                    <button onclick="deleteRule('${r.id}')" class="text-rose-600">Delete</button>
                                </div>
                            </div>
                        </div>`).join('') || `<div class="border border-dashed border-slate-300 rounded p-6 text-center">
                            <p class="text-xs text-slate-600">No rules yet — every enquiry is shared evenly across the team.</p>
                            <p class="text-[11px] text-slate-400 mt-1">A first rule might be: fleet enquiries go to your motor specialist.</p>
                        </div>`}
                </div>
                ${rules.length ? `<button onclick="testAssignmentRules()" class="text-[11px] font-semibold text-slate-700 underline">Test with an example enquiry</button>` : ''}
            </div>`;
    } else if (tab === 'team') {
        const [users, leads] = await Promise.all([apiJson('/api/users'), apiJson('/api/leads')]);
        if (!stillCurrent()) return;
        const active = users.filter(u => (u.status || 'Active') === 'Active' && u.role !== 'System Administrator');
        const openLeads = leads.filter(l => !['Won', 'Lost'].includes(l.status));
        const countFor = name => openLeads.filter(l => l.assignedTo === name).length;
        const most = Math.max(1, ...active.map(u => countFor(u.name)));
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div><h3 class="font-semibold text-slate-900 text-sm">Team access & allocation</h3>
                    <p class="text-xs text-slate-500 mt-0.5">Invite login users, control their role and balance inbound work.</p></div>
                    <button onclick="createTeamUser()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Add user</button>
                </div>
                <div class="border border-slateBorder rounded divide-y">${users.map(u=>`<div class="p-2.5 flex items-center justify-between gap-3"><div><strong class="text-xs">${esc(u.name)}</strong><div class="text-[11px] text-slate-500">${esc(u.email||'No login email')} · ${esc(u.role)} · ${esc(u.status||'Active')}</div></div>${u.status!=='Inactive'?`<button onclick="deactivateTeamUser('${u.id}')" class="text-[11px] font-semibold text-rose-700">Deactivate</button>`:''}</div>`).join('')}</div>
                <div class="p-3 bg-slate-50 border border-slateBorder rounded text-xs flex items-center justify-between">
                    <span>Status: <strong>Active (Round-Robin)</strong></span>
                    <span class="text-[11px] text-slate-500">Each new enquiry goes to whoever holds the fewest open leads</span>
                </div>
                <div>
                    <h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2">Current workload — ${active.length} broker${active.length === 1 ? '' : 's'} in rotation</h4>
                    <div class="space-y-2">
                        ${active.map(u => {
                            const n = countFor(u.name);
                            return `<div class="flex items-center gap-3 text-xs">
                                <span class="w-36 shrink-0 truncate text-slate-800 font-medium">${esc(u.name)}</span>
                                <div class="flex-1 h-2 bg-slate-100 rounded overflow-hidden"><div class="h-full bg-slate-800 rounded" style="width:${Math.round(n / most * 100)}%"></div></div>
                                <span class="w-20 text-right text-slate-500 num-tabular">${n} open</span>
                            </div>`;
                        }).join('') || '<p class="text-xs text-slate-400">No active brokers. Add team members to start balancing enquiries.</p>'}
                    </div>
                </div>
                <p class="text-[11px] text-slate-500 leading-relaxed border-t border-slateBorder pt-3">
                    Rotation uses everyone marked Active. To take someone out — on leave or left the firm — set them to Inactive and their open leads can be reassigned in bulk from the leads list.
                    Territory and product-based allocation rules are not built yet.
                </p>
            </div>`;
    } else if (tab === 'templates') {
        const [templates, channels] = await Promise.all([apiJson('/api/communication-templates?includeArchived=true'), apiJson('/api/channels')]);
        if (!stillCurrent()) return;
        window.crmCommunicationTemplates = templates;
        const liveChannels = channels.filter(c => c.status === 'Connected');
        const activeTemplates = templates.filter(t => t.status !== 'Archived');
        const archivedTemplates = templates.filter(t => t.status === 'Archived');
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div>
                        <h3 class="font-semibold text-slate-900 text-sm">Message templates</h3>
                        <p class="text-xs text-slate-500 mt-0.5">Reusable wording for renewal reminders, document requests and quote follow-ups — written once, then selected while sending from a client record.</p>
                    </div>
                    <button onclick="createTemplate()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold shrink-0">New template</button>
                </div>
                <div class="p-2.5 rounded border ${liveChannels.length ? 'bg-slate-50 border-slateBorder' : 'bg-amber-50 border-amber-200'} text-[11px] leading-relaxed">
                    ${liveChannels.length
                        ? `Templates are used by <strong>Send message</strong> on a client's record. Connected for sending: ${liveChannels.map(c => esc(c.providerLabel)).join(', ')}.`
                        : `Templates are ready to use, but nothing is connected to send them yet. Connect WhatsApp or your email in <strong>Lead Sources</strong> — until then, sending is recorded on the client's timeline without leaving the CRM.`}
                </div>
                <div class="space-y-2">
                    ${activeTemplates.map(t => `
                        <div class="border border-slateBorder rounded p-3 flex justify-between gap-3">
                            <div class="min-w-0">
                                <strong class="text-xs text-slate-900">${esc(t.name)}</strong>
                                <div class="text-[11px] text-slate-500">${esc(t.channel)}${t.subject ? ` · ${esc(t.subject)}` : ''}</div>
                                <p class="text-xs mt-1.5 text-slate-600">${esc(t.content)}</p>
                            </div>
                            <div class="flex items-center gap-3 shrink-0 self-start">
                                <button onclick="editCommunicationTemplate('${t.id}')" class="text-[11px] font-semibold text-slate-700">Edit</button>
                                <button onclick="archiveTemplate('${t.id}')" class="text-[11px] font-semibold text-slate-600">Archive</button>
                            </div>
                        </div>`).join('') || `<div class="border border-dashed border-slate-300 rounded p-6 text-center">
                            <p class="text-xs text-slate-500">No templates yet. A renewal reminder and a document chaser cover most day-to-day sending.</p>
                        </div>`}
                </div>
                <details class="border border-slateBorder rounded bg-slate-50">
                    <summary class="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-700">Archived templates (${archivedTemplates.length})</summary>
                    <div class="px-3 pb-3 space-y-2">
                        <p class="text-[11px] text-slate-500">Archived templates are kept for audit history and no longer appear in Send message. Restore one to reuse it, or permanently delete an unwanted test.</p>
                        ${archivedTemplates.map(t => `<div class="bg-white border border-slateBorder rounded p-2.5 flex items-start justify-between gap-3">
                            <div class="min-w-0"><strong class="text-xs text-slate-800">${esc(t.name)}</strong><div class="text-[11px] text-slate-500">${esc(t.channel)}</div></div>
                            <div class="flex items-center gap-3 shrink-0"><button onclick="restoreTemplate('${t.id}')" class="text-[11px] font-semibold text-slate-700">Restore</button><button onclick="deleteTemplatePermanently('${t.id}')" class="text-[11px] font-semibold text-rose-700">Delete permanently</button></div>
                        </div>`).join('') || '<p class="text-[11px] text-slate-400">No archived templates.</p>'}
                    </div>
                </details>
            </div>`;
    } else if (tab === 'watemplates') {
        const [templates, channels] = await Promise.all([apiJson('/api/whatsapp-templates'), apiJson('/api/channels')]);
        if (!stillCurrent()) return;
        const wa = channels.find(c => c.provider === 'whatsapp');
        const ready = wa && wa.credentials?.wabaId && wa.canSend;
        const pill = s => `<span class="wa-status ${{'Approved':'is-approved','Pending review':'is-pending','Rejected':'is-rejected','Draft':'is-draft'}[s] || 'is-draft'}">${esc(s)}</span>`;
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div>
                        <h3 class="font-semibold text-slate-900 text-sm">WhatsApp templates</h3>
                        <p class="text-xs text-slate-500 mt-0.5">WhatsApp only lets you message a client out of the blue using wording Meta has approved in advance. Write it here, submit it, and use it once approved — usually within a few hours.</p>
                    </div>
                    <div class="flex gap-2 shrink-0">
                        ${ready ? `<button onclick="syncWhatsAppTemplates()" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold">Refresh status</button>` : ''}
                        <button onclick="createWhatsAppTemplate()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">New template</button>
                    </div>
                </div>
                ${!wa ? `<div class="p-2.5 rounded border bg-amber-50 border-amber-200 text-[11px] leading-relaxed">Connect <strong>WhatsApp Business</strong> in Lead Sources to submit templates. You can still write them here as drafts.</div>`
                  : !ready ? `<div class="p-2.5 rounded border bg-amber-50 border-amber-200 text-[11px] leading-relaxed">Add your <strong>WhatsApp Business Account ID</strong> and access token under Sending setup on the WhatsApp source — Meta needs both to register templates.</div>` : ''}
                <div class="space-y-2">
                    ${templates.map(t => `
                        <div class="border border-slateBorder rounded p-3 space-y-2">
                            <div class="flex items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <strong class="text-xs text-slate-900">${esc(t.name)}</strong>${pill(t.status)}
                                        <span class="text-[10px] text-slate-400">${esc(t.category)} · ${esc(t.language)}</span>
                                    </div>
                                    <p class="text-xs mt-1.5 text-slate-600 whitespace-pre-wrap">${esc(t.body)}</p>
                                    ${t.rejectedReason ? `<p class="text-[11px] text-rose-600 mt-1">Meta's reason: ${esc(t.rejectedReason)}</p>` : ''}
                                    ${t.statusNote ? `<p class="text-[11px] text-amber-700 mt-1">${esc(t.statusNote)}</p>` : ''}
                                </div>
                                <div class="flex flex-col items-end gap-1.5 shrink-0 text-[11px] font-semibold">
                                    ${['Draft', 'Rejected'].includes(t.status) ? `<button onclick="submitWhatsAppTemplate('${t.id}')" class="text-slate-700">Submit to Meta</button>` : ''}
                                    <button onclick="deleteWhatsAppTemplate('${t.id}')" class="text-rose-600">Delete</button>
                                </div>
                            </div>
                        </div>`).join('') || `<div class="border border-dashed border-slate-300 rounded p-6 text-center">
                            <p class="text-xs text-slate-500">No WhatsApp templates yet. A renewal reminder is the one most brokers need first.</p>
                        </div>`}
                </div>
            </div>`;
    } else if (tab === 'configuration') {
        const settings = await apiJson('/api/settings');
        if (!stillCurrent()) return;
        const c = settings.crm || {};
        pane.innerHTML = `<form onsubmit="saveCrmConfiguration(event)" class="space-y-4">
            <div>
                <h3 class="font-semibold text-slate-900 text-sm">CRM configuration</h3>
                <p class="text-xs text-slate-500 mt-0.5">The dropdown choices your team sees while working. Change them here to match how your brokerage actually sells — one value per line.</p>
            </div>
            <label class="block text-xs font-medium text-slate-700">Pipeline stages
                <span class="block text-[11px] font-normal text-slate-500 mb-1">The columns on the Kanban board and the stages in the transition modal.</span>
                <textarea id="config-stages" rows="4" class="corp-input">${esc((c.leadStages || []).join('\n'))}</textarea>
            </label>
            <label class="block text-xs font-medium text-slate-700">Policy categories
                <span class="block text-[11px] font-normal text-slate-500 mb-1">Offered when adding a lead or issuing a policy — your product lines.</span>
                <textarea id="config-products" rows="4" class="corp-input">${esc((c.insuranceProducts || []).join('\n'))}</textarea>
            </label>
            <label class="block text-xs font-medium text-slate-700">Insurers you place business with
                <span class="block text-[11px] font-normal text-slate-500 mb-1">Offered when logging comparative quotations on a renewal.</span>
                <textarea id="config-insurers" rows="3" class="corp-input">${esc((c.insurers || []).join('\n'))}</textarea>
            </label>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label class="block text-xs font-medium text-slate-700">Company timezone
                    <select id="config-timezone" class="corp-input mt-1"><option ${c.companyTimezone==='Asia/Kolkata'?'selected':''}>Asia/Kolkata</option><option ${c.companyTimezone==='UTC'?'selected':''}>UTC</option><option ${c.companyTimezone==='Asia/Dubai'?'selected':''}>Asia/Dubai</option><option ${c.companyTimezone==='Europe/London'?'selected':''}>Europe/London</option><option ${c.companyTimezone==='America/New_York'?'selected':''}>America/New_York</option></select>
                </label>
                <label class="block text-xs font-medium text-slate-700">Notify before appointments
                    <select id="config-reminder-minutes" class="corp-input mt-1"><option value="60" ${Number(c.upcomingReminderMinutes)===60?'selected':''}>1 hour</option><option value="240" ${Number(c.upcomingReminderMinutes)===240?'selected':''}>4 hours</option><option value="1440" ${Number(c.upcomingReminderMinutes||1440)===1440?'selected':''}>1 day</option><option value="2880" ${Number(c.upcomingReminderMinutes)===2880?'selected':''}>2 days</option></select>
                </label>
            </div>
            <button class="px-4 py-2 bg-slate-900 text-white rounded text-xs font-semibold">Save configuration</button>
        </form>`;
    } else if (tab === 'archive') {
        const [archived,records]=await Promise.all([apiJson('/api/archived-leads'),apiJson('/api/archived-records')]);
        pane.innerHTML=`<div class="space-y-3"><h3 class="font-semibold text-sm">Archive & restore</h3><p class="text-xs text-slate-500">Restore records without losing their identity. Deleted-lead notes remain retained separately.</p>${archived.map(l=>`<div class="border rounded p-3 flex justify-between"><div><strong>${esc(l.name)}</strong><div class="text-xs text-slate-500">Lead · ${esc(l.organization)} · ${esc(l.archivedReason||'Archived')}</div></div><button onclick="restoreLead('${l.id}')" class="text-xs font-semibold">Restore</button></div>`).join('')}${records.map(x=>`<div class="border rounded p-3 flex justify-between"><div><strong>${esc(x.record?.name||x.record?.customerName||x.record?.policyNumber||x.record?.dealName||x.archiveId)}</strong><div class="text-xs text-slate-500">${esc(x.sourceCollection)} · ${esc(x.archivedAt)}</div></div><button onclick="restoreOperationalRecord('${x.archiveId}')" class="text-xs font-semibold">Restore</button></div>`).join('')||(!archived.length?'<p class="text-xs text-slate-400">No archived records.</p>':'')}</div>`;
    } else if (tab === 'reports') {
        const [report,backups]=await Promise.all([apiJson('/api/reports/operations'),apiJson('/api/backups')]);
        pane.innerHTML=`<div class="space-y-4"><div class="flex justify-between"><div><h3 class="font-semibold text-sm">Operations report</h3><p class="text-xs text-slate-500">Conversion, retention, employee workload and overdue work.</p></div><button onclick="createSystemBackup()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs">Create backup</button></div><div class="grid grid-cols-3 gap-3"><div class="border rounded p-3"><small>Conversion</small><strong class="block text-xl">${report.conversionRate}%</strong></div><div class="border rounded p-3"><small>Renewal retention</small><strong class="block text-xl">${report.renewal.retentionRate}%</strong></div><div class="border rounded p-3"><small>Overdue tasks</small><strong class="block text-xl">${report.overdueTasks}</strong></div></div><div><strong class="text-xs">Employee activity</strong>${Object.entries(report.employeeActivity).map(([name,x])=>`<div class="text-xs border-b py-2 flex justify-between"><span>${esc(name)}</span><span>${x.leads} leads · ${x.won} won · ${x.openTasks} open tasks</span></div>`).join('')}</div><div><strong class="text-xs">Available backups</strong>${backups.map(b=>`<div class="text-xs py-2">${esc(b.name)} · ${Math.ceil(b.size/1024)} KB</div>`).join('')||'<p class="text-xs text-slate-400 mt-2">No backups created.</p>'}</div></div>`;
    }
}

// ── Assignment rules ────────────────────────────────────────────────
// Written as one plain sentence — "When X, give it to Y" — rather than the
// condition-builder grid this kind of feature usually turns into.
let ruleDraft = { conditions: [], assignees: [], days: [] };

async function editAssignmentRule(id) {
    const opts = window.crmRuleOptions || await apiJson('/api/assignment-rules/options');
    window.crmRuleOptions = opts;
    const existing = id ? (await apiJson('/api/assignment-rules')).find(r => r.id === id) : null;
    ruleDraft = {
        id, name: existing?.name || '', conditions: JSON.parse(JSON.stringify(existing?.conditions || [])),
        assignees: [...(existing?.assignees || [])], method: existing?.method || 'least_busy',
        days: [...(existing?.days || [])], createTask: existing?.createTask || false,
        taskTitle: existing?.taskTitle || '', taskDueInDays: existing?.taskDueInDays || 1
    };
    renderRuleForm();
}

function renderRuleForm() {
    const opts = window.crmRuleOptions;
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = ruleDraft.id ? 'Edit rule' : 'New assignment rule';
    const d = ruleDraft;

    form.innerHTML = `
        <label class="block">
            <span class="block text-xs font-medium text-slate-700 mb-1">Name this rule</span>
            <input id="rule-name" class="corp-input" value="${esc(d.name)}" placeholder="Fleet enquiries to the motor team" required>
        </label>

        <div class="rule-sentence">
            <div class="rule-line"><span class="rule-word">When</span>
                <span class="text-[11.5px] text-slate-500">${d.conditions.length ? 'an enquiry matches all of these' : 'any new enquiry arrives'}</span>
            </div>
            <div class="space-y-2 mt-2">
                ${d.conditions.map((c, i) => `
                    <div class="rule-cond">
                        <select class="corp-input text-xs py-1" onchange="updateCondition(${i},'field',this.value)">
                            ${opts.fields.map(f => `<option value="${f.field}" ${c.field === f.field ? 'selected' : ''}>${esc(f.label)}</option>`).join('')}
                        </select>
                        <select class="corp-input text-xs py-1" onchange="updateCondition(${i},'operator',this.value)">
                            ${opts.operators.map(o => `<option value="${o.op}" ${c.operator === o.op ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}
                        </select>
                        <input class="corp-input text-xs py-1" value="${esc(c.value || '')}" placeholder="value"
                               ${c.operator === 'is_empty' ? 'disabled' : ''} onchange="updateCondition(${i},'value',this.value)">
                        <button type="button" onclick="removeCondition(${i})" class="rule-x" title="Remove">✕</button>
                    </div>`).join('')}
            </div>
            <button type="button" onclick="addCondition()" class="rule-add">+ Add a condition</button>

            <div class="rule-line mt-3"><span class="rule-word">Give it to</span></div>
            <div class="rule-people">
                ${opts.people.map(p => `
                    <label class="rule-person ${d.assignees.includes(p) ? 'is-on' : ''}">
                        <input type="checkbox" ${d.assignees.includes(p) ? 'checked' : ''} onchange="togglePerson('${esc(p)}')"> ${esc(p)}
                    </label>`).join('')}
            </div>
            <div class="rule-line mt-3"><span class="rule-word">Choosing</span>
                <select id="rule-method" class="corp-input text-xs py-1 max-w-[280px]">
                    ${opts.methods.map(m => `<option value="${m.method}" ${d.method === m.method ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}
                </select>
            </div>
        </div>

        <details class="advanced-block">
            <summary>Optional — follow-up task and active days</summary>
            <div class="space-y-3 pt-3">
                <label class="flex items-center gap-2 text-xs text-slate-700">
                    <input type="checkbox" id="rule-task" ${d.createTask ? 'checked' : ''} class="rounded" onchange="document.getElementById('rule-task-fields').classList.toggle('hidden', !this.checked)">
                    Also raise a follow-up task for whoever gets it
                </label>
                <div id="rule-task-fields" class="grid grid-cols-3 gap-2 ${d.createTask ? '' : 'hidden'}">
                    <input id="rule-task-title" class="corp-input col-span-2 text-xs" value="${esc(d.taskTitle)}" placeholder="Call the new enquiry">
                    <input id="rule-task-days" type="number" min="0" max="30" class="corp-input text-xs" value="${d.taskDueInDays}" title="Due in days">
                </div>
                <div>
                    <span class="block text-xs font-medium text-slate-700 mb-1">Only active on these days <span class="font-normal text-slate-400">(leave all off for every day)</span></span>
                    <div class="rule-people">
                        ${opts.days.map(day => `<label class="rule-person ${d.days.includes(day) ? 'is-on' : ''}">
                            <input type="checkbox" ${d.days.includes(day) ? 'checked' : ''} onchange="toggleDay('${day}')"> ${day.slice(0, 3)}</label>`).join('')}
                    </div>
                </div>
            </div>
        </details>

        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">${ruleDraft.id ? 'Save rule' : 'Create rule'}</button>
        </div>`;

    form.onsubmit = async e => {
        e.preventDefault();
        const body = {
            name: document.getElementById('rule-name').value.trim(),
            conditions: ruleDraft.conditions.filter(c => c.field && c.operator),
            assignees: ruleDraft.assignees, method: document.getElementById('rule-method').value,
            days: ruleDraft.days, createTask: document.getElementById('rule-task').checked,
            taskTitle: document.getElementById('rule-task-title').value.trim(),
            taskDueInDays: Number(document.getElementById('rule-task-days').value || 1)
        };
        try {
            if (ruleDraft.id) await apiJson(`/api/assignment-rules/${ruleDraft.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            else await apiJson('/api/assignment-rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            closeInsuranceForm(); showToast('Rule saved'); switchSettingTab('rules');
        } catch (err) { showToast(err.message); }
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

function addCondition() { ruleDraft.conditions.push({ field: 'policyType', operator: 'contains', value: '' }); renderRuleForm(); }
function removeCondition(i) { ruleDraft.conditions.splice(i, 1); renderRuleForm(); }
function updateCondition(i, key, value) {
    ruleDraft.conditions[i][key] = value;
    if (key === 'operator') renderRuleForm();
}
function togglePerson(name) {
    const at = ruleDraft.assignees.indexOf(name);
    at === -1 ? ruleDraft.assignees.push(name) : ruleDraft.assignees.splice(at, 1);
    renderRuleForm();
}
function toggleDay(day) {
    const at = ruleDraft.days.indexOf(day);
    at === -1 ? ruleDraft.days.push(day) : ruleDraft.days.splice(at, 1);
    renderRuleForm();
}

async function toggleRule(id, enable) {
    await apiJson(`/api/assignment-rules/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: enable }) });
    switchSettingTab('rules');
}
async function moveRule(id, direction) {
    await apiJson(`/api/assignment-rules/${id}/move`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction }) });
    switchSettingTab('rules');
}
async function deleteRule(id) {
    if (!confirm('Delete this rule? Enquiries it would have caught go back to being balanced across the team.')) return;
    await apiJson(`/api/assignment-rules/${id}`, { method: 'DELETE' });
    switchSettingTab('rules');
}

function testAssignmentRules() {
    openInsuranceForm('Test with an example enquiry', [
        ['policyType', 'Policy category', 'text', false],
        ['source', 'Where it came from', 'text', false],
        ['territory', 'Territory', 'text', false],
        ['premium', 'Premium', 'text', false]
    ], async v => {
        const r = await apiJson('/api/assignment-rules/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
        showToast(r.explanation);
    }, { policyType: 'Commercial Fleet Motor' });
}

// ── Profile, users & hierarchy actions ──────────────────────────────
async function saveProfile(event) {
    event.preventDefault();
    await apiJson('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: document.getElementById('prof-name').value.trim(),
            email: document.getElementById('prof-email').value.trim(),
            phone: document.getElementById('prof-phone').value.trim(),
            role: document.getElementById('prof-role').value.trim() }) });
    showToast('Profile saved'); await loadBrokerRoster(); switchSettingTab('profile');
}

async function switchActiveUser(id) {
    await apiJson('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentUserId: id }) });
    showToast('Switched user'); switchSettingTab('profile');
}

function addUser() {
    openInsuranceForm('Add user', [['name', 'Full name', 'text', true], ['email', 'Email', 'email', false],
        ['role', 'Job title', 'text', false]], async v => {
        await apiJson('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
        await loadBrokerRoster(); switchSettingTab('users');
    });
}

async function editUser(id) {
    const user = (await apiJson('/api/users')).find(u => u.id === id);
    openInsuranceForm('Edit user', [['name', 'Full name', 'text', true], ['email', 'Email', 'email', false],
        ['role', 'Job title', 'text', false], ['status', 'Status', 'select:Active|Inactive', true]], async v => {
        await apiJson(`/api/users/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
        await loadBrokerRoster(); switchSettingTab('users');
    }, user);
}

async function deactivateUser(id, name) {
    if (!confirm(`Deactivate ${name}? They stay on historical records but leave the rotation.`)) return;
    const r = await apiJson(`/api/users/${id}`, { method: 'DELETE' });
    showToast(r.openLeadsToReassign ? `Deactivated — ${r.openLeadsToReassign} open lead(s) still assigned to them` : 'User deactivated');
    await loadBrokerRoster(); switchSettingTab('users');
}

async function reactivateUser(id) {
    await apiJson(`/api/users/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'Active' }) });
    await loadBrokerRoster(); switchSettingTab('users');
}

async function setManager(id) {
    const users = (await apiJson('/api/users')).filter(u => u.id !== id && u.status !== 'Inactive');
    openInsuranceForm('Who do they report to?', [['reportsTo', 'Manager', `select:|${users.map(u => u.id).join('|')}`, false]],
        async v => {
            await apiJson(`/api/users/${id}/manager`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reportsTo: v.reportsTo || '' }) });
            switchSettingTab('hierarchy');
        });
    const select = document.querySelector('#insurance-dynamic-form [name="reportsTo"]');
    if (select) select.innerHTML = '<option value="">Top of the hierarchy</option>' +
        users.map(u => `<option value="${esc(u.id)}">${esc(u.name)}</option>`).join('');
}

// ── Demo data cleanup ───────────────────────────────────────────────
async function refreshDemoCleanupLink() {
    try {
        const summary = await apiJson('/api/demo-data');
        const link = document.getElementById('demo-cleanup-link');
        if (link) link.classList.toggle('hidden', summary.total === 0);
    } catch (e) { /* hidden by default */ }
}

async function openDemoCleanup() {
    const s = await apiJson('/api/demo-data');
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = 'Clear demo data';
    form.innerHTML = `
        <p class="text-xs text-slate-600 leading-relaxed">The CRM ships with sample records so the screens aren't empty while you set up. This removes those and keeps everything you've added.</p>
        <div class="grid grid-cols-2 gap-2">
            <div class="import-stat"><strong>${s.total}</strong><span>Demo records</span></div>
            <div class="import-stat"><strong>${s.realLeadCount}</strong><span>Your own leads (kept)</span></div>
        </div>
        <div class="border border-slateBorder rounded p-2.5 max-h-40 overflow-y-auto">
            <div class="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">What will be removed</div>
            ${Object.entries(s.byCollection).map(([k, v]) => `<div class="flex justify-between text-xs py-0.5"><span class="capitalize">${esc(k)}</span><span class="num-tabular text-slate-500">${v}</span></div>`).join('')}
            ${s.sampleNames.length ? `<p class="text-[11px] text-slate-400 mt-1.5">e.g. ${s.sampleNames.map(esc).join(', ')}</p>` : ''}
        </div>
        <label class="flex items-start gap-2 text-xs text-slate-600"><input type="checkbox" id="demo-users" class="mt-0.5 rounded"> Also remove sample team members who own no live work</label>
        <p class="text-[11px] text-slate-500">A backup is taken first, so this can be undone from Reports &amp; Backups.</p>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-rose-600 text-white rounded text-xs font-semibold">Remove ${s.total} demo records</button>
        </div>`;
    form.onsubmit = async e => {
        e.preventDefault();
        try {
            const r = await apiJson('/api/demo-data/purge', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ includeUsers: document.getElementById('demo-users').checked }) });
            closeInsuranceForm();
            showToast(`${r.removedTotal} demo records removed. Backup saved as ${r.safetyBackup}.`);
            await loadBrokerRoster(); refreshDemoCleanupLink(); switchView(currentView);
        } catch (err) { showToast(err.message); }
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

function createWhatsAppTemplate() {
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = 'New WhatsApp template';
    const tokens = ['name', 'organization', 'policyType', 'policyNumber', 'premium', 'expiryDate', 'daysRemaining', 'assignedTo'];
    form.innerHTML = `
        <p class="text-xs text-slate-600 leading-relaxed">Meta reviews the wording, not the individual client details. Write it once with placeholders and it works for every client.</p>
        <div class="space-y-3">
            <label class="block">
                <span class="block text-xs font-medium text-slate-700 mb-1">Template name</span>
                <input name="name" required class="corp-input" placeholder="Renewal reminder">
            </label>
            <div class="grid grid-cols-2 gap-3">
                <label class="block">
                    <span class="block text-xs font-medium text-slate-700 mb-1">Category</span>
                    <select name="category" class="corp-input">
                        <option value="UTILITY">Utility — reminders about an existing policy</option>
                        <option value="MARKETING">Marketing — offers and promotions</option>
                    </select>
                </label>
                <label class="block">
                    <span class="block text-xs font-medium text-slate-700 mb-1">Language</span>
                    <select name="language" class="corp-input">
                        <option value="en_US">English</option><option value="hi">Hindi</option>
                        <option value="mr">Marathi</option><option value="gu">Gujarati</option>
                        <option value="ta">Tamil</option><option value="te">Telugu</option>
                        <option value="kn">Kannada</option><option value="bn">Bengali</option>
                    </select>
                </label>
            </div>
            <label class="block">
                <span class="block text-xs font-medium text-slate-700 mb-1">Message</span>
                <textarea name="body" id="wa-body" rows="5" required class="corp-input" placeholder="Hello {{name}}, your {{policyType}} expires on {{expiryDate}}. Shall I prepare the renewal?"></textarea>
            </label>
            <div class="text-[11px] text-slate-500">Insert: ${tokens.map(t => `<button type="button" class="msg-token wa-token" onclick="insertWaToken('${t}')">{{${t}}}</button>`).join(' ')}</div>
            <label class="block">
                <span class="block text-xs font-medium text-slate-700 mb-1">Footer <span class="font-normal text-slate-400">(optional)</span></span>
                <input name="footer" class="corp-input" placeholder="Reply STOP to opt out">
            </label>
            <p class="text-[11px] text-slate-500 leading-relaxed">Meta usually reviews within a few hours. Utility templates about a policy the client already holds are approved most reliably; promotional wording is refused more often.</p>
        </div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save &amp; submit to Meta</button>
        </div>`;
    form.onsubmit = async e => {
        e.preventDefault();
        const v = Object.fromEntries(new FormData(form).entries());
        try {
            const t = await apiJson('/api/whatsapp-templates', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: v.name, category: v.category, language: v.language, body: v.body, footer: v.footer })
            });
            closeInsuranceForm();
            showToast(t.status === 'Pending review' ? 'Submitted to Meta — approval usually takes a few hours.'
                : t.statusNote || 'Saved as a draft.');
            switchSettingTab('watemplates');
        } catch (err) { showToast(err.message); }
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

function insertWaToken(token) {
    const box = document.getElementById('wa-body');
    const at = box.selectionStart ?? box.value.length;
    box.value = box.value.slice(0, at) + `{{${token}}}` + box.value.slice(box.selectionEnd ?? at);
    box.focus();
    box.selectionStart = box.selectionEnd = at + token.length + 4;
}

async function submitWhatsAppTemplate(id) {
    try { await apiJson(`/api/whatsapp-templates/${id}/submit`, { method: 'POST' });
        showToast('Submitted to Meta for approval'); switchSettingTab('watemplates');
    } catch (e) { showToast(e.message); }
}

async function syncWhatsAppTemplates() {
    try { const r = await apiJson('/api/whatsapp-templates/sync', { method: 'POST' });
        showToast(`${r.updatedCount} updated${r.importedCount ? `, ${r.importedCount} imported from Meta` : ''}`);
        switchSettingTab('watemplates');
    } catch (e) { showToast(e.message); }
}

async function deleteWhatsAppTemplate(id) {
    if (!confirm('Delete this template? It is removed from Meta as well and can no longer be sent.')) return;
    await apiJson(`/api/whatsapp-templates/${id}`, { method: 'DELETE' });
    showToast('Template deleted'); switchSettingTab('watemplates');
}

const communicationTemplateFields = [['name','Template name','text',true],['channel','Channel','select:Email|WhatsApp',true],['subject','Subject','text',false],['content','Message content','textarea',true]];
function createTemplate(){openInsuranceForm('New communication template',communicationTemplateFields,async v=>{await apiJson('/api/communication-templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});switchSettingTab('templates')})}
function editCommunicationTemplate(id){const item=(window.crmCommunicationTemplates||[]).find(t=>t.id===id);if(!item)return;openInsuranceForm('Edit communication template',communicationTemplateFields,async v=>{await apiJson(`/api/communication-templates/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});switchSettingTab('templates')},item)}
async function archiveTemplate(id){await apiJson(`/api/communication-templates/${id}`,{method:'DELETE'});showToast('Template archived and removed from Send message');await switchSettingTab('templates')}
async function restoreTemplate(id){await apiJson(`/api/communication-templates/${id}/restore`,{method:'POST'});showToast('Template restored');await switchSettingTab('templates')}
async function deleteTemplatePermanently(id){if(!confirm('Permanently delete this archived template? This cannot be undone.'))return;await apiJson(`/api/communication-templates/${id}?permanent=true`,{method:'DELETE'});showToast('Archived template permanently deleted');await switchSettingTab('templates')}
function createTeamUser(){openInsuranceForm('Add CRM user',[['name','Full name','text',true],['email','Work email','email',true],['role','Role','select:Sales Executive|Senior Sales Executive|Account Manager|Manager|Read-only Auditor',true],['temporaryPassword','Temporary password','password',true]],async values=>{await apiJson('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});await loadBrokerRoster();switchSettingTab('team')})}
async function deactivateTeamUser(id){if(!confirm('Deactivate this login? Historical ownership is retained and open work must be reassigned.'))return;await apiJson(`/api/users/${id}`,{method:'DELETE'});showToast('User deactivated');await switchSettingTab('team')}
async function saveCrmConfiguration(e){e.preventDefault();const lines=id=>document.getElementById(id).value.split('\n').map(x=>x.trim()).filter(Boolean);await apiJson('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({crm:{leadStages:lines('config-stages'),insuranceProducts:lines('config-products'),insurers:lines('config-insurers'),companyTimezone:document.getElementById('config-timezone').value,upcomingReminderMinutes:Number(document.getElementById('config-reminder-minutes').value)}})});showToast('CRM configuration saved')}
async function restoreLead(id){await apiJson(`/api/archived-leads/${id}/restore`,{method:'POST'});await switchSettingTab('archive');showToast('Lead restored')}
async function restoreOperationalRecord(id){await apiJson(`/api/archived-records/${id}/restore`,{method:'POST'});await switchSettingTab('archive');showToast('Record restored')}
async function createSystemBackup(){await apiJson('/api/backups',{method:'POST'});await switchSettingTab('reports');showToast('Backup created')}

// ═══════════════════════════════════════════════════════════════════
// 7b. CALENDAR — one grid across tasks, next actions, renewals, meetings
// ═══════════════════════════════════════════════════════════════════
let calendarMonth = new Date();
let calendarTypeFilter = '';
const localCalendarDate = (value = new Date()) => `${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
let calendarSelectedDate = localCalendarDate();

const CAL_TYPES = [['', 'Everything'], ['Task', 'Tasks & follow-ups'], ['Next action', 'Next actions'],
                   ['Appointment', 'Meetings & calls'], ['Renewal', 'Renewals'], ['Deal', 'Deals'],
                   ['Quotation', 'Quotations'], ['Service', 'Servicing'], ['Message', 'Messages']];
const CAL_TONE = { 'Task': 'cal-task', 'Next action': 'cal-next', 'Renewal': 'cal-renewal',
                   'Appointment': 'cal-meeting', 'Deal':'cal-deal', 'Quotation':'cal-quote',
                   'Service':'cal-service', 'Message':'cal-message' };

function monthBounds(date) {
    const first = new Date(date.getFullYear(), date.getMonth(), 1);
    const last = new Date(date.getFullYear(), date.getMonth() + 1, 0);
    const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return { start: iso(first), end: iso(last), first, last, iso };
}

async function loadCalendar() {
    const { start, end, first, last, iso } = monthBounds(calendarMonth);
    const params = new URLSearchParams({ start, end });
    if (calendarTypeFilter) params.set('types', calendarTypeFilter);
    const data = await apiJson(`/api/calendar?${params}`);
    window.crmCalendar = data.entries;

    document.getElementById('calendar-title').textContent =
        calendarMonth.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

    document.getElementById('calendar-filters').innerHTML = CAL_TYPES.map(([value, label]) => {
        const count = value ? (data.counts[value] || 0) : data.total;
        return `<button onclick="setCalendarFilter('${value}')" class="cal-filter ${calendarTypeFilter === value ? 'is-on' : ''}">${esc(label)} <span>${count}</span></button>`;
    }).join('');

    const byDate = {};
    data.entries.forEach(e => (byDate[e.date] = byDate[e.date] || []).push(e));

    // Grid starts on the Monday of the week containing the 1st.
    const lead = (first.getDay() + 6) % 7;
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(null);
    for (let d = 1; d <= last.getDate(); d++) cells.push(new Date(first.getFullYear(), first.getMonth(), d));
    while (cells.length % 7) cells.push(null);

    const today = localCalendarDate();
    document.getElementById('calendar-grid').innerHTML = cells.map(cell => {
        if (!cell) return '<div class="cal-cell is-empty"></div>';
        const key = iso(cell);
        const items = byDate[key] || [];
        return `<div class="cal-cell ${key === today ? 'is-today' : ''} ${key === calendarSelectedDate ? 'is-selected' : ''}" onclick="selectCalendarDate('${key}')">
            <span class="cal-date">${cell.getDate()}</span>
            <div class="cal-items">
                ${items.slice(0, 3).map(i => `<span class="cal-chip ${CAL_TONE[i.type] || 'cal-task'} ${i.done ? 'is-done' : ''}" title="${esc(i.title)}">${esc(i.title)}</span>`).join('')}
                ${items.length > 3 ? `<span class="cal-more">+${items.length - 3} more</span>` : ''}
            </div>
        </div>`;
    }).join('');

    renderCalendarAgenda();
}

function renderCalendarAgenda() {
    const entries = (window.crmCalendar || []).filter(e => e.date === calendarSelectedDate);
    const pretty = new Date(calendarSelectedDate + 'T00:00:00')
        .toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
    document.getElementById('calendar-agenda-title').textContent = `${pretty} — ${entries.length} item${entries.length === 1 ? '' : 's'}`;
    document.getElementById('calendar-agenda').innerHTML = entries.length ? entries.map(e => `
        <div class="flex items-center justify-between gap-3 px-3 py-2.5 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
                <span class="cal-dot ${CAL_TONE[e.type] || 'cal-task'}"></span>
                <div class="min-w-0">
                    <div class="font-medium text-slate-800 truncate ${e.done ? 'line-through text-slate-400' : ''}">${esc(e.title)}</div>
                    <div class="text-[11px] text-slate-500 truncate">${esc(e.activityType || e.source)}${e.linkLabel ? ` · ${esc(e.linkLabel)}` : ''}${e.assignedTo ? ` · ${esc(e.assignedTo)}` : ''}${e.time ? ` · ${esc(e.time)}` : ''}</div>
                    ${e.notes ? `<div class="text-[11px] text-slate-500 mt-0.5">${esc(e.notes)}</div>` : ''}
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                ${e.type === 'Task' && !e.done ? `<button onclick="completeCalendarTask('${e.id}')" class="text-[11px] font-semibold text-slate-700">Done</button>` : ''}
                ${e.type === 'Appointment' && !e.done ? `<button onclick="completeCalendarEvent('${e.id}')" class="text-[11px] font-semibold text-emerald-700">Complete</button>` : ''}
                ${(e.type === 'Task' || e.type === 'Next action' || (e.type === 'Renewal' && String(e.id).startsWith('ren-')) || e.type === 'Appointment') ? `<button onclick="rescheduleCalendarEntry('${e.id}')" class="text-[11px] font-semibold text-slate-700">Move</button>` : ''}
                ${e.linkType && e.linkId ? `<button onclick="openCalendarLink('${e.linkType}','${e.linkId}')" class="text-[11px] font-semibold text-slate-700">Open</button>` : ''}
            </div>
        </div>`).join('') : '<div class="px-3 py-8 text-center text-xs text-slate-400">Nothing scheduled for this day.</div>';
}

function selectCalendarDate(date) { calendarSelectedDate = date; loadCalendar(); }
function setCalendarFilter(type) { calendarTypeFilter = type; loadCalendar(); }
function shiftCalendar(delta) { calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + delta, 1); loadCalendar(); }
function goToday() { calendarMonth = new Date(); calendarSelectedDate = localCalendarDate(); loadCalendar(); }

async function completeCalendarTask(id) {
    await apiJson(`/api/tasks/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'Completed' }) });
    showToast('Task completed'); loadCalendar(); refreshNotificationBadge();
}

async function completeCalendarEvent(id) {
    await apiJson(`/api/calendar/events/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'Completed'})});
    showToast('Appointment completed — any planned follow-up remains in Tasks'); loadCalendar(); refreshNotificationBadge();
}

function openCalendarLink(type, id) {
    if (type === 'Lead') return openLeadDrawer(id);
    if (type === 'Customer') { switchView('customers'); return setTimeout(() => openCustomer360(id), 120); }
    const views = {'Policy':'policies','Renewal':'renewals','Deal':'deals','Organization':'organizations','Contact':'contacts','Service Request':'policies'};
    switchView(views[type] || 'dashboard');
}

function rescheduleCalendarEntry(id) {
    openInsuranceForm('Move to another date', [['date', 'New date', 'date', true]], async v => {
        await apiJson('/api/calendar/reschedule', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, date: v.date }) });
        loadCalendar();
    }, { date: calendarSelectedDate });
}

async function openCalendarEventForm(prefillType = '', prefillId = '') {
    const entities = await apiJson('/api/entities').catch(() => []);
    const linkable = entities.filter(e => ['Lead','Customer','Policy','Renewal','Deal','Organization','Contact','Service Request'].includes(e.type)).slice(0, 500);
    openInsuranceForm('Book a meeting', [
        ['title', 'What is it', 'text', true],
        ['date', 'Date', 'date', true],
        ['time', 'Time', 'time', false],
        ['durationMinutes', 'Duration (minutes)', 'select:15|30|45|60|90|120', true],
        ['type', 'Type', 'select:Meeting|Call|Site visit|Survey|Renewal review', true],
        ['associatedId', 'Related CRM record', 'select:', false],
        ['assignedTo', 'Owner', ownerFieldOptions(), false],
        ['notes', 'Meeting purpose / notes', 'textarea', false],
        ['followUpAction', 'Planned follow-up', 'text', false],
        ['followUpDate', 'Follow-up date', 'date', false]
    ], async v => {
        const [associatedType, associatedId] = v.associatedId ? v.associatedId.split(':', 2) : ['Lead', ''];
        await apiJson('/api/calendar/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...v, associatedType, associatedId, durationMinutes:Number(v.durationMinutes || 30), createTask: true }) });
        showToast(v.followUpDate ? 'Meeting and follow-up booked' : 'Meeting booked — reminders are active');
        loadCalendar();
    }, { date: calendarSelectedDate, type: 'Meeting', durationMinutes:'30' });

    // Show client names rather than raw ids in the picker.
    const select = document.querySelector('#insurance-dynamic-form [name="associatedId"]');
    if (select) {
        select.innerHTML = '<option value="">No record linked</option>' +
            linkable.map(item => `<option value="${esc(item.type)}:${esc(item.id)}">[${esc(item.type)}] ${esc(item.title)}</option>`).join('');
        if (prefillType && prefillId) select.value = `${prefillType}:${prefillId}`;
    }
}

// ═══════════════════════════════════════════════════════════════════
// 8a. LEAD SOURCES — advertising & messaging gateway
// ═══════════════════════════════════════════════════════════════════
let channelProviders = [];

const PROVIDER_ICONS = {
    meta: '<path d="M14 9h3V6h-3a4 4 0 0 0-4 4v2H8v3h2v7h3v-7h3l1-3h-4v-2a1 1 0 0 1 1-1z"/>',
    meta_facebook: '<path d="M14 9h3V6h-3a4 4 0 0 0-4 4v2H8v3h2v7h3v-7h3l1-3h-4v-2a1 1 0 0 1 1-1z"/>',
    meta_instagram: '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/>',
    whatsapp: '<path d="M21 12a9 9 0 0 1-13.5 7.8L3 21l1.3-4.4A9 9 0 1 1 21 12z"/><path d="M8.5 9.5c0 3.5 3 6.5 6.5 6.5.6 0 1.2-.5 1.2-1.1l-1.7-.9-1 1a5 5 0 0 1-2.6-2.6l1-1-.9-1.7c-.6 0-1.5.6-1.5 1.2z"/>',
    google: '<path d="M21 12.2c0 5-3.4 8.3-8.5 8.3a8.5 8.5 0 1 1 5.9-14.6l-2.4 2.3a5 5 0 1 0-3.5 8.6 4.3 4.3 0 0 0 4.4-3.4h-4.4v-3H21z"/>',
    linkedin: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 10v7M7 7v.01M11 17v-4a2 2 0 0 1 4 0v4"/>',
    email: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    custom: '<path d="M4 7h16M4 12h16M4 17h10"/>'
};

const providerIcon = (p, size = 18) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${PROVIDER_ICONS[p] || PROVIDER_ICONS.custom}</svg>`;

async function loadChannels() {
    const [channels, providers, events] = await Promise.all([
        apiJson('/api/channels'), apiJson('/api/channel-providers'), apiJson('/api/channel-events?limit=25')
    ]);
    channelProviders = providers;
    window.crmChannels = channels;

    const list = document.getElementById('channels-connected');
    list.innerHTML = channels.length ? channels.map(ch => {
        const hasReceived = Boolean(ch.lastEventAt);
        const showSetup = window.justCreatedChannelId === ch.id;
        return `
        <div class="bg-white border border-slateBorder rounded-lg p-4 space-y-3" data-channel-id="${ch.id}">
            <div class="flex items-start justify-between gap-3">
                <div class="flex items-start gap-3 min-w-0">
                    <span class="channel-icon">${providerIcon(ch.provider)}</span>
                    <div class="min-w-0">
                        <div class="flex items-center gap-2">
                            <span class="font-semibold text-slate-900 text-sm">${esc(ch.name)}</span>
                            <span class="channel-pill ${hasReceived && ch.status === 'Connected' ? 'is-live' : ch.status === 'Paused' ? 'is-paused' : ''}">${ch.status === 'Paused' ? 'Paused' : hasReceived ? 'Receiving leads' : 'Ready to finish'}</span>
                        </div>
                        <div class="text-[11px] text-slate-500">${esc(ch.providerLabel)} · ${ch.lastEventAt ? `last enquiry ${esc(ch.lastEventAt.slice(0, 10))}` : 'complete the short setup below'}</div>
                    </div>
                </div>
                <button onclick="sendChannelTest('${ch.id}')" class="px-3 py-1.5 rounded bg-slate-900 text-white text-xs font-semibold shrink-0">Test connection</button>
            </div>

            <div class="grid grid-cols-4 gap-2">
                ${[['received', 'Received'], ['created', 'New leads'], ['duplicates', 'Matched existing'], ['failed', 'Needs attention']]
                  .map(([k, label]) => `<div class="channel-stat"><strong>${ch.stats?.[k] ?? 0}</strong><span>${label}</span></div>`).join('')}
            </div>

            <details class="source-setup" ${showSetup || !hasReceived ? 'open' : ''}>
                <summary><span><strong>${hasReceived ? 'View connection setup' : 'Finish setup'}</strong><small>${hasReceived ? 'Callback details and provider instructions' : 'Usually 2–5 minutes'}</small></span><span aria-hidden="true">⌄</span></summary>
                <div class="source-setup-body">
                ${['meta','google','linkedin'].includes(ch.provider) ? `<div class="rounded border ${ch.oauthAuthorized?'border-emerald-200 bg-emerald-50':'border-slate-200 bg-slate-50'} p-3 flex items-center justify-between gap-3"><div><strong class="text-xs">${ch.oauthAuthorized?'Ad account authorized':'Authorize your ad account'}</strong><p class="text-[11px] text-slate-500 mt-0.5">${ch.oauthAuthorized?'The provider granted secure account access.':'You will sign in on the provider website; InsureCRM never receives your password.'}</p></div>${ch.oauthAuthorized?'':`<button onclick="beginChannelOAuth('${ch.id}')" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold shrink-0">Connect account</button>`}</div>` : ''}
                <div class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Step 1 — copy into ${esc(ch.providerLabel)}</div>
                <div class="channel-cred"><span>Callback URL</span><code>${esc(ch.webhookUrl)}</code><button onclick="copyText('${esc(ch.webhookUrl)}')">Copy</button></div>
                ${ch.credentials?.verifyToken ? `<div class="channel-cred"><span>Verification password</span><code>${esc(ch.credentials.verifyToken)}</code><button onclick="copyText('${esc(ch.credentials.verifyToken)}')">Copy</button></div>` : ''}
                ${ch.credentials?.googleKey ? `<div class="channel-cred"><span>Lead form key</span><code>${esc(ch.credentials.googleKey)}</code><button onclick="copyText('${esc(ch.credentials.googleKey)}')">Copy</button></div>` : ''}
                ${ch.credentials?.sharedSecret ? `<div class="channel-cred"><span>Shared password</span><code>${esc(ch.credentials.sharedSecret)}</code><button onclick="copyText('${esc(ch.credentials.sharedSecret)}')">Copy</button></div>` : ''}
                ${ch.steps?.length ? `<div class="text-[10px] font-bold uppercase tracking-wider text-slate-500 pt-2">Step 2 — finish in ${esc(ch.providerLabel)}</div><ol class="channel-steps">${ch.steps.slice(1).map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}
                <div class="rounded bg-emerald-50 border border-emerald-200 p-2 text-[11px] text-emerald-800"><strong>Step 3:</strong> return here and choose “Test connection.” A sample enquiry should appear below and in Leads & Accounts.</div>
                </div>
            </details>

            <details class="source-manage"><summary>More options</summary><div class="flex flex-wrap gap-3 pt-2 text-[11px] font-semibold">
                <button onclick="editChannelMapping('${ch.id}')">Field mapping</button>
                ${['whatsapp', 'email'].includes(ch.provider) ? `<button onclick="configureSending('${ch.id}')">Sending setup</button>` : ''}
                <button onclick="toggleChannelStatus('${ch.id}','${ch.status}')">${ch.status === 'Paused' ? 'Resume source' : 'Pause source'}</button>
                <button onclick="disconnectChannel('${ch.id}')" class="text-rose-600">Disconnect</button>
            </div></details>
        </div>`;
    }).join('')
        : `<div class="bg-white border border-dashed border-slate-300 rounded-lg p-8 text-center">
             <p class="text-sm font-medium text-slate-700">No lead sources connected yet</p>
             <p class="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">Choose your ad platform. The CRM creates the technical details automatically and shows only the steps you need.</p>
             <button onclick="openConnectSourcePicker()" class="mt-3 px-4 py-2 bg-slate-900 text-white rounded text-xs font-semibold">Connect my first source</button>
           </div>`;

    if (window.justCreatedChannelId) {
        list.querySelector(`[data-channel-id="${window.justCreatedChannelId}"]`)?.scrollIntoView({behavior:'smooth',block:'center'});
        window.justCreatedChannelId = null;
    }

    renderChannelEvents(events);
}

function renderChannelEvents(events) {
    const feed = document.getElementById('channel-events-feed');
    const tone = { 'Lead created': 'is-good', 'Duplicate': 'is-warn', 'Failed': 'is-bad', 'Ignored': '', 'Reprocessed': 'is-good' };
    feed.innerHTML = events.length ? events.map(e => {
        const who = e.mappedValues?.name || e.mappedValues?.mobile || e.mappedValues?.email || '—';
        return `<div class="flex items-center justify-between gap-3 px-3 py-2.5 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
                <span class="text-slate-400 shrink-0">${providerIcon(e.provider, 14)}</span>
                <div class="min-w-0">
                    <div class="font-medium text-slate-800 truncate">${esc(who)}${e.attribution?.campaignId ? ` <span class="text-slate-400 font-normal">· ${esc(e.attribution.campaignId)}</span>` : ''}</div>
                    <div class="text-[11px] text-slate-500 truncate">${esc(e.channelName || '')}${e.message ? ` — ${esc(e.message)}` : ''}</div>
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="channel-pill ${tone[e.status] || ''}">${esc(e.status)}</span>
                ${e.leadId ? `<button onclick="openLeadDrawer('${e.leadId}')" class="text-[11px] font-semibold text-slate-700">Open</button>` : ''}
                ${e.status === 'Failed' ? `<button onclick="reprocessChannelEvent('${e.id}')" class="text-[11px] font-semibold text-slate-700">Retry</button>` : ''}
            </div>
        </div>`;
    }).join('') : '<div class="px-3 py-8 text-center text-xs text-slate-400">Enquiries from your connected sources will appear here.</div>';
}

async function openConnectSourcePicker() {
    if (!channelProviders.length) channelProviders = await apiJson('/api/channel-providers');
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = 'Connect a lead source';
    setInsuranceFormBack(() => closeInsuranceForm(), 'Back');
    form.onsubmit = e => e.preventDefault();
    const adProviders = channelProviders.filter(p => ['meta','google','linkedin'].includes(p.provider));
    const otherProviders = channelProviders.filter(p => !['meta','google','linkedin'].includes(p.provider));
    const cards = providers => providers.map(p => `
                <button type="button" onclick="chooseProvider('${p.provider}')" class="channel-choice">
                    <span class="channel-icon">${providerIcon(p.provider)}</span>
                    <span><strong>${esc(p.label)}</strong><small>${esc(p.kind)}</small></span>
                    <span class="channel-choice-arrow" aria-hidden="true">→</span>
                </button>`).join('');
    form.innerHTML = `
        <div class="source-dialog-progress"><b>1</b><span>Choose source</span><i></i><b>2</b><span>Name it</span><i></i><b>3</b><span>Test</span></div>
        <div><h3 class="font-semibold text-sm">Where do your leads come from?</h3><p class="text-xs text-slate-500 mt-1">No account passwords are needed on this step.</p></div>
        <div><div class="source-group-label">Advertising platforms</div><div class="channel-picker">${cards(adProviders)}</div></div>
        <details class="source-other"><summary>Website, WhatsApp, email or another app</summary><div class="channel-picker mt-2">${cards(otherProviders)}</div></details>
        <div class="pt-3 border-t border-slateBorder flex justify-end">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
        </div>`;
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

function chooseProvider(provider) {
    const spec = channelProviders.find(p => p.provider === provider);
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = `Connect ${spec.label}`;
    setInsuranceFormBack(() => openConnectSourcePicker(), 'Back');
    form.innerHTML = `
        <div class="source-dialog-progress"><b class="is-done">✓</b><span>Source chosen</span><i></i><b>2</b><span>Name it</span><i></i><b>3</b><span>Test</span></div>
        <div class="flex items-start gap-3"><span class="channel-icon">${providerIcon(provider)}</span><div><h3 class="font-semibold text-sm">${esc(spec.label)}</h3><p class="text-xs text-slate-500 mt-1 leading-relaxed">${esc(spec.summary || '')}</p></div></div>
        ${spec.summaryNote ? `<p class="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2.5 py-1.5 leading-relaxed">${esc(spec.summaryNote)}</p>` : ''}
        <div class="space-y-3">
            <label class="block"><span class="block text-xs font-medium text-slate-700 mb-1">Connection name</span><input name="name" value="${esc(spec.label)}" required class="corp-input" aria-describedby="source-name-help"><span id="source-name-help" class="block text-[11px] text-slate-500 mt-1">Only visible inside your CRM. You can change it later.</span></label>
            <label class="block"><span class="block text-xs font-medium text-slate-700 mb-1">Default insurance product <span class="font-normal text-slate-400">(optional)</span></span><input name="policyType" class="corp-input" placeholder="e.g. Commercial Motor"><span class="block text-[11px] text-slate-500 mt-1">New enquiries from this source will be tagged automatically.</span></label>
        </div>
        <div class="rounded bg-emerald-50 border border-emerald-200 px-3 py-2 text-[11px] text-emerald-800"><strong>That is all for this step.</strong> The CRM will generate the callback address and verification key for you.</div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap items-center justify-between gap-2">
            <button type="button" onclick="openConnectSourcePicker()" class="text-xs font-semibold text-slate-600">← Different source</button>
            <div class="flex gap-2 ml-auto">
                <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
                <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Create & show setup</button>
            </div>
        </div>`;

    form.onsubmit = async e => {
        e.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries());
        const credentials = {};
        // Guard the case from the screenshot: two identical Google Ads connections, made by
        // reopening the picker instead of going back. Two callback URLs to maintain and
        // enquiries split across both is almost never what someone means to do.
        const duplicate = (window.crmChannels || []).find(c => c.provider === provider);
        if (duplicate) {
            const proceed = await confirmDestructive({
                title: `${spec.label} is already connected`,
                body: `“${duplicate.name}” is already set up. Add a second one only if you genuinely run separate ad accounts — otherwise go back and finish setting up the existing connection.`,
                confirmLabel: 'Add a second one anyway', tone: 'neutral'
            });
            if (!proceed) { closeInsuranceForm(); loadChannels(); return; }
        }
        try {
            const created = await apiJson('/api/channels', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, name: values.name || spec.label, credentials,
                    defaults: { policyType: values.policyType || '' } })
            });
            window.justCreatedChannelId = created.id;
            closeInsuranceForm();
            showToast(`${spec.label} is ready. Complete the highlighted setup and run the test.`);
            loadChannels();
        } catch (err) { showToast(err.message); }
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

async function editChannelMapping(id) {
    const channel = (window.crmChannels || []).find(c => c.id === id);
    const spec = channelProviders.find(p => p.provider === channel.provider);
    const crmFields = [['name', 'Client name'], ['mobile', 'Mobile'], ['email', 'Email'], ['organization', 'Organization'],
        ['policyType', 'Policy category'], ['premium', 'Premium'], ['territory', 'Territory'],
        ['designation', 'Job title'], ['companyDescription', 'Notes'], ['__skip__', 'Keep as extra detail']];
    const entries = Object.entries({ ...spec.defaultMapping, ...(channel.fieldMapping || {}) });
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = `${channel.name} — field mapping`;
    form.innerHTML = `
        <p class="text-xs text-slate-500">Decide which CRM field each incoming form field fills. Anything set to “extra detail” is still saved on the record.</p>
        <div class="import-map-list">
            ${entries.map(([source, target]) => `
                <div class="import-map-row">
                    <div class="min-w-0"><div class="font-medium text-slate-800 text-xs truncate">${esc(source)}</div>
                        <div class="text-[10.5px] text-slate-400">from ${esc(spec.label)}</div></div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="1.5"><path d="M5 12h14m0 0-5-5m5 5-5 5"/></svg>
                    <select data-source="${esc(source)}" class="corp-input text-xs py-1 channel-map-select">
                        ${crmFields.map(([f, label]) => `<option value="${f}" ${target === f ? 'selected' : ''}>${esc(label)}</option>`).join('')}
                    </select>
                </div>`).join('')}
        </div>
        <div class="pt-3 border-t border-slateBorder flex justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save mapping</button>
        </div>`;
    form.onsubmit = async e => {
        e.preventDefault();
        const fieldMapping = {};
        document.querySelectorAll('.channel-map-select').forEach(sel => { fieldMapping[sel.dataset.source] = sel.value; });
        await apiJson(`/api/channels/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fieldMapping }) });
        closeInsuranceForm(); showToast('Field mapping saved'); loadChannels();
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

// ── Sending a message to a client ────────────────────────────────────
async function openSendMessage(leadId) {
    const [opts, lead] = await Promise.all([
        apiJson(`/api/leads/${leadId}/message-options`),
        apiJson(`/api/leads/${leadId}`)
    ]);
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = `Message ${lead.lead.name}`;
    const usable = opts.options.filter(o => o.canSend);

    if (!usable.length) {
        form.innerHTML = `<p class="text-xs text-slate-600">This client can't be messaged yet:</p>
            <ul class="text-xs text-slate-600 space-y-1">${opts.options.map(o => `<li>• <strong>${esc(o.channel)}</strong> — ${esc(o.reason)}</li>`).join('')}</ul>
            <div class="pt-3 border-t border-slateBorder flex justify-end"><button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Close</button></div>`;
        form.onsubmit = e => e.preventDefault();
        document.getElementById('insurance-form-modal').classList.remove('hidden');
        return;
    }

    const first = usable[0];
    form.innerHTML = `
        <div class="space-y-3">
            <label class="block">
                <span class="block text-xs font-medium text-slate-700 mb-1">Send by</span>
                <select name="channel" id="msg-channel" class="corp-input" onchange="updateMessageChannel()">
                    ${usable.map(o => `<option value="${o.channel}" data-live="${o.live}" data-recipient="${esc(o.recipient)}" data-reason="${esc(o.reason)}">${o.channel} — ${esc(o.recipient)}</option>`).join('')}
                </select>
            </label>
            <div id="msg-live-note" class="text-[11px] leading-relaxed"></div>
            <div id="msg-wa-template-wrap" class="${opts.whatsapp.requiresApprovedTemplate ? '' : 'hidden'}">
                <label class="block">
                    <span class="block text-xs font-medium text-slate-700 mb-1">Approved WhatsApp template</span>
                    <select id="msg-wa-template" class="corp-input" onchange="applyWhatsAppTemplate()">
                        <option value="">Choose a template…</option>
                        ${opts.whatsapp.approvedTemplates.map(t => `<option value="${t.id}" data-body="${esc(t.body)}">${esc(t.name)}</option>`).join('')}
                    </select>
                </label>
                ${!opts.whatsapp.approvedTemplates.length ? `<p class="text-[11px] text-amber-700 mt-1">No approved templates yet — create one under Settings → WhatsApp Templates and submit it to Meta.</p>` : ''}
            </div>
            ${opts.templates.length ? `
            <label class="block" id="msg-template-wrap">
                <span class="block text-xs font-medium text-slate-700 mb-1">Start from a template <span class="font-normal text-slate-400">(optional)</span></span>
                <select id="msg-template" class="corp-input" onchange="applyMessageTemplate()">
                    <option value="">Write from scratch</option>
                    ${opts.templates.map(t => `<option value="${t.id}" data-subject="${esc(t.subject || '')}" data-content="${esc(t.content)}">${esc(t.name)} (${esc(t.channel)})</option>`).join('')}
                </select>
            </label>` : ''}
            <label class="block" id="msg-subject-wrap">
                <span class="block text-xs font-medium text-slate-700 mb-1">Subject</span>
                <input name="subject" id="msg-subject" class="corp-input">
            </label>
            <label class="block">
                <span class="block text-xs font-medium text-slate-700 mb-1">Message</span>
                <textarea name="content" id="msg-content" rows="6" required class="corp-input"></textarea>
            </label>
            <p class="text-[11px] text-slate-500 leading-relaxed">Placeholders filled automatically: ${opts.tokens.map(t => `<code class="msg-token">{{${t}}}</code>`).join(' ')}</p>
        </div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Send message</button>
        </div>`;

    window.__msgWindow = opts.whatsapp;
    form.onsubmit = async e => {
        e.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries());
        const waTemplateId = values.channel.toLowerCase() === 'whatsapp' && opts.whatsapp.requiresApprovedTemplate
            ? (document.getElementById('msg-wa-template')?.value || '') : '';
        if (values.channel.toLowerCase() === 'whatsapp' && opts.whatsapp.requiresApprovedTemplate && !waTemplateId) {
            return showToast('Choose an approved template — WhatsApp does not allow free text outside the 24-hour window.');
        }
        try {
            const sent = await apiJson(`/api/leads/${leadId}/message`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel: values.channel, subject: values.subject || '',
                    content: values.content, whatsappTemplateId: waTemplateId,
                    templateId: document.getElementById('msg-template')?.value || '' })
            });
            closeInsuranceForm();
            showToast(sent.status === 'Sent' ? `Message sent by ${sent.channel}.`
                : sent.status === 'Failed' ? `Not delivered: ${sent.error || 'sending failed'}`
                : 'Message saved to the client’s timeline — sending is not connected yet.');
            openLeadDrawer(leadId);
        } catch (err) { showToast(err.message); }
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
    updateMessageChannel();
}

function updateMessageChannel() {
    const select = document.getElementById('msg-channel');
    if (!select) return;
    const option = select.selectedOptions[0];
    const live = option.dataset.live === 'true';
    const isWhatsApp = select.value.toLowerCase() === 'whatsapp';
    const win = window.__msgWindow || {};
    const needsTemplate = isWhatsApp && win.requiresApprovedTemplate;

    document.getElementById('msg-subject-wrap').style.display = isWhatsApp ? 'none' : '';
    document.getElementById('msg-wa-template-wrap')?.classList.toggle('hidden', !needsTemplate);
    document.getElementById('msg-template-wrap')?.classList.toggle('hidden', needsTemplate);
    const content = document.getElementById('msg-content');
    content.readOnly = needsTemplate;
    content.classList.toggle('bg-slate-50', needsTemplate);
    if (needsTemplate) content.placeholder = 'Choose an approved template above — its wording appears here.';

    const note = document.getElementById('msg-live-note');
    if (needsTemplate) {
        note.innerHTML = `<span class="msg-note is-draft"><strong>WhatsApp 24-hour rule:</strong> ${esc(win.note || '')} Pick an approved template below — the client's details are filled in automatically.</span>`;
    } else if (isWhatsApp && live) {
        note.innerHTML = `<span class="msg-note is-live">${esc(win.note || '')} Will be delivered to ${esc(option.dataset.recipient)} now.</span>`;
    } else if (live) {
        note.innerHTML = `<span class="msg-note is-live">Will be delivered to ${esc(option.dataset.recipient)} now.</span>`;
    } else {
        note.innerHTML = `<span class="msg-note is-draft">${esc(option.dataset.reason || 'Sending is not connected for this channel yet')} — the message is saved to the timeline so the follow-up is recorded, but the client won't receive it.</span>`;
    }
}

function applyWhatsAppTemplate() {
    const option = document.getElementById('msg-wa-template').selectedOptions[0];
    document.getElementById('msg-content').value = option?.dataset.body || '';
}

function applyMessageTemplate() {
    const option = document.getElementById('msg-template').selectedOptions[0];
    if (!option || !option.value) return;
    document.getElementById('msg-content').value = option.dataset.content || '';
    const subject = document.getElementById('msg-subject');
    if (subject) subject.value = option.dataset.subject || '';
}

async function configureSending(id) {
    const channel = (window.crmChannels || []).find(c => c.id === id);
    const spec = channelProviders.find(p => p.provider === channel.provider);
    const fields = spec.credentials.filter(cr => cr.sending);
    const form = document.getElementById('insurance-dynamic-form');
    document.getElementById('insurance-form-title').textContent = `${channel.name} — sending setup`;
    form.innerHTML = `
        <p class="text-xs text-slate-600 leading-relaxed">Add these to send ${channel.provider === 'whatsapp' ? 'WhatsApp messages' : 'emails'} from a client's record. Until they're filled in, messages are recorded on the timeline but not delivered.</p>
        <div class="space-y-3">
            ${fields.map(cr => `
                <label class="block">
                    <span class="block text-xs font-medium text-slate-700">${esc(cr.label)}</span>
                    <span class="block text-[11px] text-slate-500 leading-relaxed mt-0.5 mb-1">${esc(cr.help || '')}</span>
                    <input name="cred_${cr.key}" class="corp-input" value="${esc(channel.credentials?.[cr.key] && !String(channel.credentials[cr.key]).includes('•') ? channel.credentials[cr.key] : '')}" placeholder="${channel.credentials?.[cr.key] ? 'Saved — type to replace' : ''}">
                </label>`).join('')}
        </div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">Cancel</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save sending setup</button>
        </div>`;
    form.onsubmit = async e => {
        e.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries());
        const credentials = {};
        fields.forEach(cr => { if (values[`cred_${cr.key}`]) credentials[cr.key] = values[`cred_${cr.key}`]; });
        await apiJson(`/api/channels/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credentials }) });
        closeInsuranceForm(); showToast('Sending setup saved'); loadChannels();
    };
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

async function sendChannelTest(id) {
    try {
        const r = await apiJson(`/api/channels/${id}/test`, { method: 'POST' });
        const outcome = r.events?.[0]?.status || 'sent';
        showToast(`Test enquiry ${outcome === 'Lead created' ? 'arrived and created a lead' : outcome.toLowerCase()}.`);
        loadChannels();
    } catch (e) { showToast(e.message); }
}

async function beginChannelOAuth(id) {
    try { const result=await apiJson(`/api/channels/${id}/oauth/start`); location.href=result.authorizationUrl; }
    catch(e){ showToast(e.message); }
}

async function toggleChannelStatus(id, status) {
    await apiJson(`/api/channels/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: status === 'Paused' ? 'Connected' : 'Paused' }) });
    loadChannels();
}

async function disconnectChannel(id) {
    if (!confirm('Disconnect this source? Leads already received are kept; no new enquiries will arrive.')) return;
    await apiJson(`/api/channels/${id}`, { method: 'DELETE' });
    showToast('Lead source disconnected'); loadChannels();
}

async function reprocessChannelEvent(id) {
    try { await apiJson(`/api/channel-events/${id}/reprocess`, { method: 'POST' }); showToast('Enquiry reprocessed'); loadChannels(); }
    catch (e) { showToast(e.message); }
}

function copyText(text) {
    navigator.clipboard?.writeText(text).then(() => showToast('Copied to clipboard'), () => showToast('Copy failed'));
}

// ═══════════════════════════════════════════════════════════════════
// 8b. SPREADSHEET IMPORT WIZARD — upload → map columns → import
// ═══════════════════════════════════════════════════════════════════
let importAnalysis = null;

function importPane() { return document.getElementById('setting-pane-content'); }

async function renderImportStep1(stillCurrent = () => true) {
    const history = await apiJson('/api/imports').catch(() => []);
    if (!stillCurrent()) return;
    const committed = history.filter(h => h.status !== 'Awaiting mapping');
    importPane().innerHTML = `
        <div class="space-y-4">
            <div>
                <h3 class="font-semibold text-slate-900 text-sm">Import your spreadsheet</h3>
                <p class="text-xs text-slate-500 mt-0.5">Upload the file as it is — your own column names are fine. You’ll confirm how each column maps before anything is saved, and any column the CRM doesn’t recognise is kept on the record rather than dropped.</p>
            </div>
            <label class="import-dropzone" for="import-file-input">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M12 16V4m0 0L8 8m4-4 4 4"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
                <strong>Choose a spreadsheet</strong>
                <span>.xlsx, .csv or .tsv — up to 5,000 rows</span>
                <input id="import-file-input" type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm" class="hidden" onchange="handleImportFile(this)">
            </label>
            <div id="import-status" class="text-xs text-slate-500"></div>
            ${committed.length ? `
            <div class="pt-2 border-t border-slateBorder">
                <h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2">Import history</h4>
                <div class="space-y-1.5">
                    ${committed.slice(0, 6).map(h => `
                        <div class="flex items-center justify-between gap-2 text-xs border border-slateBorder rounded px-2.5 py-2">
                            <div class="min-w-0">
                                <div class="font-medium text-slate-800 truncate">${esc(h.filename)}</div>
                                <div class="text-[11px] text-slate-500">${h.importedCount} imported · ${h.updatedCount} updated · ${h.skippedCount} skipped${h.errorCount ? ` · <span class="text-rose-600">${h.errorCount} rejected</span>` : ''}</div>
                            </div>
                            <div class="flex items-center gap-2 shrink-0">
                                ${h.errorCount ? `<a href="/api/imports/${h.id}/rejected.csv" class="text-[11px] font-semibold text-slate-700 underline">Rejected rows</a>` : ''}
                                ${h.rolledBackAt ? '<span class="text-[10px] text-slate-400">Rolled back</span>'
                                  : `<button onclick="rollbackImport('${h.id}')" class="text-[11px] font-semibold text-rose-600">Undo</button>`}
                            </div>
                        </div>`).join('')}
                </div>
            </div>` : ''}
        </div>`;
}

async function handleImportFile(input) {
    const file = input.files?.[0];
    if (!file) return;
    const status = document.getElementById('import-status');
    status.textContent = `Reading ${file.name}…`;
    try {
        importAnalysis = await apiJson(`/api/imports/analyze?filename=${encodeURIComponent(file.name)}`, {
            method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file
        });
        renderImportStep2();
    } catch (e) {
        status.innerHTML = `<span class="text-rose-600">${esc(e.message)}</span>`;
    }
}

function renderImportStep2() {
    const a = importAnalysis;
    const fieldOptions = (selected) => `
        <option value="__custom__" ${!selected ? 'selected' : ''}>Keep as extra detail</option>
        <option value="__skip__">Don’t import</option>
        ${a.availableFields.map(f => `<option value="${f.field}" ${selected === f.field ? 'selected' : ''}>${esc(f.label)}${f.required ? ' *' : ''}</option>`).join('')}`;

    importPane().innerHTML = `
        <div class="space-y-4">
            <div class="flex items-start justify-between gap-3">
                <div>
                    <h3 class="font-semibold text-slate-900 text-sm">Match your columns</h3>
                    <p class="text-xs text-slate-500 mt-0.5"><strong>${esc(a.filename)}</strong> · ${a.rowCount} rows · ${a.columns.length} columns. We’ve matched what we recognised — correct anything that’s wrong.</p>
                </div>
                <button onclick="renderImportStep1()" class="text-xs font-semibold text-slate-600 shrink-0">Choose another file</button>
            </div>

            <div class="import-map-list">
                ${a.columns.map(col => `
                    <div class="import-map-row">
                        <div class="min-w-0">
                            <div class="font-medium text-slate-800 text-xs truncate">${esc(col.header)}</div>
                            <div class="text-[10.5px] text-slate-400 truncate">${col.samples.length ? esc(col.samples.join(' · ')) : 'no values'}</div>
                        </div>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="1.5" class="shrink-0"><path d="M5 12h14m0 0-5-5m5 5-5 5"/></svg>
                        <select id="map-col-${col.index}" class="corp-input text-xs py-1" onchange="refreshImportMappingWarning()">
                            ${fieldOptions(col.suggestedField)}
                        </select>
                    </div>`).join('')}
            </div>

            <div id="import-map-warning" class="text-xs"></div>

            <div class="grid grid-cols-2 gap-3">
                <label class="block text-xs font-medium text-slate-700">If a client already exists
                    <select id="import-dedup" class="corp-input mt-1">
                        <option value="skip">Skip the row (match on phone or email)</option>
                        <option value="update">Update the existing record</option>
                        <option value="create">Import it as a separate record</option>
                    </select>
                </label>
                <label class="block text-xs font-medium text-slate-700">Assign rows with no owner to
                    <select id="import-default-owner" class="corp-input mt-1">
                        <option value="">Balance across brokers (round-robin)</option>
                        ${brokerRoster.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('')}
                    </select>
                </label>
            </div>

            <div>
                <h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Preview — first rows</h4>
                <div class="import-preview">
                    <table>
                        <thead><tr>${a.columns.map(c => `<th>${esc(c.header)}</th>`).join('')}</tr></thead>
                        <tbody>${a.previewRows.map(r => `<tr>${a.columns.map(c => `<td>${esc(r[c.index] || '')}</td>`).join('')}</tr>`).join('')}</tbody>
                    </table>
                </div>
            </div>

            <div class="flex items-center justify-between pt-1">
                <span class="text-[11px] text-slate-500">Nothing is saved until you confirm.</span>
                <button id="import-commit-btn" onclick="commitImport()" class="px-4 py-2 bg-slate-900 hover:bg-black text-white rounded font-semibold text-xs">Import ${a.rowCount} rows</button>
            </div>
        </div>`;
    refreshImportMappingWarning();
}

function currentImportMapping() {
    const mapping = {};
    importAnalysis.columns.forEach(col => {
        mapping[String(col.index)] = document.getElementById(`map-col-${col.index}`)?.value || '__custom__';
    });
    return mapping;
}

function refreshImportMappingWarning() {
    const mapping = currentImportMapping();
    const chosen = Object.values(mapping);
    const el = document.getElementById('import-map-warning');
    const btn = document.getElementById('import-commit-btn');
    if (!el) return;

    const duplicates = chosen.filter((v, i) => v !== '__custom__' && v !== '__skip__' && chosen.indexOf(v) !== i);
    if (!chosen.includes('name')) {
        el.innerHTML = '<span class="import-warn">Map one column to <strong>Client name</strong> to continue.</span>';
        if (btn) btn.disabled = true;
    } else if (duplicates.length) {
        const label = importAnalysis.availableFields.find(f => f.field === duplicates[0])?.label || duplicates[0];
        el.innerHTML = `<span class="import-warn">Two columns are both mapped to <strong>${esc(label)}</strong>.</span>`;
        if (btn) btn.disabled = true;
    } else {
        const kept = chosen.filter(v => v === '__custom__').length;
        const dropped = chosen.filter(v => v === '__skip__').length;
        el.innerHTML = `<span class="import-ok">Ready. ${kept} extra column${kept === 1 ? '' : 's'} will be kept on each record${dropped ? `, ${dropped} ignored` : ''}.</span>`;
        if (btn) btn.disabled = false;
    }
}

async function commitImport() {
    const btn = document.getElementById('import-commit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Importing…'; }
    try {
        const result = await apiJson(`/api/imports/${importAnalysis.importId}/commit`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mapping: currentImportMapping(),
                deduplicationStrategy: document.getElementById('import-dedup').value,
                defaults: { assignedTo: document.getElementById('import-default-owner').value }
            })
        });
        renderImportResult(result);
        await loadBrokerRoster();
        loadLeads();
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Import rows'; }
        showToast(e.message);
    }
}

function renderImportResult(r) {
    importPane().innerHTML = `
        <div class="space-y-4">
            <div>
                <h3 class="font-semibold text-slate-900 text-sm">Import finished</h3>
                <p class="text-xs text-slate-500 mt-0.5">Extra columns were saved against each record and appear in the client’s 360° view.</p>
            </div>
            <div class="grid grid-cols-4 gap-2">
                <div class="import-stat"><strong>${r.importedCount}</strong><span>Imported</span></div>
                <div class="import-stat"><strong>${r.updatedCount}</strong><span>Updated</span></div>
                <div class="import-stat"><strong>${r.skippedCount}</strong><span>Skipped</span></div>
                <div class="import-stat ${r.rejectedCount ? 'is-error' : ''}"><strong>${r.rejectedCount}</strong><span>Rejected</span></div>
            </div>
            ${r.rejectedCount ? `
                <div class="space-y-2">
                    <p class="text-xs text-slate-600">These rows were not imported. Download them, fix the reason given, and import that file again — nothing else is affected.</p>
                    <div class="import-preview"><table>
                        <thead><tr><th>Row</th><th>Reason</th></tr></thead>
                        <tbody>${r.errors.slice(0, 8).map(e => `<tr><td>${e.row}</td><td>${esc(e.message)}</td></tr>`).join('')}</tbody>
                    </table></div>
                    <a href="/api/imports/${r.importId}/rejected.csv" class="inline-block px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold">Download rejected rows</a>
                </div>` : '<p class="text-xs text-emerald-700">Every row was accounted for.</p>'}
            <div class="flex items-center gap-2 pt-1">
                <button onclick="closeSettingsModal(); switchView('leads')" class="px-4 py-2 bg-slate-900 text-white rounded font-semibold text-xs">View imported leads</button>
                <button onclick="rollbackImport('${r.importId}')" class="px-3 py-2 border border-slate-300 rounded text-xs font-semibold text-rose-600">Undo this import</button>
                <button onclick="renderImportStep1()" class="px-3 py-2 border border-slate-300 rounded text-xs font-semibold">Import another file</button>
            </div>
        </div>`;
}

async function rollbackImport(id) {
    if (!confirm('Undo this import? Records created by it are moved to the archive; anything already worked on is left in place.')) return;
    try {
        const r = await apiJson(`/api/imports/${id}/rollback`, { method: 'POST' });
        showToast(`${r.archivedCount} record(s) archived${r.retained.length ? `, ${r.retained.length} kept because work had started` : ''}.`);
        await renderImportStep1();
        loadLeads();
    } catch (e) { showToast(e.message); }
}

// ═══════════════════════════════════════════════════════════════════
// 9. AI ADVISOR
// ═══════════════════════════════════════════════════════════════════
function toggleAiAdvisor() {
    document.getElementById('ai-advisor-panel')?.classList.toggle('translate-x-full');
}

function askAdvisor(query) {
    document.getElementById('advisor-input').value = query;
    handleAdvisorSubmit(new Event('submit'));
}

async function handleAdvisorSubmit(e) {
    if (e) e.preventDefault();
    const input = document.getElementById('advisor-input');
    const query = input.value.trim();
    if (!query) return;

    const msgs = document.getElementById('advisor-messages');
    msgs.innerHTML += `
        <div class="flex justify-end">
            <div class="bg-slate-900 text-white p-2.5 rounded-lg max-w-[85%] text-xs">
                ${esc(query)}
            </div>
        </div>
    `;
    input.value = '';

    try {
        // Must go through apiJson: it attaches the CSRF token every mutation needs.
        const data = await apiJson('/api/ai-advisor', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });
        const body = esc(data.answer || '')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
        msgs.innerHTML += `
            <div class="bg-white p-3 rounded-lg border border-slateBorder text-xs text-slate-800 leading-relaxed shadow-xs">
                ${body}
                ${data.notice ? `<div class="mt-2 pt-2 border-t border-slate-100 text-[11px] text-amber-700">${esc(data.notice)}</div>` : ''}
            </div>
        `;
    } catch (err) {
        msgs.innerHTML += `
            <div class="bg-rose-50 border border-rose-200 p-3 rounded-lg text-xs text-rose-700">
                ${esc(err.message || 'The advisor could not be reached.')}
            </div>`;
    }
    msgs.scrollTop = msgs.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════
function stagePillClass(stage) {
    switch (stage) {
        case 'New': return 'bg-slate-100 text-slate-800 border border-slate-200';
        case 'Contacted': return 'bg-blue-50 text-blue-800 border border-blue-200';
        case 'Risk / Underwriting': return 'bg-amber-50 text-amber-800 border border-amber-200';
        case 'Quotation Sent': return 'bg-purple-50 text-purple-800 border border-purple-200';
        case 'Won': return 'bg-emerald-50 text-emerald-900 border border-emerald-300 font-semibold';
        case 'Lost': return 'bg-rose-50 text-rose-800 border border-rose-200';
        default: return 'bg-slate-100 text-slate-700';
    }
}

function getCategoryColor(cat) {
    switch (cat) {
        case 'Underwriting Note': return 'bg-amber-50 text-amber-800 border border-amber-200';
        case 'Risk Assessment': return 'bg-indigo-50 text-indigo-800 border border-indigo-200';
        case 'Stage Progression': return 'bg-slate-100 text-slate-700 border border-slate-200';
        case 'Meeting Minutes': return 'bg-emerald-50 text-emerald-800 border border-emerald-200';
        default: return 'bg-slate-100 text-slate-600';
    }
}

function formatDueBadge(dateStr, daysRemaining) {
    if (!dateStr) return 'No date set';
    const today = new Date().toISOString().split('T')[0];
    if (dateStr < today) return `Overdue (${dateStr})`;
    if (dateStr === today) return 'Due Today';
    return dateStr;
}

function showToast(msg) {
    const toast = document.getElementById('toast');
    const msgEl = document.getElementById('toast-msg');
    if (!toast || !msgEl) return;
    msgEl.textContent = msg;
    toast.classList.remove('opacity-0', 'pointer-events-none');
    toast.classList.add('opacity-100');
    setTimeout(() => {
        toast.classList.remove('opacity-100');
        toast.classList.add('opacity-0', 'pointer-events-none');
    }, 3000);
}

function esc(str) {
    return (str || '').toString().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function getInitials(name) {
    return (name || '?').trim().split(/\s+/).map(w => w[0]).join('').substring(0, 2).toUpperCase();
}

function timeAgo(isoDate) {
    if (!isoDate) return '-';
    const d = new Date(isoDate);
    return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
}
