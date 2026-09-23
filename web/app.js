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

// The lead vocabulary is served by /api/lead-options so screens never keep a copy that
// drifts from the server. These values only cover the first paint.
let STAGES = ["New", "Assigned", "Contacted", "Interested", "Quote Sent", "Follow-up", "Documents Pending",
    "Policy Sold", "Not Interested", "Call Later", "Wrong Number", "Unreachable", "Lost"];
let leadOptions = { statuses: STAGES, noNextAction: ['Lost', 'Not Interested', 'Policy Sold', 'Wrong Number'],
    reasonRequired: ['Lost', 'Not Interested'], products: ['Car Insurance', 'Health Insurance'], sources: [],
    closeReasons: [], fuelTypes: [], ncbLevels: [], healthPlanTypes: [], memberRelations: [] };

async function loadLeadOptions() {
    try { leadOptions = await apiJson('/api/lead-options'); STAGES = leadOptions.statuses; }
    catch (e) { /* keep the first-paint values */ }
    const filter = document.getElementById('leads-status-filter');
    if (filter) {
        const chosen = filter.value;
        filter.innerHTML = '<option value="">All statuses</option>' + STAGES.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
        filter.value = STAGES.includes(chosen) ? chosen : '';
    }
    return leadOptions;
}

// Mirrors is_open_lead() on the server: finished enquiries and wrong numbers are not open work.
const isOpenLead = lead => !leadOptions.noNextAction.includes(lead.status);
const needsNextAction = status => !leadOptions.noNextAction.includes(status);
const needsReason = status => leadOptions.reasonRequired.includes(status);

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
        select.innerHTML = (keepAll ? '<option value="">All telecallers</option>' : '')
            + brokerRoster.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
        if (current && brokerRoster.includes(current)) select.value = current;
    });
}

function ownerFieldOptions() {
    return brokerRoster.length ? `select:${brokerRoster.join('|')}` : 'text';
}

// "23 Sept 2026", in the viewer's own time zone.
function formatShortDate(value) {
    const d = new Date(value);
    return isNaN(d) ? String(value || '') : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
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
    await Promise.all([loadBrokerRoster(), loadLeadOptions()]);
    applyRoleVisibility();
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
    set('current-user-initials', initials); set('current-user-name', user.name); set('current-user-role', roleLabel(user));
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

function toggleAccountMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('account-menu');
    const open = menu.classList.toggle('hidden') === false;
    event.currentTarget.setAttribute('aria-expanded', String(open));
    if (open) {
        const close = e => { if (!menu.contains(e.target)) { menu.classList.add('hidden'); document.removeEventListener('click', close); } };
        setTimeout(() => document.addEventListener('click', close), 0);
    }
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
        view: 'leads', screen: 'Leads', heading: 'Capture the enquiry',
        summary: 'Every enquiry starts here — typed in directly, or imported in bulk from your existing spreadsheet.',
        points: [
            'New Lead records the customer, their mobile, car or health product and current policy expiry',
            'Import from spreadsheet brings your whole list across, skipping or updating duplicates',
            'Car and health details are optional — capture what the customer tells you, when they tell you'
        ],
        note: 'A lead with no renewal date stays out of the renewal radar until you set one.',
        hint: 'Start with New Lead in the top right, or Import to bring across an existing book.'
    },
    {
        view: 'leads', screen: 'Leads', heading: 'Move the stage, schedule the next action',
        summary: 'Click any stage pill to advance the lead. The CRM will not let you leave without deciding what happens next.',
        points: [
            'Thirteen statuses follow a telecalling day: New → Contacted → Interested → Quote Sent → Documents Pending → Policy Sold',
            'While a lead is being worked it needs a next action and a date — this is what stops leads going quiet',
            'Not Interested and Lost need a reason, so you can see why business is being lost'
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
        'leads': 'Leads',
        'deals': 'Pipeline Deals',
        'policies': 'Policies',
        'renewals': 'Renewals',
        'customers': 'Customers',
        'contacts': 'Contacts',
        'organizations': 'Organizations',
        'notes': 'Activity Notes',
        'tasks': 'Action Tasks',
        'follow-ups': 'Follow-ups',
        'automation': 'Automation',
        'performance': 'Performance',
        'reports': 'Reports',
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
        case 'follow-ups': loadFollowUps(); break;
        case 'automation': loadAutomation(); break;
        case 'performance': loadPerformance(); break;
        case 'reports': loadReports(); break;
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
    document.getElementById('renewal-dashboard-section').classList.toggle('hidden',policies);
    document.getElementById('insurance-kpis').classList.toggle('hidden',!policies);
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
        if (currentView === 'renewals') await loadRenewalDashboard();
    } catch (e) {
        showToast(e.message);
    }
}

function renderQuotationComparison(quotes, renewals) {
    const root = document.getElementById('quotation-comparison');
    if (!root) return;
    const lowest = quotes.length ? Math.min(...quotes.map(q => Number(q.premium || 0))) : 0;
    const deals = window.crmDeals || [];
    root.innerHTML = quotes.length ? quotes.map(q => {
        let parentLabel = 'Unlinked Quotation';
        let contextType = 'renewal';
        let contextId = q.renewalId || '';
        let selected = false;
        let approvalEvents = 0;

        if (q.renewalId) {
            const renewal = renewals.find(r => r.id === q.renewalId) || {};
            parentLabel = `Renewal: ${renewal.customerName || q.renewalId}`;
            selected = renewal.selectedQuotationId === q.id;
            approvalEvents = renewal.approvalHistory?.length || 0;
            contextType = 'renewal';
            contextId = q.renewalId;
        } else if (q.dealId) {
            const deal = deals.find(d => d.id === q.dealId) || {};
            parentLabel = `Deal: ${deal.dealName || deal.title || q.dealId}`;
            selected = deal.selectedQuotationId === q.id;
            contextType = 'deal';
            contextId = q.dealId;
        } else if (q.leadId) {
            parentLabel = `Lead: ${q.leadId}`;
            contextType = 'lead';
            contextId = q.leadId;
        }

        return `<div class="border ${selected ? 'border-emerald-500 ring-1 ring-emerald-200' : 'border-slate-200'} rounded-lg p-3 bg-white">
            <div class="flex justify-between gap-2"><div><div class="font-semibold text-slate-900">${esc(q.insurer)}</div><div class="text-[11px] text-slate-500">${esc(parentLabel)}</div></div><div class="font-mono font-semibold text-slate-900">₹${Number(q.premium || 0).toLocaleString('en-IN')}</div></div>
            <div class="text-[10px] mt-2 ${Number(q.premium||0)===lowest?'text-emerald-700 font-semibold':'text-slate-500'}">${Number(q.premium||0)===lowest?'Lowest premium':`₹${(Number(q.premium||0)-lowest).toLocaleString('en-IN')} above lowest`}</div>
            <div class="text-[11px] text-slate-600 mt-2">Sum insured: ₹${Number(q.sumInsured || 0).toLocaleString('en-IN')} · Deductible: ₹${Number(q.deductible || 0).toLocaleString('en-IN')}</div>
            <div class="text-[11px] text-slate-500 mt-1">${esc(q.coverageSummary || 'No coverage summary')}</div>
            ${approvalEvents ? `<div class="text-[10px] text-slate-400 mt-2">${approvalEvents} approval event(s) recorded</div>` : ''}
            <div class="mt-3 flex gap-2">
                <button onclick="selectQuotationUnified('${contextType}','${contextId}','${q.id}')" class="flex-1 py-1.5 rounded text-xs font-semibold ${selected ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-900 text-white'}">${selected ? 'Selected' : 'Select quotation'}</button>
                ${contextId ? `<button onclick="openSideBySideQuoteComparison('${contextType}','${contextId}')" class="px-2.5 py-1.5 border border-slate-300 rounded text-xs font-semibold text-slate-700 hover:bg-slate-50" title="Compare side-by-side">Matrix</button>` : ''}
            </div>
        </div>`;
    }).join('') : '<div class="text-xs text-slate-400">No quotations recorded yet.</div>';
}

const renderQuoteComparison = renderQuotationComparison;
const compareQuotes = (...args) => openSideBySideQuoteComparison(...args);
const quotationComparison = (...args) => openSideBySideQuoteComparison(...args);

async function selectQuotation(renewalId, quotationId) {
    return selectQuotationUnified('renewal', renewalId, quotationId);
}

async function selectQuotationUnified(contextType, contextId, quoteId) {
    try {
        if (contextType === 'renewal' && contextId) {
            await apiJson(`/api/renewals/${contextId}`, {
                method: 'PUT',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({selectedQuotationId: quoteId, stage: 'Quotation Sent'})
            });
            showToast('Renewal quotation selected');
            await loadInsuranceOperations();
        } else if (contextType === 'deal' && contextId) {
            const quotes = await apiJson('/api/quotations').catch(() => []);
            const quote = quotes.find(q => q.id === quoteId);
            await apiJson(`/api/deals/${contextId}`, {
                method: 'PUT',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({
                    selectedQuotationId: quoteId,
                    stage: 'Quotation Sent',
                    annualRevenue: quote?.premium || 0
                })
            });
            showToast('Deal quotation selected');
            await loadDeals();
            if (['policies','renewals'].includes(currentView)) await loadInsuranceOperations();
        } else if (contextType === 'lead' && contextId) {
            // The customer chose this quote. A quote they accept has necessarily been sent to them.
            const quote = (await apiJson(`/api/quotations?leadId=${encodeURIComponent(contextId)}`)).find(q => q.id === quoteId);
            if (quote?.status === 'Draft') await setQuoteStatus(quoteId, 'Sent', true);
            await setQuoteStatus(quoteId, 'Accepted', true);
            showToast('Quotation accepted — collect the documents next');
            openLeadDrawer(contextId);
        } else {
            showToast('Cannot select quotation: unlinked context');
        }
        closeQuoteComparisonModal();
    } catch (e) {
        showToast(e.message);
    }
}

async function openSideBySideQuoteComparison(contextType, contextId) {
    const [allQuotes, renewals, deals] = await Promise.all([
        apiJson('/api/quotations').catch(() => []),
        cachedRenewals.length ? Promise.resolve(cachedRenewals) : apiJson('/api/renewals').catch(() => []),
        window.crmDeals?.length ? Promise.resolve(window.crmDeals) : apiJson('/api/deals').catch(() => [])
    ]);

    let title = 'Comparative Quotation Analysis';
    let filteredQuotes = [];
    let selectedQuoteId = null;

    if (contextType === 'renewal') {
        const r = renewals.find(x => x.id === contextId);
        title = `Quotation Comparison — ${r?.customerName || 'Renewal'} (${r?.policyNumber || contextId})`;
        filteredQuotes = allQuotes.filter(q => q.renewalId === contextId);
        selectedQuoteId = r?.selectedQuotationId;
    } else if (contextType === 'deal') {
        const d = deals.find(x => x.id === contextId);
        title = `Quotation Comparison — Deal: ${d?.dealName || d?.title || contextId}`;
        filteredQuotes = allQuotes.filter(q => q.dealId === contextId);
        selectedQuoteId = d?.selectedQuotationId;
    } else if (contextType === 'lead') {
        const lead = (await apiJson(`/api/leads/${contextId}`)).lead;
        title = `Quotation comparison — ${lead?.name || 'Lead'}`;
        filteredQuotes = allQuotes.filter(q => q.leadId === contextId && q.status !== 'Rejected');
        selectedQuoteId = filteredQuotes.find(q => q.status === 'Accepted')?.id;
    } else {
        filteredQuotes = allQuotes;
    }

    const modal = document.getElementById('quote-comparison-modal');
    if (!modal) return;
    document.getElementById('quote-modal-title').textContent = title;
    document.getElementById('quote-modal-subtitle').textContent = `${filteredQuotes.length} competing quote(s) received`;

    const body = document.getElementById('quote-modal-body');
    if (!filteredQuotes.length) {
        body.innerHTML = `
            <div class="py-12 text-center">
                <p class="text-xs text-slate-500">No quotes recorded for this record yet.</p>
                <button onclick="closeQuoteComparisonModal(); openQuotationModalPrompt('${contextType}', '${contextId}')" class="mt-3 px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold hover:bg-black">+ Add Quote</button>
            </div>
        `;
        modal.classList.remove('hidden');
        return;
    }

    const lowest = Math.min(...filteredQuotes.map(q => Number(q.premium || 0)));
    const todayStr = new Date().toISOString().slice(0, 10);

    body.innerHTML = `
        <div class="overflow-x-auto">
            <table class="w-full border-collapse text-left text-xs corp-table">
                <thead>
                    <tr class="bg-slate-50 border-b border-slateBorder">
                        <th class="p-3 font-semibold text-slate-700 w-44">Comparison Feature</th>
                        ${filteredQuotes.map(q => `
                            <th class="p-3 font-semibold text-slate-900 border-l border-slateBorder min-w-[200px]">
                                <div class="flex items-center justify-between">
                                    <span>${esc(q.insurer)}</span>
                                    ${q.id === selectedQuoteId ? '<span class="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold">Selected</span>' : ''}
                                </div>
                            </th>
                        `).join('')}
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100">
                    <tr>
                        <td class="p-3 font-medium text-slate-600 bg-slate-50/50">Net Premium</td>
                        ${filteredQuotes.map(q => {
                            const prem = Number(q.premium || 0);
                            const isLowest = prem === lowest;
                            return `
                                <td class="p-3 border-l border-slateBorder ${isLowest ? 'bg-emerald-50/30' : ''}">
                                    <div class="font-mono font-semibold text-sm ${isLowest ? 'text-emerald-800' : 'text-slate-900'}">₹${prem.toLocaleString('en-IN')}</div>
                                    <div class="text-[10px] ${isLowest ? 'text-emerald-700 font-bold' : 'text-slate-400'}">${isLowest ? '★ Lowest Premium' : `+₹${(prem - lowest).toLocaleString('en-IN')}`}</div>
                                </td>
                            `;
                        }).join('')}
                    </tr>
                    <tr>
                        <td class="p-3 font-medium text-slate-600 bg-slate-50/50">Sum Insured</td>
                        ${filteredQuotes.map(q => `
                            <td class="p-3 border-l border-slateBorder font-mono">₹${Number(q.sumInsured || 0).toLocaleString('en-IN')}</td>
                        `).join('')}
                    </tr>
                    <tr>
                        <td class="p-3 font-medium text-slate-600 bg-slate-50/50">Deductible</td>
                        ${filteredQuotes.map(q => `
                            <td class="p-3 border-l border-slateBorder font-mono">₹${Number(q.deductible || 0).toLocaleString('en-IN')}</td>
                        `).join('')}
                    </tr>
                    <tr>
                        <td class="p-3 font-medium text-slate-600 bg-slate-50/50">Valid Until</td>
                        ${filteredQuotes.map(q => {
                            const isExpired = q.validityDate && q.validityDate < todayStr;
                            return `
                                <td class="p-3 border-l border-slateBorder">
                                    <span class="font-mono ${isExpired ? 'text-rose-600 font-bold' : 'text-slate-700'}">${esc(q.validityDate || 'Not specified')}</span>
                                    ${isExpired ? '<span class="ml-1.5 px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 text-[10px]">Expired</span>' : ''}
                                </td>
                            `;
                        }).join('')}
                    </tr>
                    <tr>
                        <td class="p-3 font-medium text-slate-600 bg-slate-50/50">Coverage Terms</td>
                        ${filteredQuotes.map(q => `
                            <td class="p-3 border-l border-slateBorder text-slate-600 leading-relaxed">${esc(q.coverageSummary || 'Standard coverage terms')}</td>
                        `).join('')}
                    </tr>
                    <tr class="bg-slate-50/50">
                        <td class="p-3 font-medium text-slate-600">Decision</td>
                        ${filteredQuotes.map(q => {
                            const isSelected = q.id === selectedQuoteId;
                            const isExpired = q.validityDate && q.validityDate < todayStr;
                            return `
                                <td class="p-3 border-l border-slateBorder">
                                    ${isSelected ? `
                                        <button disabled class="w-full py-1.5 px-3 rounded text-xs font-semibold bg-emerald-100 text-emerald-800">Current Choice</button>
                                    ` : `
                                        <button onclick="selectQuotationUnified('${contextType}','${contextId}','${q.id}')" ${isExpired ? 'disabled title="Cannot select expired quotation"' : ''} class="w-full py-1.5 px-3 rounded text-xs font-semibold ${isExpired ? 'bg-slate-200 text-slate-400 cursor-not-allowed' : 'bg-slate-900 hover:bg-black text-white'}">
                                            ${isExpired ? 'Expired' : 'Select Quote'}
                                        </button>
                                    `}
                                </td>
                            `;
                        }).join('')}
                    </tr>
                </tbody>
            </table>
        </div>
    `;
    modal.classList.remove('hidden');
}

function closeQuoteComparisonModal() {
    document.getElementById('quote-comparison-modal')?.classList.add('hidden');
}

function openQuotationModalPrompt(targetType = null, targetId = null) {
    const deals = window.crmDeals || [];
    const renewals = cachedRenewals || [];

    const targetPairs = [
        'none::-- Select Associated Opportunity / Renewal --',
        ...renewals.map(r => `renewal_${r.id}::Renewal: ${r.customerName} (${r.policyNumber || r.id})`),
        ...deals.map(d => `deal_${d.id}::Deal: ${d.dealName || d.title} (${d.organization || d.id})`)
    ].join('|');

    let initialTarget = 'none';
    if (targetType === 'renewal' && targetId) initialTarget = `renewal_${targetId}`;
    if (targetType === 'deal' && targetId) initialTarget = `deal_${targetId}`;

    openInsuranceForm('Add Insurer Quotation', [
        ['target', 'Associated Renewal or Deal', 'selectpairs:' + targetPairs, true],
        ['insurer', 'Insurer Name', 'text', true],
        ['premium', 'Quoted Net Premium (₹)', 'number', true],
        ['sumInsured', 'Sum Insured (₹)', 'number', false],
        ['deductible', 'Deductible (₹)', 'number', false],
        ['validityDate', 'Quotation Validity Expiry', 'date', false],
        ['coverageSummary', 'Coverage & Terms Summary', 'textarea', false]
    ], async values => {
        const payload = {
            insurer: values.insurer,
            premium: Number(values.premium || 0),
            sumInsured: Number(values.sumInsured || 0),
            deductible: Number(values.deductible || 0),
            validityDate: values.validityDate || null,
            coverageSummary: values.coverageSummary || '',
            status: 'Draft'
        };

        if (values.target?.startsWith('renewal_')) {
            payload.renewalId = values.target.replace('renewal_', '');
        } else if (values.target?.startsWith('deal_')) {
            payload.dealId = values.target.replace('deal_', '');
        }

        await apiJson('/api/quotations', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        if (payload.renewalId) {
            await apiJson(`/api/renewals/${payload.renewalId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({stage: 'Quotation Requested'})
            }).catch(() => {});
        }

        showToast('Quotation recorded');
        if (['policies','renewals'].includes(currentView)) await loadInsuranceOperations();
        if (currentView === 'deals') await loadDeals();
    }, {target: initialTarget});
}

function addDealQuotation(dealId) {
    openQuotationModalPrompt('deal', dealId);
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

// Slide 24: due this month and next, renewed, lost, renewal rate, and each telecaller's
// renewed against pending. Slide 23's reminder ladder shows how many sit at each stage.
async function loadRenewalDashboard() {
    const input = document.getElementById('renewal-dashboard-month');
    const root = document.getElementById('renewal-dashboard-body');
    if (!input || !root) return;
    try {
        const d = await apiJson(`/api/renewals/dashboard${input.value ? `?month=${encodeURIComponent(input.value)}` : ''}`);
        input.value = d.month;
        const tile = (label, value, note = '') => `<div class="border border-slateBorder rounded-lg p-3"><div class="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">${label}</div><div class="text-xl font-semibold mt-1 num-tabular">${value}</div>${note ? `<div class="text-[11px] text-slate-500 mt-0.5">${note}</div>` : ''}</div>`;
        const rate = d.renewalRate === null ? '—' : `${d.renewalRate}%`;
        root.innerHTML = `
            <div class="grid grid-cols-2 md:grid-cols-6 gap-3">
                ${tile('Due this month', d.dueThisMonth)}${tile('Due next month', d.dueNextMonth)}${tile('Renewed', d.renewed, d.premiumRenewed ? `₹${Number(d.premiumRenewed).toLocaleString('en-IN')}` : '')}
                ${tile('Pending', d.pending)}${tile('Lost', d.lost)}${tile('Renewal rate', rate, d.dueThisMonth ? `${d.renewed} of ${d.dueThisMonth}` : 'Nothing due this month')}
            </div>
            <div class="grid md:grid-cols-2 gap-4">
                <div><h3 class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Open renewals by reminder stage</h3>
                    <div class="flex flex-wrap gap-2">${d.ladder.map(s => `<span class="px-2 py-1 rounded border text-[11px] ${s.stage.startsWith('Expired') && s.count ? 'border-red-200 bg-red-50 text-red-700' : 'border-slate-200 bg-slate-50'}">${esc(s.stage)} <strong class="num-tabular">${s.count}</strong></span>`).join('')}</div></div>
                <div><h3 class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">By telecaller — ${esc(d.month)}</h3>
                    ${d.byEmployee.length ? `<table class="w-full text-left corp-table"><thead><tr><th>Telecaller</th><th>Renewed</th><th>Pending</th><th>Lost</th></tr></thead><tbody>${d.byEmployee.map(r => `<tr><td>${esc(r.person)}</td><td class="num-tabular">${r.renewed}</td><td class="num-tabular">${r.pending}</td><td class="num-tabular">${r.lost}</td></tr>`).join('')}</tbody></table>` : '<p class="text-xs text-slate-400">No renewals fall due this month.</p>'}</div>
            </div>`;
    } catch (e) { root.innerHTML = `<p class="text-xs text-red-600">${esc(e.message)}</p>`; }
}

function renderRenewals(items) {
    const body = document.getElementById('renewals-table-body');
    const stages = ['Upcoming', 'Due Soon', 'Contacted', 'Quotation Requested', 'Quotation Sent', 'Negotiation', 'Renewed', 'Lost', 'Lapsed'];
    body.innerHTML = items.length ? items.map(r => `<tr>
        <td><div class="font-medium">${esc(r.customerName)}</div><div class="text-[11px] text-slate-500">${esc(r.policyNumber || 'Policy')}</div></td>
        <td><div class="font-mono text-xs">${esc(r.expiryDate || '—')}</div>${r.ladderStage ? `<div class="text-[10px] mt-0.5 ${r.daysToExpiry < 0 ? 'text-red-700 font-semibold' : r.daysToExpiry <= 7 ? 'text-amber-700 font-semibold' : 'text-slate-500'}">${esc(r.ladderStage)}</div>` : ''}</td><td>${esc(r.assignedTo || 'Unassigned')}</td>
        <td><div>${esc(r.nextAction)}</div><div class="text-[11px] text-slate-500">${esc(r.nextActionDate || 'No date')}</div></td>
        <td class="font-mono">₹${Number(r.targetPremium || 0).toLocaleString('en-IN')}</td>
        <td><select class="corp-input py-1 text-[11px]" onchange="changeRenewalStage('${r.id}', this.value)">${stages.map(s => `<option ${s === r.stage ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
        <td><div class="flex gap-2"><button onclick="addQuotation('${r.id}')" class="text-[11px] font-semibold text-slate-700 hover:text-black">Add quote</button><button onclick="openSideBySideQuoteComparison('renewal','${r.id}')" class="text-[11px] font-semibold text-indigo-700 hover:text-indigo-900">Compare</button><button onclick="openCalendarEventForm('Renewal','${r.id}')" class="text-[11px] font-semibold">Schedule</button>${r.selectedQuotationId && r.stage !== 'Renewed' ? `<button onclick="completeRenewal('${r.id}')" class="text-[11px] font-semibold text-emerald-700">Complete</button>` : ''}</div></td>
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
        document.getElementById('leads-count-info').textContent = `Displaying ${first}–${last} of ${result.total} leads`;
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
                            <div class="text-[11px] text-slate-500 font-medium">${esc(productLine(l))}</div>
                        </div>
                    </div>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder">${priorityBadge(l)}</td>
                <td class="px-4 py-2.5 border-r border-slateBorder" onclick="event.stopPropagation()">
                    <button onclick="openStageTransitionModal('${l.id}', '${l.status}')" class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium transition-all ${stagePillClass(l.status)}" title="Click to transition stage">
                        <span>${esc(l.status)}</span>
                        <svg class="w-2.5 h-2.5 opacity-60 ml-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder">
                    <div class="flex items-center justify-between gap-2">
                        <span class="text-slate-800 font-medium truncate max-w-[230px]" title="${esc(l.nextAction)}">${esc(l.nextAction || (needsNextAction(l.status) ? 'No next action set' : '—'))}</span>
                        ${l.nextActionDate ? `<span class="text-[10px] px-1.5 py-0.2 rounded font-mono font-medium flex-shrink-0 ${isOverdue ? 'bg-rose-50 text-rose-700 border border-rose-200 font-bold' : (isDueToday ? 'bg-amber-50 text-amber-800 border border-amber-200' : 'bg-slate-100 text-slate-600')}">
                            ${formatDueBadge(l.nextActionDate, l.daysRemaining)}
                        </span>` : ''}
                    </div>
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder font-mono font-semibold text-slate-900 num-tabular">
                    ${esc(l.premium || '—')}
                </td>
                <td class="px-4 py-2.5 border-r border-slateBorder text-slate-700 font-medium">
                    ${esc(l.assignedTo || 'Unassigned')}
                </td>
                <td class="px-2 py-2.5 text-center whitespace-nowrap" onclick="event.stopPropagation()">
                    ${needsNextAction(l.status) ? callButton(l.id, '') : ''}
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
            <div class="w-64 kanban-col flex flex-col max-h-full flex-shrink-0">
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
                                <div class="text-[11px] text-slate-500 font-medium truncate">${esc(productLine(l))}</div>
                            </div>

                            ${l.nextAction ? `<div class="p-1.5 rounded bg-slate-50 border border-slate-100 text-[11px] space-y-0.5">
                                <div class="text-[10px] text-slate-400 uppercase font-medium">Next Action</div>
                                <div class="text-slate-800 font-medium truncate">${esc(l.nextAction)}</div>
                                <div class="text-[10px] text-slate-500 font-mono">${esc(l.nextActionDate || '')}</div>
                            </div>` : ''}

                            <div class="flex items-center justify-between gap-2 pt-1 text-[11px]">
                                ${priorityBadge(l)}
                                <span class="font-mono font-bold text-slate-900 num-tabular">${esc(l.premium || '')}</span>
                                <span class="text-[10px] text-slate-400 truncate">${esc(l.assignedTo || 'Unassigned')}</span>
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
async function openStageTransitionModal(leadId, targetStage, { fresh = false } = {}) {
    let lead = fresh ? null : cachedLeads.find(l => l.id === leadId);
    if (!lead) { try { lead = (await apiJson(`/api/leads/${leadId}`)).lead; } catch (e) { return; } }
    await loadLeadOptions();
    const target = targetStage || lead.status;
    document.getElementById('stage-modal-lead-id').value = lead.id;
    document.getElementById('stage-modal-lead-name').textContent = [lead.name, lead.product].filter(Boolean).join(' · ');
    document.getElementById('stage-modal-old-stage').textContent = lead.status;
    document.getElementById('stage-modal-new-stage').innerHTML = optionsHtml(STAGES, target);
    document.getElementById('next-action-suggestions').innerHTML = NEXT_ACTIONS.map(a => `<option value="${esc(a)}"></option>`).join('');
    document.getElementById('close-reason-suggestions').innerHTML = (leadOptions.closeReasons || []).map(r => `<option value="${esc(r)}"></option>`).join('');
    const keepCurrent = target === lead.status && lead.nextAction && !lead.nextActionCompleted;
    document.getElementById('stage-modal-custom-action').value = keepCurrent ? lead.nextAction : (STATUS_NEXT_ACTION[target] || '');
    document.getElementById('stage-modal-action-date').value = keepCurrent && lead.nextActionDate ? lead.nextActionDate : isoDay(1);
    document.getElementById('stage-modal-action-time').value = keepCurrent ? (lead.nextActionTime || '') : '';
    document.getElementById('stage-modal-lost-reason').value = '';
    document.getElementById('stage-modal-note').value = '';
    updateStageFields(target);
    document.getElementById('stage-transition-modal').classList.remove('hidden');
}

// A finished lead has nothing to schedule; closing one needs a reason.
function updateStageFields(status) {
    const open = needsNextAction(status);
    document.getElementById('stage-modal-next-container').classList.toggle('hidden', !open);
    document.getElementById('stage-modal-custom-action').required = open;
    document.getElementById('stage-modal-action-date').required = open;
    document.getElementById('stage-modal-lost-container').classList.toggle('hidden', !needsReason(status));
    document.getElementById('stage-modal-lost-reason').required = needsReason(status);
    // Replace our own suggestion as the status changes, but never something the telecaller typed.
    const action = document.getElementById('stage-modal-custom-action');
    const suggested = Object.values(STATUS_NEXT_ACTION);
    if (open && (!action.value || suggested.includes(action.value))) action.value = STATUS_NEXT_ACTION[status] || action.value;
}

function closeStageTransitionModal() {
    document.getElementById('stage-transition-modal').classList.add('hidden');
}

async function handleStageTransitionSubmit(e) {
    e.preventDefault();
    const leadId = document.getElementById('stage-modal-lead-id').value;
    const status = document.getElementById('stage-modal-new-stage').value;
    const body = { status, stageNote: document.getElementById('stage-modal-note').value.trim() };
    if (needsNextAction(status)) {
        body.nextAction = document.getElementById('stage-modal-custom-action').value.trim();
        body.nextActionDate = document.getElementById('stage-modal-action-date').value;
        body.nextActionTime = document.getElementById('stage-modal-action-time').value;
    }
    if (needsReason(status)) body.lostReason = document.getElementById('stage-modal-lost-reason').value.trim();
    try {
        await apiJson(`/api/leads/${leadId}/stage`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        closeStageTransitionModal();
        showToast(needsNextAction(status) ? `Now ${status} — next: ${body.nextAction}` : `Marked ${status}`);
        if (currentView === 'follow-ups') loadFollowUps(); else loadLeads();
        if (document.getElementById('detail-drawer')?.classList.contains('translate-x-0')) openLeadDrawer(leadId);
    } catch (err) {
        showToast(err.message || 'Could not update the status.');
    }
}

// ═══════════════════════════════════════════════════════════════════
// 3. 360° LEAD DETAIL DRAWER
// ═══════════════════════════════════════════════════════════════════
function nextActionCard(l) {
    const open = needsNextAction(l.status);
    if (!open) return `<div class="p-3 rounded-lg border border-slate-200 bg-slate-50/70 text-xs text-slate-600">
        ${esc(l.status)} — nothing further is scheduled.${l.lostReason && needsReason(l.status) ? ` Reason: ${esc(l.lostReason)}` : ''}</div>`;
    // A finished follow-up with nothing after it is exactly how customers get forgotten.
    if (!l.nextAction || l.nextActionCompleted) return `
        <div class="p-3 rounded-lg border border-amber-300 bg-amber-50 space-y-2 text-xs">
            <div class="font-semibold text-amber-900">No next action scheduled</div>
            <p class="text-amber-800">${l.nextAction ? `“${esc(l.nextAction)}” is done.` : ''} Decide what happens next so this customer isn't forgotten.</p>
            <button onclick="openStageTransitionModal('${l.id}', '${esc(l.status)}', { fresh: true })" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Schedule next action</button>
        </div>`;
    const today = localCalendarDate();
    const late = l.nextActionDate && l.nextActionDate < today;
    return `
        <div class="p-3 rounded-lg border ${late ? 'border-rose-300 bg-rose-50/60' : 'border-slate-300 bg-slate-50/70'} space-y-2">
            <div class="flex items-center justify-between">
                <span class="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Next action</span>
                <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white border ${late ? 'border-rose-300 text-rose-700' : 'border-slate-200 text-slate-800'} font-bold">
                    ${late ? 'Overdue · ' : ''}${esc(l.nextActionDate)}${l.nextActionTime ? ` ${esc(l.nextActionTime)}` : ''}
                </span>
            </div>
            <div class="font-semibold text-slate-900 text-xs">${esc(l.nextAction)}</div>
            <div class="flex items-center justify-between pt-1 border-t border-slate-200 text-[11px]">
                <span class="text-slate-500">Telecaller: <strong>${esc(l.assignedTo || 'Unassigned')}</strong></span>
                <button onclick="openStageTransitionModal('${l.id}', '${esc(l.status)}', { fresh: true })" class="text-black font-semibold hover:underline">Reschedule / update →</button>
            </div>
        </div>`;
}

function detailCell(label, value, mono = false) {
    return `<div><span class="text-slate-400 block text-[10px]">${label}</span><span class="text-slate-800 ${mono ? 'font-mono' : 'font-medium'} break-words">${value ? esc(String(value)) : '<span class="text-slate-300">—</span>'}</span></div>`;
}

function vehicleSummary(v) {
    if (!v || !Object.values(v).some(x => x !== '' && x !== null && x !== undefined)) return '';
    const car = [v.make, v.model, v.variant].filter(Boolean).join(' ');
    const parts = [v.registrationNumber, car, v.manufactureYear, v.fuelType, v.ncbPercent !== undefined && v.ncbPercent !== null ? `${v.ncbPercent}% NCB` : '',
        v.idv ? `IDV ₹${Number(v.idv).toLocaleString('en-IN')}` : '', v.previousClaims === true ? 'claimed last year' : ''].filter(Boolean);
    return `<div class="pt-2 border-t border-slate-100"><span class="text-slate-400 block text-[10px]">Car</span><span class="text-slate-800 font-medium">${esc(parts.join(' · '))}</span></div>`;
}

function healthSummary(h) {
    if (!h || !(h.members?.length || h.planType || h.sumInsured || h.preExistingConditions)) return '';
    const members = (h.members || []).map(m => `${m.relation} ${m.age}`).join(', ');
    const parts = [h.planType, members, h.sumInsured ? `cover ₹${Number(h.sumInsured).toLocaleString('en-IN')}` : '', h.preExistingConditions].filter(Boolean);
    return `<div class="pt-2 border-t border-slate-100"><span class="text-slate-400 block text-[10px]">Health</span><span class="text-slate-800 font-medium">${esc(parts.join(' · '))}</span></div>`;
}

async function openLeadDrawer(leadId) {
    try {
        const res = await fetch(`/api/leads/${leadId}`);
        if (!res.ok) return;
        const data = await res.json();
        const l = data.lead;
        const notes = data.notes || [];
        const docStatus = data.documentStatus || { required: [], missing: [] };
        const documents = await apiJson(`/api/documents?associatedId=${encodeURIComponent(leadId)}`);
        await loadLeadOptions();

        document.getElementById('drawer-title').textContent = l.name;
        document.getElementById('drawer-org').textContent = [productLine(l), l.source && l.source !== 'Not recorded' ? `via ${l.source}` : ''].filter(Boolean).join(' • ');

        const content = document.getElementById('drawer-content');
        content.innerHTML = `
            <div class="flex flex-wrap justify-end gap-2">${needsNextAction(l.status) || l.status === 'Policy Sold' ? callButton(l.id, 'Call now') : ''}<button onclick="openCalendarEventForm('Lead','${l.id}')" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold">Schedule activity</button><button onclick="openEditLead('${l.id}')" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Edit lead details</button></div>
            <!-- Stage Chevron Progression -->
            <div class="space-y-1.5 pb-3 border-b border-slateBorder">
                <div class="flex items-center justify-between">
                    <div class="text-[10px] uppercase font-semibold text-slate-500">Status</div>
                    ${priorityBadge(l)}
                </div>
                <div class="flex flex-wrap gap-1">
                    ${STAGES.map(stg => `<button onclick="openStageTransitionModal('${l.id}', '${esc(stg)}')" class="stage-step ${l.status === stg ? 'active' : ''} text-[10px] py-1 px-2">${esc(stg)}</button>`).join('')}
                </div>
            </div>

            ${await callHistoryCard(l.id)}

            ${await quotationsCard(l)}

            ${documentsCard(l, documents, docStatus)}

            <!-- Next action: what happens next with this customer -->
            ${nextActionCard(l)}

            <!-- What the customer has told us -->
            <div class="border border-slateBorder rounded-lg p-3 bg-white space-y-2 text-xs">
                <div class="text-[11px] font-bold text-slate-800 uppercase tracking-wider">Customer & cover</div>
                <div class="grid grid-cols-2 gap-2">
                    ${detailCell('Mobile', l.mobile, true)}
                    ${detailCell('Email', l.email, true)}
                    ${detailCell('Product', l.product || l.policyType)}
                    ${detailCell('City', l.city)}
                    ${detailCell('Current premium', l.premium, true)}
                    ${detailCell('Current policy expires', l.expiryDate ? `${l.expiryDate} (${formatDaysLeft(l.daysRemaining)})` : '')}
                    ${detailCell('Current insurer', l.existingPolicy?.insurer)}
                    ${detailCell('Lead source', l.sourceDetail ? `${l.source} (${l.sourceDetail})` : l.source)}
                    ${detailCell('Enquiry received', l.leadDate ? formatShortDate(l.leadDate) : (l.leadDateUnknown ? 'Not recorded' : ''))}
                    ${detailCell('Policy number', l.policyNumber, true)}
                </div>
                ${vehicleSummary(l.vehicleDetails)}${healthSummary(l.healthDetails)}
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

// ── Documents (slide 21): what the product needs, what has arrived, what is verified ──
const DOC_STATE = {
    missing: ['Missing', 'bg-rose-50 text-rose-700 border-rose-200'],
    pending: ['Awaiting check', 'bg-amber-50 text-amber-800 border-amber-200'],
    verified: ['Verified', 'bg-emerald-50 text-emerald-800 border-emerald-200'],
    rejected: ['Rejected', 'bg-rose-50 text-rose-700 border-rose-200'],
};
const docStateBadge = state => { const [label, cls] = DOC_STATE[state] || DOC_STATE.pending;
    return `<span class="inline-block px-1.5 py-0.5 rounded border text-[10px] font-semibold ${cls}">${label}</span>`; };

function documentsCard(l, documents, status) {
    const active = documents.filter(d => d.status === 'Active');
    const checklist = status.required.length ? `
        <div class="space-y-1">
            <div class="text-[10px] text-slate-400 uppercase font-medium">Needed for ${esc(status.product)}</div>
            ${status.required.map(r => `<div class="flex items-center justify-between gap-2 text-xs">
                <span class="font-medium text-slate-800">${esc(r.type)}</span>
                <span class="flex items-center gap-1.5">${r.note ? `<span class="text-[10px] text-rose-600 truncate max-w-[160px]" title="${esc(r.note)}">${esc(r.note)}</span>` : ''}${docStateBadge(r.state)}</span>
            </div>`).join('')}
            ${status.missing.length ? `<button type="button" onclick="requestMissingDocuments('${l.id}')" class="mt-1 w-full px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold hover:border-slate-500">Ask for ${esc(status.missing.join(', '))} on WhatsApp or email</button>`
                : `<p class="text-[11px] text-emerald-700 font-medium">Everything needed has arrived.</p>`}
        </div>` : `<p class="text-[11px] text-slate-400">${l.product ? `No documents are required for ${esc(l.product)}.` : 'Choose a product to see which documents are needed.'}</p>`;
    const types = leadOptions.documentTypes?.length ? leadOptions.documentTypes : ['Other'];
    const firstMissing = status.missing[0] || types[0];
    return `
        <div class="border border-slateBorder rounded-lg p-3 bg-white space-y-2.5">
            <div class="text-[11px] font-bold uppercase tracking-wider">Documents (${active.length})</div>
            ${checklist}
            <div class="flex flex-wrap gap-2 pt-2 border-t border-slate-100">
                <select id="lead-document-category" class="corp-input flex-1 min-w-[8rem]" aria-label="Document type">${optionsHtml(types, firstMissing)}</select>
                <input id="lead-document-file" type="file" class="corp-input flex-[2] min-w-[10rem]" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.csv,.txt" aria-label="Document file">
                <button onclick="uploadLeadDocument('${l.id}')" class="px-3 bg-slate-900 text-white rounded text-xs font-semibold">Upload</button>
            </div>
            <div class="space-y-1">${active.map(d => `
                <div class="text-xs flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-1.5">
                    <a class="font-medium underline truncate max-w-[45%]" href="/api/documents/${d.id}/content" target="_blank" rel="noopener">${esc(d.originalName)}</a>
                    <span class="flex items-center gap-1.5 text-slate-400">${esc(d.category)} · v${d.version} ${docStateBadge((d.verification || 'Pending').toLowerCase())}
                        ${canAssignLeads() && (d.verification || 'Pending') === 'Pending' ? `<button type="button" onclick="verifyDocument('${d.id}','Verified','${l.id}')" class="fu-btn">Verify</button><button type="button" onclick="verifyDocument('${d.id}','Rejected','${l.id}')" class="fu-btn">Reject</button>` : ''}
                    </span>
                </div>`).join('') || '<p class="text-xs text-slate-400">No documents uploaded.</p>'}</div>
        </div>`;
}

async function verifyDocument(id, verification, leadId) {
    let note = '';
    if (verification === 'Rejected') {
        note = prompt('Why is this document being rejected? The customer will need to know what to send instead.') || '';
        if (!note.trim()) return;
    }
    try {
        await apiJson(`/api/documents/${id}/verification`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ verification, note }) });
        showToast(verification === 'Verified' ? 'Document verified' : 'Document rejected');
        openLeadDrawer(leadId);
    } catch (e) { showToast(e.message); }
}

// Slide 19: request pending documents from the customer, naming exactly what is missing.
async function requestMissingDocuments(leadId) {
    const data = await apiJson(`/api/leads/${leadId}`);
    const l = data.lead, missing = data.documentStatus?.missing || [];
    if (!missing.length) return showToast('Nothing is missing');
    const first = (l.firstName || l.name || '').split(' ')[0];
    const draft = `Hello ${first}, to complete your ${l.product || 'insurance'} we still need: ${missing.join(', ')}. `
        + `You can reply to this message with a photo or PDF of each. Thank you.`;
    openSendMessage(leadId, draft);
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
                    <span class="font-medium text-slate-600">${esc(n.author || 'Unknown')}</span>
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

// ═══════════════════════════════════════════════════════════════════
// FOLLOW-UPS — slide 17: counters and the calling order
// ═══════════════════════════════════════════════════════════════════
let followUpData = null;
let followUpTab = 'dueToday';

async function loadFollowUps() {
    try {
        followUpData = await apiJson('/api/follow-ups');
    } catch (e) { showToast(e.message || 'Could not load follow-ups'); return; }
    const m = followUpData.metrics;
    const basis = m.onTimeBasis;
    // Status is carried by the rail and the wording, not by colour alone.
    const tiles = [
        ['Due today', m.dueToday, 'Still to do today', m.dueToday ? 'is-warning' : '', 'dueToday'],
        ['Overdue', m.overdue, 'Past their due time', m.overdue ? 'is-critical' : '', 'overdue'],
        ['Upcoming', m.upcoming, 'Scheduled after today', '', 'upcoming'],
        ['On-time rate', m.onTimeRate === null ? '—' : `${m.onTimeRate}%`,
            m.onTimeRate === null ? `Nothing fell due in the last ${basis.days} days`
                : `${basis.onTime} of ${basis.cameDue} on time · last ${basis.days} days`, m.onTimeRate >= 90 ? 'is-good' : '', ''],
    ];
    document.getElementById('fu-metrics').innerHTML = tiles.map(([label, value, note, tone, tab]) => `
        <${tab ? `button type="button" onclick="setFollowUpTab('${tab}')"` : 'div'} class="day-tile ${tone}">
            <strong>${esc(String(value))}</strong>
            <span class="font-medium text-slate-700">${esc(label)}</span>
            <span>${esc(note)}</span>
        </${tab ? 'button' : 'div'}>`).join('');
    ['overdue', 'dueToday', 'upcoming', 'doneToday'].forEach(key => {
        const el = document.querySelector(`[data-fu-count="${key}"]`);
        if (el) el.textContent = (followUpData[key] || []).length;
    });
    document.getElementById('fu-timezone').textContent = `Times shown in ${followUpData.timezone}`;
    // Open on the first list with something in it, rather than an empty "due today".
    if (!(followUpData[followUpTab] || []).length) {
        followUpTab = ['dueToday', 'overdue', 'upcoming'].find(k => followUpData[k].length) || followUpTab;
    }
    renderFollowUps();
}

function setFollowUpTab(tab) { followUpTab = tab; renderFollowUps(); }

function relativeTime(iso) {
    const then = new Date(iso); if (isNaN(then)) return '';
    const minutes = Math.round((Date.now() - then) / 60000);
    if (minutes < 60) return `${Math.max(minutes, 1)} min ago`;
    if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
    return `${Math.round(minutes / 1440)} d ago`;
}

function followUpWhen(r) {
    const today = localCalendarDate();
    const day = r.dueDate === today ? 'Today' : r.dueDate === isoDay(1) ? 'Tomorrow' : formatShortDate(r.dueDate);
    return `${day}${r.dueTime ? ` · ${r.dueTime}` : ''}`;
}

function renderFollowUps() {
    document.querySelectorAll('[data-fu-tab]').forEach(b => {
        const on = b.dataset.fuTab === followUpTab;
        b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on);
    });
    const rows = (followUpData?.[followUpTab]) || [];
    const empty = { overdue: 'Nothing overdue. Every follow-up is on track.', dueToday: 'Nothing left for today.',
        upcoming: 'Nothing scheduled after today yet.', doneToday: 'Nothing finished yet today.' }[followUpTab];
    const list = document.getElementById('fu-list');
    if (!rows.length) { list.innerHTML = `<p class="p-6 text-center text-xs text-slate-400">${empty}</p>`; return; }
    const done = followUpTab === 'doneToday', late = followUpTab === 'overdue';
    list.innerHTML = rows.map(r => `
        <div class="fu-row">
            <div class="fu-when ${late ? 'text-rose-700' : 'text-slate-700'}">
                <span class="font-mono font-semibold">${esc(done ? `Done ${relativeTime(r.completedAt)}` : followUpWhen(r))}</span>
            </div>
            <div class="min-w-0">
                <button type="button" onclick="${r.associatedType === 'Lead' ? `openLeadDrawer('${r.associatedId}')` : `openFollowUpRecord('${r.associatedType}','${r.associatedId}')`}"
                    class="font-semibold text-slate-900 hover:underline text-left truncate block max-w-full">${esc(r.customerName || 'General task')}</button>
                <span class="block text-[11px] text-slate-500 truncate">${esc([r.product, r.leadStatus].filter(Boolean).join(' · '))}</span>
            </div>
            <div>${r.leadPriority ? priorityBadge(r) : ''}</div>
            <div class="min-w-0">
                <span class="block text-slate-800 font-medium truncate">${esc(r.title)}</span>
                <span class="block text-[11px] text-slate-400 truncate">${r.lastInteraction ? `Last: ${esc(r.lastInteraction.what)} · ${relativeTime(r.lastInteraction.at)}` : 'No contact recorded yet'}</span>
            </div>
            <div class="text-[11px] text-slate-600 truncate">${esc(r.assignedTo || 'Unassigned')}</div>
            <div class="fu-actions">
                ${r.associatedType === 'Lead' && r.mobile ? callButton(r.associatedId) : r.mobile ? `<a href="tel:${esc(r.mobile.replace(/\s+/g, ''))}" class="fu-btn">Call</a>` : ''}
                ${done ? '' : `<button type="button" onclick="completeFollowUp('${r.id}')" class="fu-btn is-primary">Done</button>
                <button type="button" onclick="rescheduleFollowUp('${r.id}')" class="fu-btn">Reschedule</button>`}
            </div>
        </div>`).join('');
}

function findFollowUp(id) {
    return ['overdue', 'dueToday', 'upcoming'].flatMap(k => followUpData?.[k] || []).find(r => r.id === id);
}

// Finishing a lead's follow-up asks what happens next, so the lead is never left without one.
async function completeFollowUp(id) {
    const row = findFollowUp(id);
    try {
        await apiJson(`/api/tasks/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'Completed' }) });
        showToast('Follow-up done');
        await loadFollowUps();
        if (row?.associatedType === 'Lead' && row.leadStatus && needsNextAction(row.leadStatus)) {
            const next = ['New', 'Assigned'].includes(row.leadStatus) ? 'Contacted' : row.leadStatus;
            openStageTransitionModal(row.associatedId, next, { fresh: true });
        }
    } catch (e) { showToast(e.message || 'Could not update the follow-up'); }
}

function rescheduleFollowUp(id) {
    const row = findFollowUp(id); if (!row) return;
    if (row.associatedType === 'Lead' && row.leadStatus) { openStageTransitionModal(row.associatedId, row.leadStatus, { fresh: true }); return; }
    openInsuranceForm('Reschedule follow-up', [['dueDate', 'Due', 'date', true], ['dueTime', 'Time', 'time', false]], async v => {
        await apiJson(`/api/tasks/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
        await loadFollowUps();
    }, { dueDate: row.dueDate, dueTime: row.dueTime || '' });
}

function openFollowUpRecord(type, id) {
    // The 360° panel lives on the Customers screen, so go there first.
    if (type === 'Customer') { switchView('customers'); setTimeout(() => openCustomer360(id), 120); }
    else if (type === 'Policy' || type === 'Renewal') switchView(type === 'Policy' ? 'policies' : 'renewals');
}

// ═══════════════════════════════════════════════════════════════════
// ROLE-AWARE SCREENS — elements marked data-requires only show to those allowed
// ═══════════════════════════════════════════════════════════════════
function roleKey() {
    if (!signedInUser) return 'admin';                        // local mode without sign-in
    const r = String(signedInUser.role || '').toLowerCase();
    if (['admin', 'administrator', 'system administrator', 'owner', 'owner / admin'].includes(r)) return 'admin';
    if (['manager', 'team manager', 'sales manager'].includes(r)) return 'manager';
    if (['readonly', 'read-only', 'read-only auditor', 'auditor', 'viewer'].includes(r)) return 'readonly';
    return 'telecaller';
}

function applyRoleVisibility() {
    const role = roleKey();
    document.querySelectorAll('[data-requires]').forEach(el => {
        const need = el.dataset.requires;
        const allowed = need === 'admin' ? role === 'admin' : need === 'manage' ? ['admin', 'manager'].includes(role) : true;
        el.classList.toggle('hidden', !allowed);
    });
}

// ═══════════════════════════════════════════════════════════════════
// AUTOMATION — slide 33: when something happens, if it matches, then act
// ═══════════════════════════════════════════════════════════════════
let automationData = null, automationOptions = null, automationTab = 'rules', ruleDraft = null;

async function loadAutomation() {
    try {
        [automationData, automationOptions] = await Promise.all([apiJson('/api/automations'), apiJson('/api/automations/options')]);
    } catch (e) { showToast(e.message || 'Could not load automations'); return; }
    document.getElementById('auto-paused').checked = automationData.paused;
    document.getElementById('auto-paused-banner').classList.toggle('hidden', !automationData.paused);
    applyRoleVisibility();
    setAutomationTab(automationTab);
}

function setAutomationTab(tab) {
    automationTab = tab;
    document.querySelectorAll('[data-auto-tab]').forEach(b => { const on = b.dataset.autoTab === tab; b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on); });
    document.getElementById('auto-rules-pane').classList.toggle('hidden', tab !== 'rules');
    document.getElementById('auto-activity-pane').classList.toggle('hidden', tab !== 'activity');
    if (tab === 'rules') { renderRecipes(); renderAutomationRules(); } else loadAutomationRuns();
}

const quote = t => `“${esc(t)}”`;
function describeAction(a) {
    const p = a.params || {};
    switch (a.type) {
        case 'assign': { const how = (automationOptions.methods.find(m => m.method === p.method) || {}).label || '';
            return `assign it to <b>${esc((p.assignees || []).join(' or '))}</b>${how ? ` (${esc(how.toLowerCase())})` : ''}`; }
        case 'create_task': return `create a follow-up ${quote(p.title)} due ${Number(p.dueInDays) ? `in ${p.dueInDays} day${p.dueInDays == 1 ? '' : 's'}` : 'the same day'}`;
        case 'notify': return `notify <b>${esc({ assignee: 'the telecaller', manager: 'their manager', owner: 'the owner' }[p.to] || p.to)}</b>: ${quote(p.message)}`;
        case 'send_message': { const t = (automationOptions.whatsappTemplates || []).find(x => x.id === p.whatsappTemplateId);
            return `send the customer ${esc(p.channel === 'Email' ? 'an email' : 'a WhatsApp')}: ${t ? `template ${quote(t.name)}` : quote(p.text)}`; }
        case 'set_status': return `set the status to <b>${esc(p.status)}</b>`;
        case 'set_priority': return `set calling priority to <b>${esc(p.priority)}</b>`;
        case 'add_note': return `add a note ${quote(p.text)}`;
        case 'create_renewal': return 'open a renewal record';
        default: return esc(a.type);
    }
}

function describeRule(rule) {
    const t = rule.trigger || {}, spec = automationOptions.triggers[t.type] || { label: t.type };
    let when = esc(spec.label.charAt(0).toLowerCase() + spec.label.slice(1));
    if (t.params?.to) when += ` ${t.type === 'call.logged' ? 'with outcome' : 'to'} <b>${esc(t.params.to)}</b>`;
    if (t.params?.days !== undefined) when += ` (<b>${esc(t.params.days)}</b> ${esc((spec.params || [])[0]?.label || 'days')})`;
    const fields = automationOptions.fields[spec.record] || [];
    const ops = Object.fromEntries(automationOptions.operators.map(o => [o.op, o.label]));
    const ifs = (rule.conditions || []).map(c => `<b>${esc((fields.find(f => f.field === c.field) || {}).label || c.field)}</b> ${esc(ops[c.operator] || c.operator)}${c.operator === 'is_empty' ? '' : ` <b>${esc(c.value)}</b>`}`);
    return `<span class="auto-sentence"><b>When</b> ${when}${ifs.length ? ` · <b>if</b> ${ifs.join(' and ')}` : ''} · <b>then</b> ${(rule.actions || []).map(describeAction).join(', then ')}.</span>`;
}

function renderRecipes() {
    const admin = roleKey() === 'admin';
    document.getElementById('auto-recipes').innerHTML = automationData.recipes.map(r => {
        const rule = automationData.rules.find(x => x.id === r.ruleId);
        const [label, cls] = r.builtIn ? ['Built in', 'built'] : r.comingWith ? ['Coming later', 'later'] : rule ? (rule.enabled ? ['On', 'on'] : ['Off', 'off']) : ['Not added', 'off'];
        const body = r.builtIn || r.comingWith || (rule ? describeRule(rule) : esc(r.name));
        const button = r.builtIn || r.comingWith ? '' : rule ? `<button type="button" class="fu-btn" onclick="openRuleBuilder('${rule.id}')">${admin ? 'Edit' : 'View'}</button>`
            : admin ? `<button type="button" class="fu-btn is-primary" onclick="addRecipe('${r.key}')">Turn on</button>` : '';
        return `<div class="auto-card ${rule?.enabled ? '' : 'is-off'}"><div class="min-w-0 space-y-1">
                <div class="flex flex-wrap items-center gap-2"><span class="font-semibold text-slate-900">${esc(r.row)}</span><span class="auto-pill ${cls}">${label}</span></div>
                <div class="text-[11px] text-slate-500">${body}</div></div>${button}</div>`;
    }).join('');
}

function renderAutomationRules() {
    const admin = roleKey() === 'admin';
    const rules = automationData.rules;
    document.getElementById('auto-rules').innerHTML = rules.length ? rules.map((r, i) => `
        <div class="auto-card ${r.enabled ? '' : 'is-off'}">
            <div class="min-w-0 space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                    <span class="font-mono text-[10px] text-slate-400">${i + 1}</span>
                    <span class="font-semibold text-slate-900">${esc(r.name)}</span>
                    <span class="auto-pill ${r.enabled ? 'on' : 'off'}">${r.enabled ? 'On' : 'Off'}</span>
                </div>
                <div>${describeRule(r)}</div>
                <div class="text-[11px] text-slate-400">${r.runCount ? `Ran ${r.runCount} time${r.runCount === 1 ? '' : 's'} · last ${relativeTime(r.lastRunAt)}` : 'Has not run yet'}${(r.limits?.daysOfWeek || []).length ? ` · only on ${esc(r.limits.daysOfWeek.join(', '))}` : ''}</div>
            </div>
            <div class="flex flex-wrap gap-1.5 shrink-0">
                ${admin ? `<label class="auto-switch"><input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleAutomation('${r.id}', this.checked)"><span>On</span></label>
                <button type="button" class="fu-btn" onclick="moveAutomation('${r.id}','up')" aria-label="Try earlier" ${i === 0 ? 'disabled' : ''}>↑</button>
                <button type="button" class="fu-btn" onclick="moveAutomation('${r.id}','down')" aria-label="Try later" ${i === rules.length - 1 ? 'disabled' : ''}>↓</button>` : ''}
                <button type="button" class="fu-btn" onclick="openRuleBuilder('${r.id}')">${admin ? 'Edit' : 'View'}</button>
                ${admin ? `<button type="button" class="fu-btn" onclick="deleteAutomation('${r.id}')">Delete</button>` : ''}
            </div>
        </div>`).join('') : '<p class="text-xs text-slate-400 p-4 bg-white border border-slateBorder rounded-lg">No rules yet. Turn on one from the client’s plan above, or write your own with New rule.</p>';
}

async function automationCall(path, method, body) {
    try { await apiJson(path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }); await loadAutomation(); return true; }
    catch (e) { showToast(e.message); return false; }
}
const toggleAutomation = (id, enabled) => automationCall(`/api/automations/${id}`, 'PUT', { enabled }).then(ok => ok && showToast(enabled ? 'Rule switched on' : 'Rule switched off'));
const moveAutomation = (id, direction) => automationCall(`/api/automations/${id}/move`, 'POST', { direction });
const setAutomationPaused = paused => automationCall('/api/automations/pause', 'PUT', { paused }).then(ok => ok && showToast(paused ? 'Every automation is paused' : 'Automations resumed'));
async function addRecipe(key) { if (await automationCall(`/api/automations/recipes/${key}`, 'POST', {})) showToast('Rule switched on'); }
async function deleteAutomation(id) {
    const rule = automationData.rules.find(r => r.id === id);
    if (!await confirmDestructive({ title: `Delete “${rule?.name}”?`, body: 'The rule stops running and is removed. Its past activity stays in the log.', confirmLabel: 'Delete rule', tone: 'danger' })) return;
    if (await automationCall(`/api/automations/${id}`, 'DELETE')) showToast('Rule deleted');
}

async function loadAutomationRuns() {
    const runs = await apiJson('/api/automations/runs?limit=200');
    const results = { done: 'Done', partial: 'Partly done', blocked: 'Blocked', skipped: 'Skipped', failed: 'Failed' };
    document.getElementById('auto-runs').innerHTML = runs.length ? runs.map(r => `
        <tr><td class="whitespace-nowrap text-[11px] text-slate-500">${esc(formatShortDate(r.at))} ${esc(new Date(r.at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }))}</td>
            <td class="text-xs font-medium">${esc(r.ruleName || '—')}</td>
            <td class="text-xs">${esc(r.recordName || r.recordId)}</td>
            <td><span class="auto-pill ${r.status}">${results[r.status] || esc(r.status)}</span></td>
            <td class="text-[11px] text-slate-600">${r.reason ? esc(r.reason) : (r.actions || []).map(a => `${esc(a.detail || a.type)}${a.result === 'done' ? '' : ` — <em>${esc(a.result)}</em>`}`).join('<br>')}</td></tr>`).join('')
        : '<tr><td colspan="5" class="text-center text-xs text-slate-400 py-6">No automation has run yet.</td></tr>';
}

// ── The rule builder ──
function blankRule() {
    return { name: '', enabled: false, trigger: { type: 'lead.status_changed', params: {} }, conditions: [],
        actions: [{ type: 'create_task', params: { title: '', dueInDays: 0 } }], limits: { daysOfWeek: [], maxPerHour: automationOptions.defaultMaxPerHour } };
}

async function openRuleBuilder(id = '') {
    if (!automationOptions) automationOptions = await apiJson('/api/automations/options');
    const existing = id ? automationData.rules.find(r => r.id === id) : null;
    ruleDraft = JSON.parse(JSON.stringify(existing || blankRule()));
    ruleDraft.id = existing?.id || '';
    document.getElementById('insurance-form-title').textContent = existing ? (roleKey() === 'admin' ? 'Edit rule' : 'Rule') : 'New rule';
    renderRuleBuilder();
    document.getElementById('insurance-form-modal').classList.remove('hidden');
}

const selectHtml = (bind, pairs, value) => `<select data-bind="${bind}" class="corp-input">${pairs.map(([v, l]) => `<option value="${esc(String(v))}" ${String(v) === String(value ?? '') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
const inputHtml = (bind, value, attrs = '') => `<input data-bind="${bind}" value="${esc(String(value ?? ''))}" class="corp-input" ${attrs}>`;

function actionEditor(a, i) {
    const p = a.params || {}, b = k => `actions.${i}.params.${k}`, o = automationOptions;
    const label = (text, control, wide = false) => `<label class="block text-[11px] font-medium text-slate-600 ${wide ? 'sm:col-span-2' : ''}">${text}${control}</label>`;
    switch (a.type) {
        case 'assign': return `${label('Choose between', `<div class="flex flex-wrap gap-1.5 mt-1">${o.people.map(n => `<span class="auto-chip ${(p.assignees || []).includes(n) ? 'is-on' : ''}" onclick="toggleDraftList('${b('assignees')}','${esc(n)}')">${esc(n)}</span>`).join('')}</div>`, true)}
            ${label('How', selectHtml(b('method'), o.methods.map(m => [m.method, m.label]), p.method || 'least_busy'))}`;
        case 'create_task': return `${label('Follow-up', inputHtml(b('title'), p.title, 'placeholder="e.g. Send quotation to {{name}}"'), true)}
            ${label('Due in days (0 = same day)', inputHtml(b('dueInDays'), p.dueInDays ?? 0, 'type="number" min="0" max="365"'))}
            ${label('Time', inputHtml(b('dueTime'), p.dueTime, 'type="time"'))}`;
        case 'notify': return `${label('Who', selectHtml(b('to'), [['assignee', 'The telecaller'], ['manager', 'Their manager'], ['owner', 'The owner']], p.to || 'assignee'))}
            ${label('Message', inputHtml(b('message'), p.message, 'placeholder="e.g. {{name}} needs a call today"'), true)}`;
        case 'send_message': return `${label('By', selectHtml(b('channel'), [['WhatsApp', 'WhatsApp'], ['Email', 'Email']], p.channel || 'WhatsApp'))}
            ${label('Approved WhatsApp template', selectHtml(b('whatsappTemplateId'), [['', 'None — write the text'], ...(o.whatsappTemplates || []).map(t => [t.id, t.name])], p.whatsappTemplateId))}
            ${label('Message', `<textarea data-bind="${b('text')}" rows="2" class="corp-input">${esc(p.text || '')}</textarea>`, true)}
            <p class="text-[11px] text-slate-500 sm:col-span-2">Only sent to customers who haven't opted out. Outside WhatsApp's 24-hour window only an approved template can go, and nothing is sent during quiet hours — it waits for the morning.</p>`;
        case 'set_status': return `${label('Status', selectHtml(b('status'), o.statuses.map(x => [x, x]), p.status || o.statuses[0]))}
            ${label('Then', inputHtml(b('nextAction'), p.nextAction, 'placeholder="Next action, e.g. Call back"'))}
            ${label('Due in days', inputHtml(b('dueInDays'), p.dueInDays ?? 0, 'type="number" min="0"'))}
            ${label('Reason (when closing)', inputHtml(b('reason'), p.reason))}`;
        case 'set_priority': return label('Priority', selectHtml(b('priority'), [['HOT', 'HOT'], ['WARM', 'WARM'], ['COLD', 'COLD']], p.priority || 'HOT'));
        case 'add_note': return label('Note', inputHtml(b('text'), p.text), true);
        case 'create_renewal': return '<p class="text-[11px] text-slate-500 sm:col-span-2">Opens a renewal for the policy, owned by its telecaller, unless one is already open.</p>';
        default: return '';
    }
}

function renderRuleBuilder() {
    const o = automationOptions, d = ruleDraft, admin = roleKey() === 'admin';
    const spec = o.triggers[d.trigger.type], record = spec.record;
    const fields = (o.fields[record] || []).filter(f => !f.legacy || d.conditions.some(c => c.field === f.field));
    const triggerPairs = Object.entries(o.triggers).map(([k, v]) => [k, `${v.kind === 'time' ? 'Every day: ' : ''}${v.label}`]);
    const actionPairs = Object.entries(o.actions).filter(([, v]) => v.records.includes(record)).map(([k, v]) => [k, v.label]);
    const params = (spec.params || []).map(p => p.type === 'status' || p.type === 'outcome'
        ? `<label class="block text-[11px] font-medium text-slate-600">${esc(p.label)} ${selectHtml(`trigger.params.${p.name}`,
            [['', p.type === 'status' ? 'any status' : 'any outcome'], ...(p.type === 'status' ? o.statuses : o.outcomes).map(x => [x, x])], d.trigger.params?.[p.name])}</label>`
        : `<label class="block text-[11px] font-medium text-slate-600">${esc(p.label)} ${inputHtml(`trigger.params.${p.name}`, d.trigger.params?.[p.name] ?? p.default ?? '', p.type === 'int' ? 'type="number" min="0" max="365"' : '')}</label>`).join('');
    const form = document.getElementById('insurance-dynamic-form');
    form.innerHTML = `
        <fieldset ${admin ? '' : 'disabled'} class="space-y-3">
        <label class="block text-xs font-medium text-slate-700">Name ${inputHtml('name', d.name, 'placeholder="e.g. Quote interested customers the same day" required')}</label>
        <div class="auto-block"><h4>When</h4>
            ${selectHtml('trigger.type', triggerPairs, d.trigger.type)}
            ${params ? `<div class="grid grid-cols-2 gap-2">${params}</div>` : ''}</div>
        <div class="auto-block"><h4>If <span class="normal-case font-normal tracking-normal">— every condition must match; none means always</span></h4>
            ${d.conditions.map((c, i) => `<div class="auto-row">
                ${selectHtml(`conditions.${i}.field`, fields.map(f => [f.field, f.label]), c.field)}
                ${selectHtml(`conditions.${i}.operator`, o.operators.map(x => [x.op, x.label]), c.operator)}
                ${c.operator === 'is_empty' ? '<span></span>' : inputHtml(`conditions.${i}.value`, c.value)}
                <button type="button" class="fu-btn" onclick="removeDraftItem('conditions', ${i})" aria-label="Remove condition">✕</button></div>`).join('')}
            <button type="button" class="fu-btn justify-self-start" onclick="addDraftCondition()">+ Add condition</button></div>
        <div class="auto-block"><h4>Then</h4>
            ${d.actions.map((a, i) => `<div class="auto-action">
                <div class="flex gap-2">${selectHtml(`actions.${i}.type`, actionPairs, a.type)}<button type="button" class="fu-btn" onclick="removeDraftItem('actions', ${i})" aria-label="Remove action">✕</button></div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${actionEditor(a, i)}</div></div>`).join('')}
            <button type="button" class="fu-btn justify-self-start" onclick="addDraftAction()">+ Add action</button>
            <p class="text-[11px] text-slate-400">Placeholders: ${o.tokens.map(t => `<code class="msg-token">{{${t}}}</code>`).join(' ')}</p></div>
        <div class="auto-block"><h4>Limits</h4>
            <div class="flex flex-wrap gap-1.5">${o.weekdays.map(day => `<span class="auto-chip ${(d.limits?.daysOfWeek || []).includes(day) ? 'is-on' : ''}" onclick="toggleDraftList('limits.daysOfWeek','${day}')">${day.slice(0, 3)}</span>`).join('')}
                <span class="text-[11px] text-slate-400 self-center">${(d.limits?.daysOfWeek || []).length ? '' : 'every day'}</span></div>
            <label class="block text-[11px] font-medium text-slate-600">At most this many runs an hour ${inputHtml('limits.maxPerHour', d.limits?.maxPerHour ?? o.defaultMaxPerHour, 'type="number" min="1" max="5000"')}</label></div>
        </fieldset>
        <div id="rule-preview" class="text-[11px] text-slate-600"></div>
        <div class="pt-3 border-t border-slateBorder flex flex-wrap justify-end gap-2">
            <button type="button" onclick="closeInsuranceForm()" class="px-3 py-1.5 border border-slate-300 rounded text-xs">${admin ? 'Cancel' : 'Close'}</button>
            ${admin ? `<button type="button" onclick="previewRule()" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold">Try it on recent records</button>
            <button type="submit" class="px-4 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Save rule</button>` : ''}
        </div>`;
    // Structural choices re-render the builder so the right fields appear.
    form.querySelectorAll('[data-bind="trigger.type"], [data-bind$=".type"], [data-bind$=".operator"]').forEach(el => el.addEventListener('change', () => { collectRuleDraft(); renderRuleBuilder(); }));
    form.onsubmit = saveRuleDraft;
}

function setByPath(obj, path, value) {
    const keys = path.split('.'); let cur = obj;
    keys.slice(0, -1).forEach((k, i) => { if (cur[k] === undefined) cur[k] = /^\d+$/.test(keys[i + 1]) ? [] : {}; cur = cur[k]; });
    cur[keys[keys.length - 1]] = value;
}
function getByPath(obj, path) { return path.split('.').reduce((cur, k) => cur?.[k], obj); }

function collectRuleDraft() {
    const previousTrigger = ruleDraft.trigger.type;
    document.querySelectorAll('#insurance-dynamic-form [data-bind]').forEach(el => {
        let value = el.value;
        if (el.type === 'number') value = value === '' ? '' : Number(value);
        setByPath(ruleDraft, el.dataset.bind, value);
    });
    if (ruleDraft.trigger.type !== previousTrigger) {
        // A different record type: keep only what still makes sense.
        const record = automationOptions.triggers[ruleDraft.trigger.type].record;
        const fields = new Set((automationOptions.fields[record] || []).map(f => f.field));
        ruleDraft.trigger.params = {};
        ruleDraft.conditions = ruleDraft.conditions.filter(c => fields.has(c.field));
        ruleDraft.actions = ruleDraft.actions.filter(a => automationOptions.actions[a.type].records.includes(record));
        if (!ruleDraft.actions.length) ruleDraft.actions = [{ type: 'notify', params: { to: 'assignee', message: '' } }];
    }
    ruleDraft.actions.forEach(a => { a.params = a.params || {}; });
}

function toggleDraftList(path, value) {
    collectRuleDraft();
    const list = getByPath(ruleDraft, path) || [];
    setByPath(ruleDraft, path, list.includes(value) ? list.filter(v => v !== value) : [...list, value]);
    renderRuleBuilder();
}
function addDraftCondition() {
    collectRuleDraft();
    const record = automationOptions.triggers[ruleDraft.trigger.type].record;
    ruleDraft.conditions.push({ field: automationOptions.fields[record][0].field, operator: 'is', value: '' });
    renderRuleBuilder();
}
function addDraftAction() {
    collectRuleDraft();
    const record = automationOptions.triggers[ruleDraft.trigger.type].record;
    const first = Object.entries(automationOptions.actions).find(([k, v]) => v.records.includes(record) && k !== 'assign');
    ruleDraft.actions.push({ type: first[0], params: {} });
    renderRuleBuilder();
}
function removeDraftItem(list, index) { collectRuleDraft(); ruleDraft[list].splice(index, 1); renderRuleBuilder(); }

function draftPayload() {
    collectRuleDraft();
    const { id, runCount, lastRunAt, createdAt, createdBy, updatedAt, order, window: _w, matchCount, lastMatchedAt, recipe, ...body } = ruleDraft;
    return body;
}

async function previewRule() {
    const box = document.getElementById('rule-preview');
    try {
        const r = await apiJson('/api/automations/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draftPayload()) });
        box.innerHTML = `Checked the ${r.checked} most recent records: <b>${r.matched}</b> would match${r.examples.length ? ` — ${r.examples.map(e => esc(e.name)).join(', ')}` : ''}. Nothing was changed.`;
    } catch (e) { box.innerHTML = `<span class="text-rose-700">${esc(e.message)}</span>`; }
}

async function saveRuleDraft(event) {
    event.preventDefault();
    const body = draftPayload(), id = ruleDraft.id;
    try {
        await apiJson(id ? `/api/automations/${id}` : '/api/automations', { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        closeInsuranceForm();
        showToast(id ? 'Rule saved' : 'Rule saved — it is off until you switch it on');
        await loadAutomation();
    } catch (e) { document.getElementById('rule-preview').innerHTML = `<span class="text-rose-700">${esc(e.message)}</span>`; }
}

// ═══════════════════════════════════════════════════════════════════
// CALLING — slides 15–16: click to call, the customer on screen, an outcome that decides what's next
// ═══════════════════════════════════════════════════════════════════
let activeCall = null, callTimer = null, callOptions = null;
const PHONE_SVG = '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg>';
const callButton = (leadId, label = 'Call') => `<button type="button" class="btn-call" onclick="event.stopPropagation(); startCall('${leadId}')" title="Call and record the outcome">${PHONE_SVG}${label}</button>`;
const formatDuration = sec => sec === null || sec === undefined ? '—' : `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;

async function startCall(leadId) {
    try {
        if (!callOptions) callOptions = await apiJson('/api/calls/options');
        const data = await apiJson('/api/calls/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ leadId }) });
        openCallScreen(data, Date.now());
        if (data.dial) { const a = document.createElement('a'); a.href = data.dial; a.click(); }   // the phone dials
    } catch (e) { showToast(e.message || 'Could not start the call'); }
}

// An unfinished call can have its outcome recorded later, from the lead's call history.
async function resumeCall(callId, leadId) {
    if (!callOptions) callOptions = await apiJson('/api/calls/options');
    const [lead, calls] = await Promise.all([apiJson(`/api/leads/${leadId}`), apiJson(`/api/calls?leadId=${encodeURIComponent(leadId)}`)]);
    const call = calls.find(c => c.id === callId);
    openCallScreen({ call, lead: lead.lead, documentStatus: lead.documentStatus, previousCalls: calls.filter(c => c.id !== callId), dial: '' },
        new Date(call.startedAt).getTime());
    showCallOutcomes();
}

function openCallScreen(data, startedAt) {
    const l = data.lead;
    activeCall = { id: data.call.id, leadId: l.id, name: l.name, done: false };
    document.getElementById('call-title').textContent = `Calling ${l.name}`;
    document.getElementById('call-subtitle').textContent = [l.mobile, l.product, l.status].filter(Boolean).join(' · ');
    document.getElementById('call-instructions').textContent = data.instructions || 'Call in progress.';
    const link = document.getElementById('call-dial-link');
    link.href = data.dial || `tel:${(l.mobile || '').replace(/\s+/g, '')}`;
    link.innerHTML = `${PHONE_SVG} Dial ${esc(l.mobile || '')} again`;
    document.getElementById('call-notes').value = '';
    renderCallCustomer(data);
    backToCall();
    clearInterval(callTimer);
    const tick = () => { document.getElementById('call-timer').textContent = formatDuration(Math.max(0, Math.round((Date.now() - startedAt) / 1000))); };
    tick(); callTimer = setInterval(tick, 1000);
    document.getElementById('call-modal').classList.remove('hidden');
    document.getElementById('call-notes').focus();
}

function renderCallCustomer(data) {
    const l = data.lead, docs = data.documentStatus || { missing: [] };
    const row = (k, v) => v ? `<dt>${k}</dt><dd>${esc(String(v))}</dd>` : '';
    document.getElementById('call-customer').innerHTML = `
        <div class="flex flex-wrap items-center gap-2">${priorityBadge(l)}<span class="auto-pill off">${esc(l.status)}</span>
            ${l.nextAction ? `<span class="text-slate-500">Planned: <b class="text-slate-800">${esc(l.nextAction)}</b></span>` : ''}</div>
        <dl class="call-kv">
            ${row('Mobile', l.mobile)}${row('Product', l.product || l.policyType)}${row('City', l.city)}
            ${row('Current insurer', l.existingPolicy?.insurer)}${row('Policy expires', l.expiryDate ? `${l.expiryDate} (${formatDaysLeft(l.daysRemaining)})` : '')}
            ${row('Current premium', l.premium)}${row('Source', l.source)}${row('Email', l.email)}
            ${docs.missing.length ? row('Documents missing', docs.missing.join(', ')) : ''}
        </dl>
        ${vehicleSummary(l.vehicleDetails)}${healthSummary(l.healthDetails)}
        <div>
            <div class="text-[10px] uppercase font-bold tracking-wider text-slate-500 mb-1">Earlier calls</div>
            ${(data.previousCalls || []).map(c => `<div class="border-t border-slate-100 py-1.5">
                <div class="flex justify-between gap-2"><b class="text-slate-800">${esc(c.outcome || c.status)}</b>
                <span class="text-slate-400 font-mono">${esc(formatShortDate(c.startedAt || c.createdAt))} · ${formatDuration(c.durationSeconds)}</span></div>
                ${c.notes ? `<p class="text-slate-500 mt-0.5">${esc(c.notes)}</p>` : ''}</div>`).join('') || '<p class="text-slate-400">First call to this customer.</p>'}
        </div>`;
}

function backToCall() {
    document.getElementById('call-dialling').classList.remove('hidden');
    document.getElementById('call-outcome-form').classList.add('hidden');
}

function showCallOutcomes() {
    const groups = [['Spoke to the customer', true], ['Did not reach them', false]];
    document.getElementById('call-outcomes').innerHTML = groups.map(([title, connected]) => `
        <div class="call-group">${title}</div>
        ${callOptions.outcomes.filter(o => o.connected === connected).map(o => `
            <label class="call-outcome"><input type="radio" name="call-outcome" value="${esc(o.value)}" required onchange="renderOutcomeFields(this.value)">
                <span><b>${esc(o.label)}</b></span></label>`).join('')}`).join('');
    document.getElementById('call-outcome-fields').innerHTML = '';
    document.getElementById('call-outcome-error').textContent = '';
    document.getElementById('call-dialling').classList.add('hidden');
    document.getElementById('call-outcome-form').classList.remove('hidden');
}

// Each outcome asks only for what it needs.
function renderOutcomeFields(outcome) {
    const f = (id, label, type = 'text', attrs = '', wide = false) =>
        `<label class="block font-medium text-slate-700 ${wide ? 'col-span-2' : ''}">${label}<input id="${id}" type="${type}" class="corp-input mt-1" ${attrs}></label>`;
    const nextYear = (() => { const d = new Date(); d.setFullYear(d.getFullYear() + 1); d.setDate(d.getDate() - 1); return localCalendarDate(d); })();
    const fields = {
        'Call Back': f('co-date', 'Call back on *', 'date', `required value="${isoDay(1)}"`) + f('co-time', 'At', 'time'),
        'Not Interested': f('co-reason', 'Why? *', 'text', 'required list="close-reason-suggestions"', true),
        'Already Insured': f('co-expiry', 'Their current policy expires *', 'date', 'required', true),
        'Policy Sold': f('co-insurer', 'Insurer *', 'text', 'required') + f('co-premium', 'Premium (₹) *', 'number', 'required min="1" step="1"')
            + f('co-start', 'Policy starts', 'date', `value="${isoDay(0)}"`) + f('co-end', 'Policy expires *', 'date', `required value="${nextYear}"`),
        'Busy / Switched Off': '<p class="col-span-2 text-slate-500">A retry is scheduled for tomorrow.</p>',
        'Wrong Number': '<p class="col-span-2 text-slate-500">The lead is flagged for a manager to check the number.</p>',
        'Interested': '<p class="col-span-2 text-slate-500">A quotation follow-up is set for today.</p>',
        'Documents Pending': '<p class="col-span-2 text-slate-500">A document collection follow-up is set for tomorrow.</p>',
    };
    document.getElementById('call-outcome-fields').innerHTML = fields[outcome] || '';
    const reasons = document.getElementById('close-reason-suggestions');
    if (reasons && !reasons.children.length) reasons.innerHTML = (callOptions.closeReasons || []).map(r => `<option value="${esc(r)}"></option>`).join('');
}

async function submitCallOutcome(event) {
    event.preventDefault();
    const outcome = document.querySelector('input[name="call-outcome"]:checked')?.value;
    const val = id => document.getElementById(id)?.value?.trim() || '';
    const body = { outcome, notes: val('call-notes'), followUpDate: val('co-date'), followUpTime: val('co-time'),
        reason: val('co-reason'), currentExpiryDate: val('co-expiry') };
    if (outcome === 'Policy Sold') body.policy = { insurer: val('co-insurer'), premium: Number(val('co-premium')), startDate: val('co-start'), expiryDate: val('co-end') };
    try {
        const r = await apiJson(`/api/calls/${activeCall.id}/complete`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        activeCall.done = true;
        closeCallScreen();
        showToast(r.summary);
        refreshAfterCall();
    } catch (e) { document.getElementById('call-outcome-error').textContent = e.message; }
}

function closeCallScreen() {
    if (activeCall && !activeCall.done && !document.getElementById('call-modal').classList.contains('hidden')) {
        if (!confirm('The outcome is not recorded yet. You can record it later from the lead’s call history. Close anyway?')) return;
    }
    clearInterval(callTimer);
    document.getElementById('call-modal').classList.add('hidden');
    const leadId = activeCall?.leadId; activeCall = null;
    refreshAfterCall(leadId);
}

function refreshAfterCall(leadId) {
    if (currentView === 'follow-ups') loadFollowUps();
    else if (currentView === 'leads') loadLeads();
    const drawer = document.getElementById('detail-drawer');
    if (leadId && drawer && !drawer.classList.contains('translate-x-full')) openLeadDrawer(leadId);
}

async function callHistoryCard(leadId) {
    const calls = await apiJson(`/api/calls?leadId=${encodeURIComponent(leadId)}`).catch(() => []);
    return `<div class="border border-slateBorder rounded-lg p-3 bg-white space-y-1.5 text-xs">
        <div class="flex items-center justify-between"><span class="text-[11px] font-bold uppercase tracking-wider">Calls (${calls.length})</span>${callButton(leadId)}</div>
        ${calls.map(c => `<div class="border-t border-slate-100 pt-1.5 flex flex-wrap justify-between gap-2">
            <span><b>${esc(c.status === 'In progress' ? 'Outcome not recorded' : c.outcome)}</b> <span class="text-slate-400">· ${esc(c.assignedTo || '')}</span></span>
            <span class="text-slate-400 font-mono">${esc(formatShortDate(c.startedAt))} · ${formatDuration(c.durationSeconds)}</span>
            ${c.status === 'In progress' ? `<button type="button" class="fu-btn" onclick="resumeCall('${c.id}','${leadId}')">Record outcome</button>` : ''}
            ${c.notes ? `<p class="w-full text-slate-500">${esc(c.notes)}</p>` : ''}</div>`).join('') || '<p class="text-slate-400">No calls yet.</p>'}
    </div>`;
}

// ═══════════════════════════════════════════════════════════════════
// ROLE DASHBOARDS — slide 14 for a telecaller, slides 34 and 47 for the owner
// ═══════════════════════════════════════════════════════════════════
const inr = n => n === null || n === undefined ? '—' : `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const pct = n => n === null || n === undefined ? '—' : `${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 1 })}%`;
const num = n => n === null || n === undefined ? '—' : Number(n).toLocaleString('en-IN');

async function renderRoleDashboard() {
    const root = document.getElementById('dashboard-role');
    if (!root) return;
    try {
        root.innerHTML = roleKey() === 'telecaller' ? telecallerBoard(await apiJson('/api/dashboard/telecaller'))
            : ['admin', 'manager'].includes(roleKey()) ? ownerBoard(await apiJson('/api/dashboard/owner')) : '';
    } catch (e) { root.innerHTML = `<p class="text-xs text-rose-700">${esc(e.message || 'Could not load your figures')}</p>`; }
}

function telecallerBoard(d) {
    const t = d.tiles;
    const tiles = [["Today's leads", t.todaysLeads, 'To work today'], ['Calls done', t.callsDone, 'Today'], ['Connected', t.connected, 'Reached the customer'],
        ['Follow-ups due', t.followUpsDue, t.overdue ? `${t.overdue} overdue` : 'Today and earlier', t.overdue ? 'is-critical' : t.followUpsDue ? 'is-warning' : ''],
        ['Interested', t.interested, 'Today'], ['Quotes sent', t.quotesSent, 'Today'], ['Policies sold', t.policiesSold, 'Today', t.policiesSold ? 'is-good' : ''],
        ['Target achieved', pct(t.targetAchieved), t.targetAchieved === null ? 'No target set this month' : 'This month', t.targetAchieved >= 100 ? 'is-good' : '']];
    const a = d.availability || { available: true };
    return `
        <p class="text-xs flex flex-wrap items-center gap-2">${a.available
            ? `<span class="text-emerald-700 font-semibold">Receiving new leads</span><button type="button" class="fu-btn" onclick="setAvailability(false)">I'm away</button>`
            : `<span class="text-amber-700 font-semibold">Away — no new leads${a.note ? ` (${esc(a.note)})` : ''}</span><button type="button" class="fu-btn" onclick="setAvailability(true)">I'm back</button>`}</p>
        <section class="grid grid-cols-2 sm:grid-cols-4 gap-3">${tiles.map(([label, value, note, tone]) =>
            `<div class="day-tile ${tone || ''}" style="cursor:default"><strong>${esc(String(value))}</strong><span class="font-medium text-slate-700">${esc(label)}</span><span>${esc(note)}</span></div>`).join('')}</section>
        ${d.incentive?.hasPlan ? `<p class="text-xs text-slate-600">This month so far: <b>${num(d.month.policiesSold)}</b> polic${d.month.policiesSold === 1 ? 'y' : 'ies'}, <b>${inr(d.month.premium)}</b> premium · incentive estimate <b>${inr(d.incentive.estimate)}</b>
            <span class="text-slate-400">(${esc(d.incentive.lines.filter(l => l.amount).map(l => `${l.rule} ${inr(l.amount)}`).join(' · ') || 'nothing earned yet')})</span></p>` : ''}
        <section class="band">
            <h3>Today's priority leads</h3>
            ${d.priorityLeads.length ? `<div class="overflow-x-auto"><table class="w-full text-left perf-table min-w-[640px]"><thead><tr><th>Customer</th><th>Product</th><th>Priority</th><th>Status</th><th>Next action</th><th></th></tr></thead><tbody>
            ${d.priorityLeads.map(l => `<tr><td><button class="font-semibold hover:underline" onclick="openLeadDrawer('${l.id}')">${esc(l.name)}</button></td>
                <td>${esc(l.product || '—')}</td><td>${priorityBadge(l)}</td><td><span class="inline-block px-2 py-0.5 rounded text-[11px] ${stagePillClass(l.status)}">${esc(l.status)}</span></td>
                <td>${esc(l.nextAction || '—')}${l.nextActionDate ? `<span class="perf-sub">${esc(l.nextActionDate)}${l.nextActionTime ? ' ' + esc(l.nextActionTime) : ''}</span>` : ''}</td>
                <td class="text-right">${callButton(l.id)}</td></tr>`).join('')}</tbody></table></div>`
            : '<p class="text-xs text-slate-400">No open leads assigned to you.</p>'}
        </section>`;
}

// Slide 12: someone away receives no new leads until they are back.
async function setAvailability(available, userId) {
    let note = '';
    if (!available) { note = prompt('Reason (optional) — for example "On leave until Monday"') ?? null; if (note === null) return; }
    try {
        await apiJson('/api/availability', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ available, note, ...(userId ? { userId } : {}) }) });
        showToast(available ? 'Receiving new leads again' : 'Marked away — no new leads until back');
        renderRoleDashboard();
    } catch (e) { showToast(e.message); }
}

function ownerBoard(d) {
    const b = d.bands, c = d.control, team = d.team;
    const band = (title, items) => `<div class="band"><h3>${title}</h3><div class="band-grid">${items.map(([label, value]) => `<div><strong>${esc(String(value))}</strong><span>${esc(label)}</span></div>`).join('')}</div></div>`;
    return `
        <section class="grid grid-cols-1 lg:grid-cols-3 gap-3">
            ${band('Today', [['New leads', num(b.today.newLeads)], ['Calls', num(b.today.calls)], ['Connected', num(b.today.connected)],
                ['Follow-ups due', num(b.today.followUpsOpen)], ['Policies', num(b.today.policiesSold)], ['Premium', inr(b.today.premium)]])}
            ${band('This week', [['New leads', num(b.week.newLeads)], ['Policies', num(b.week.policiesSold)], ['Premium', inr(b.week.premium)], ['Conversion', pct(b.week.conversionRate)]])}
            ${band('This month', [['Policies', num(b.month.policiesSold)], ['Premium', inr(b.month.premium)],
                ['Commission', d.commissionAvailable ? inr(b.month.commission) : roleKey() === 'admin' ? 'No rates set' : 'Owner only'], ['Renewals', num(b.month.renewalsClosed)]])}
        </section>
        <section class="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-3">
            <div class="band space-y-2 text-xs">
                <h3>Team this month</h3>
                <div class="grid grid-cols-2 gap-2">
                    <div><span class="perf-sub">Best performer</span><b>${esc(team.best || '—')}</b></div>
                    <div><span class="perf-sub">Needs support</span><b>${esc(team.needsSupport || '—')}</b></div>
                    <div><span class="perf-sub">Target achieved</span><b>${team.targetAchieved === null ? 'No targets set' : pct(team.targetAchieved)}</b></div>
                    <div><span class="perf-sub">Online now</span><b>${c.employeesOnline.length} of ${c.teamSize}</b>${c.employeesOnline.length ? `<span class="perf-sub">${esc(c.employeesOnline.join(', '))}</span>` : ''}</div>
                </div>
                <div class="border-t border-slate-100 pt-2"><span class="perf-sub">Away — receiving no new leads</span>
                    ${c.away.length ? c.away.map(p => `<span class="inline-flex items-center gap-1 mr-2">${esc(p.person)}${p.note ? ` <span class="text-slate-400">(${esc(p.note)})</span>` : ''}<button type="button" class="fu-btn" onclick="setAvailability(true,'${p.userId}')">Back</button></span>`).join('') : '<b>Nobody</b>'}
                    ${c.availablePeople.length ? `<select class="corp-input py-0.5 text-[11px] ml-1" aria-label="Mark someone away" onchange="if(this.value)setAvailability(false,this.value)"><option value="">Mark someone away…</option>${c.availablePeople.map(p => `<option value="${esc(p.userId)}">${esc(p.person)}</option>`).join('')}</select>` : ''}
                </div>
            </div>
            <div class="band text-xs">
                <h3>Needs attention today</h3>
                <div class="band-grid">
                    <button class="text-left" onclick="switchView('follow-ups')"><strong>${num(c.overdueFollowUps)}</strong><span>Follow-ups overdue</span></button>
                    <div><strong>${num(c.missedCallsToday)}</strong><span>Calls not connected</span></div>
                    <button class="text-left" onclick="switchView('renewals')"><strong>${num(c.renewalOpportunities)}</strong><span>Policies expiring in 30 days</span></button>
                    <button class="text-left" onclick="switchView('notifications')"><strong>${num(c.importantAlerts)}</strong><span>Unread urgent alerts</span></button>
                </div>
            </div>
        </section>`;
}

// ═══════════════════════════════════════════════════════════════════
// PERFORMANCE — slide 26 (the team) and slide 29 (targets)
// ═══════════════════════════════════════════════════════════════════
let performanceTab = 'team', performancePeriod = 'month', targetsData = null;

function loadPerformance() { setPerformanceTab(performanceTab); }

function setPerformanceTab(tab) {
    performanceTab = tab;
    document.querySelectorAll('[data-perf-tab]').forEach(b => { const on = b.dataset.perfTab === tab; b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on); });
    ['team', 'targets', 'leaderboard', 'incentives', 'commission'].forEach(p =>
        document.getElementById(`perf-${p}-pane`).classList.toggle('hidden', tab !== p));
    applyRoleVisibility();
    if (tab === 'team') setPerformancePeriod(performancePeriod);
    else if (tab === 'targets') loadTargets();
    else if (tab === 'leaderboard') loadLeaderboard();
    else if (tab === 'incentives') loadIncentives();
    else loadCommission();
}

function setPerformancePeriod(period) {
    performancePeriod = period;
    document.querySelectorAll('[data-period]').forEach(b => b.classList.toggle('is-active', b.dataset.period === period));
    const custom = document.getElementById('perf-custom');
    custom.classList.toggle('hidden', period !== 'custom'); custom.classList.toggle('flex', period === 'custom');
    if (period === 'custom') {
        if (!document.getElementById('perf-start').value) { document.getElementById('perf-start').value = isoDay(-30); document.getElementById('perf-end').value = isoDay(0); }
    }
    loadPerformanceTeam();
}

async function loadPerformanceTeam() {
    const params = new URLSearchParams({ period: performancePeriod });
    if (performancePeriod === 'custom') { params.set('start', document.getElementById('perf-start').value); params.set('end', document.getElementById('perf-end').value); }
    let d;
    try { d = await apiJson(`/api/performance?${params}`); } catch (e) { return showToast(e.message); }
    const p = d.period;
    document.getElementById('perf-period-label').textContent = p.start === p.end ? formatShortDate(p.start) : `${formatShortDate(p.start)} – ${formatShortDate(p.end)}`;
    const cols = [['New leads', r => num(r.newLeads)], ['Calls', r => num(r.calls)], ['Connected', r => `${num(r.connected)}<span class="perf-sub">${pct(r.connectRate)}</span>`],
        ['Not connected', r => num(r.notConnected)], ['Avg call', r => r.avgCallSeconds === null ? '—' : formatDuration(r.avgCallSeconds)],
        ['Quotes', r => num(r.quotesSent)], ['Policies', r => num(r.policiesSold)], ['Premium', r => inr(r.premium)], ['Conversion', r => pct(r.conversionRate)],
        ['Follow-ups', r => `${num(r.followUpsDone)} / ${num(r.followUpsDue)}<span class="perf-sub">${pct(r.onTimeRate)} on time</span>`],
        ['Renewals', r => num(r.renewalsClosed)], ['Documents', r => num(r.documentsCollected)]];
    document.getElementById('perf-team-head').innerHTML = `<tr><th>Telecaller</th>${cols.map(([h]) => `<th class="num">${h}</th>`).join('')}</tr>`;
    document.getElementById('perf-team-body').innerHTML = d.rows.length ? d.rows.map(r => `<tr><td class="font-semibold">${esc(r.person)}</td>${cols.map(([, f]) => `<td class="num">${f(r)}</td>`).join('')}</tr>`).join('')
        : `<tr><td colspan="${cols.length + 1}" class="text-center text-slate-400 py-6">No telecallers yet. Add them under Settings → Users.</td></tr>`;
    document.getElementById('perf-team-foot').innerHTML = d.rows.length > 1 ? `<tr><td>Team</td>${cols.map(([, f]) => `<td class="num">${f(d.totals)}</td>`).join('')}</tr>` : '';
}

async function loadTargets() {
    const input = document.getElementById('targets-month');
    if (!input.value) input.value = localCalendarDate().slice(0, 7);
    try { targetsData = await apiJson(`/api/targets?month=${input.value}`); } catch (e) { return showToast(e.message); }
    const d = targetsData, measures = Object.entries(d.measures), canEdit = ['admin', 'manager'].includes(roleKey());
    document.getElementById('targets-headline').innerHTML = measures.map(([k, l]) => `<option value="${k}" ${k === d.headline ? 'selected' : ''}>${esc(l)}</option>`).join('');
    const cell = (key, t, a, percent) => {
        const value = key === 'premium' ? inr(a) : num(a);
        const bar = percent === undefined ? '' : `<div class="bar ${percent >= 100 ? 'is-done' : ''}" title="${pct(percent)}"><i style="width:${Math.min(100, percent)}%"></i></div>`;
        return `<td>${canEdit ? `<input class="target-input" type="number" min="0" data-target="${key}" value="${t ?? ''}" placeholder="—" aria-label="${esc(d.measures[key])} target">` : `<b>${t ?? '—'}</b>`}
            <span class="perf-sub">${value} so far${percent === undefined ? '' : ` · ${pct(percent)}`}</span>${bar}</td>`;
    };
    document.getElementById('targets-head').innerHTML = `<tr><th>Telecaller</th>${measures.map(([, l]) => `<th>${esc(l)}</th>`).join('')}<th>Headline</th>${canEdit ? '<th></th>' : ''}</tr>`;
    document.getElementById('targets-body').innerHTML = d.rows.map(r => `<tr data-person="${esc(r.person)}"><td class="font-semibold">${esc(r.person)}</td>
        ${measures.map(([k]) => cell(k, r.targets[k], r.actual[k], r.achievement.measures[k]?.percent)).join('')}
        <td class="num font-semibold">${pct(r.achievement.percent)}</td>
        ${canEdit ? `<td><button class="fu-btn" onclick="saveTargetRow(this)">Save</button></td>` : ''}</tr>`).join('')
        || `<tr><td colspan="${measures.length + 3}" class="text-center text-slate-400 py-6">No telecallers yet.</td></tr>`;
    const team = d.team.achievement;
    document.getElementById('targets-team').innerHTML = `Team, ${esc(d.month)} to ${esc(formatShortDate(d.through))}: <b>${team.percent === null ? 'no targets set yet' : pct(team.percent) + ' of target'}</b>`;
}

async function saveTargetRow(button) {
    const row = button.closest('tr'), body = { month: targetsData.month, person: row.dataset.person };
    row.querySelectorAll('[data-target]').forEach(i => { body[i.dataset.target] = i.value === '' ? 0 : Number(i.value); });
    try { await apiJson('/api/targets', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); showToast(`Targets saved for ${body.person}`); loadTargets(); }
    catch (e) { showToast(e.message); }
}

async function setTargetHeadline(headline) {
    try { await apiJson('/api/targets/headline', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ headline }) }); loadTargets(); }
    catch (e) { showToast(e.message); }
}

async function copyLastMonthTargets() {
    const to = document.getElementById('targets-month').value;
    const d = new Date(`${to}-01T00:00:00`); d.setMonth(d.getMonth() - 1);
    const from = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    try { const r = await apiJson('/api/targets/copy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from, to }) });
        showToast(r.copied ? `Copied ${r.copied} telecaller${r.copied === 1 ? '' : 's'}' targets from ${from}` : `Nothing to copy — no new targets in ${from}`); loadTargets(); }
    catch (e) { showToast(e.message); }
}

// ── Leaderboard and Employee of the Month (slides 28 and 30) ──
let leaderboardData = null;
async function loadLeaderboard() {
    try { leaderboardData = await apiJson(`/api/leaderboard?period=${performancePeriod === 'custom' ? 'month' : performancePeriod}`); }
    catch (e) { return showToast(e.message); }
    const d = leaderboardData, e = d.employeeOfMonth, admin = roleKey() === 'admin';
    const periods = ['today', 'week', 'month'].map(p => `<button class="fu-tab ${d.period.name === p ? 'is-active' : ''}" onclick="performancePeriod='${p}'; loadLeaderboard()">${{ today: 'Today', week: 'This week', month: 'This month' }[p]}</button>`).join('');
    const awardValue = (k, v) => v === null ? '' : k === 'highestPremium' ? inr(v) : ['highestConversion', 'bestFollowUp'].includes(k) ? pct(v) : num(v);
    document.getElementById('perf-leaderboard-pane').innerHTML = `
        <div class="flex flex-wrap items-center gap-1.5 text-xs">${periods}<span class="ml-auto text-[11px] text-slate-400">${esc(formatShortDate(d.period.start))} – ${esc(formatShortDate(d.period.end))}</span></div>
        <div class="grid grid-cols-2 lg:grid-cols-5 gap-2">${Object.entries(d.awards).map(([k, a]) => `
            <div class="band"><h3>${esc(a.label)}</h3><b class="text-sm">${a.winners.length ? esc(a.winners.join(' & ')) : '—'}</b>
                <span class="perf-sub">${a.winners.length ? awardValue(k, a.value) : esc(a.note || '')}</span></div>`).join('')}</div>
        <div class="bg-white border border-slateBorder rounded-lg overflow-x-auto"><table class="w-full text-left perf-table min-w-[760px]">
            <thead><tr><th>#</th><th>Telecaller</th><th class="num">Calls</th><th class="num">Connected</th><th class="num">Quotes</th><th class="num">Policies</th><th class="num">Premium</th><th class="num">Conversion</th><th class="num">On time</th></tr></thead>
            <tbody>${d.ranking.map((r, i) => `<tr><td class="font-mono text-slate-400">${i + 1}</td><td class="font-semibold">${esc(r.person)}</td><td class="num">${num(r.calls)}</td>
                <td class="num">${num(r.connected)}<span class="perf-sub">${pct(r.connectRate)}</span></td><td class="num">${num(r.quotesSent)}</td><td class="num">${num(r.policiesSold)}</td>
                <td class="num">${inr(r.premium)}</td><td class="num">${pct(r.conversionRate)}</td><td class="num">${pct(r.onTimeRate)}</td></tr>`).join('')
                || '<tr><td colspan="9" class="text-center text-slate-400 py-6">No telecallers yet.</td></tr>'}</tbody></table></div>
        <section class="band space-y-3">
            <div class="flex flex-wrap items-start justify-between gap-2">
                <div><h3>Employee of the Month — ${esc(d.period.start.slice(0, 7))}</h3>
                    <p class="text-xs">${e.announced ? `Announced: <b>${esc(e.announced.person)}</b> by ${esc(e.announced.announcedBy)}` : e.winner ? `Leading: <b>${esc(e.winner)}</b>` : e.tied.length > 1 ? `Tied: <b>${esc(e.tied.join(' & '))}</b>` : 'Nobody has scored yet.'}</p></div>
                ${admin && e.winner && !e.announced ? `<button class="fu-btn is-primary" onclick="announceEmployeeOfMonth('${esc(e.winner)}')">Announce ${esc(e.winner)}</button>` : ''}
            </div>
            <div class="overflow-x-auto"><table class="w-full text-left perf-table min-w-[560px]"><thead><tr><th>Telecaller</th>${Object.keys(e.weightsUsed).map(k => `<th class="num">${esc(e.labels[k])}<span class="perf-sub">${e.weightsUsed[k]} pts</span></th>`).join('')}<th class="num">Score</th></tr></thead>
                <tbody>${e.ranking.map(r => `<tr><td class="font-semibold">${esc(r.person)}</td>${Object.keys(e.weightsUsed).map(k => `<td class="num">${r.parts[k]}</td>`).join('')}<td class="num font-semibold">${r.score}</td></tr>`).join('')}</tbody></table></div>
            <p class="text-[11px] text-slate-500">Each measure is scaled against the best in the team, so the leader on a measure earns its full points.${e.leftOut.length ? ` ${esc(e.leftOut.map(k => e.labels[k]).join(', '))} is left out until calls are reviewed for quality, and the other weights are scaled up to fill its share.` : ''}</p>
            ${admin ? `<details><summary class="text-xs font-semibold cursor-pointer">Change the weights</summary>
                <div class="flex flex-wrap gap-2 mt-2">${Object.entries(e.labels).map(([k, l]) => `<label class="text-xs">${esc(l)} <input class="target-input" type="number" min="0" data-weight="${k}" value="${e.weights[k] ?? 0}"></label>`).join('')}
                <button class="fu-btn" onclick="saveRecognitionWeights()">Save weights</button></div></details>` : ''}
        </section>`;
}
async function announceEmployeeOfMonth(person) {
    try { await apiJson(`/api/recognition/${leaderboardData.period.start.slice(0, 7)}/announce`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ person }) });
        showToast(`${person} is Employee of the Month`); loadLeaderboard(); } catch (e) { showToast(e.message); }
}
async function saveRecognitionWeights() {
    const weights = {}; document.querySelectorAll('[data-weight]').forEach(i => { weights[i.dataset.weight] = Number(i.value || 0); });
    try { await apiJson('/api/recognition/weights', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ weights }) }); showToast('Weights saved'); loadLeaderboard(); }
    catch (e) { showToast(e.message); }
}

// ── Incentives (slide 29) ──
let incentiveData = null, incentiveDraft = null;
async function loadIncentives(month) {
    const m = month || incentiveData?.month || localCalendarDate().slice(0, 7);
    try { incentiveData = await apiJson(`/api/incentives?month=${m}`); } catch (e) { return showToast(e.message); }
    incentiveDraft = JSON.parse(JSON.stringify(incentiveData.rules));
    renderIncentives();
}
function renderIncentives() {
    const d = incentiveData, admin = roleKey() === 'admin', past = d.month < localCalendarDate().slice(0, 7);
    document.getElementById('perf-incentives-pane').innerHTML = `
        <div class="flex flex-wrap items-center gap-2 text-xs">
            <label class="flex items-center gap-1.5">Month <input type="month" class="corp-input w-auto py-0.5" value="${d.month}" onchange="loadIncentives(this.value)"></label>
            <span class="auto-pill ${d.status === 'Approved' ? 'on' : 'later'}">${d.status === 'Approved' ? 'Approved' : 'Estimate — changes as sales happen'}</span>
            ${d.status === 'Approved' ? `<span class="text-slate-500">by ${esc(d.approvedBy)} on ${esc(formatShortDate(d.approvedAt))}</span>` : ''}
            ${admin && past && d.status !== 'Approved' ? `<button class="fu-btn is-primary ml-auto" onclick="approveIncentives()">Approve ${esc(d.month)} for payroll</button>` : ''}
        </div>
        <div class="bg-white border border-slateBorder rounded-lg overflow-x-auto"><table class="w-full text-left perf-table min-w-[640px]">
            <thead><tr><th>Telecaller</th><th class="num">Policies</th><th class="num">Premium</th><th class="num">Target</th><th>How it adds up</th><th class="num">Incentive</th></tr></thead>
            <tbody>${d.rows.map(r => `<tr><td class="font-semibold">${esc(r.person)}</td><td class="num">${num(r.policiesSold)}</td><td class="num">${inr(r.premium)}</td><td class="num">${pct(r.targetAchieved)}</td>
                <td class="text-[11px] text-slate-600 whitespace-normal">${r.lines.map(l => `${esc(l.rule)}: ${inr(l.amount)} <span class="text-slate-400">(${esc(l.basis)})</span>`).join('<br>') || 'No incentive rules yet'}</td>
                <td class="num font-semibold">${inr(r.total)}</td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-slate-400 py-6">No telecallers yet.</td></tr>'}</tbody></table></div>
        ${admin && d.status !== 'Approved' ? incentivePlanEditor() : ''}`;
}
function incentivePlanEditor() {
    const kinds = incentiveData.kinds, measures = incentiveData.slabMeasures;
    const products = leadOptions.products || [], sources = leadOptions.sources || [];
    const field = (i, key, label, attrs = '') => `<label class="text-[11px] text-slate-600">${label}<input class="corp-input mt-0.5 py-0.5" data-inc="${i}.${key}" value="${esc(String(incentiveDraft[i][key] ?? ''))}" ${attrs}></label>`;
    return `<section class="band space-y-2"><h3>Incentive rules</h3>
        <p class="text-xs text-slate-500">Rules can change at any time; an approved month keeps the rules it was approved with.</p>
        ${incentiveDraft.map((r, i) => `<div class="auto-action">
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                ${field(i, 'name', 'Name')}
                <label class="text-[11px] text-slate-600">Kind<select class="corp-input mt-0.5 py-0.5" data-inc="${i}.kind" onchange="collectIncentiveDraft(); renderIncentives()">${Object.entries(kinds).map(([k, l]) => `<option value="${k}" ${k === r.kind ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
                ${r.kind === 'per_policy' ? field(i, 'amount', '₹ per policy', 'type="number" min="0"') : ''}
                ${r.kind === 'premium_percent' ? field(i, 'percent', '% of premium', 'type="number" min="0" max="100" step="0.1"') : ''}
                ${r.kind === 'target_bonus' ? field(i, 'amount', 'Bonus ₹', 'type="number" min="0"') + field(i, 'atPercent', 'When target reaches %', 'type="number" min="1"') : ''}
                ${r.kind === 'slab' ? `<label class="text-[11px] text-slate-600">Levels measure<select class="corp-input mt-0.5 py-0.5" data-inc="${i}.measure">${Object.entries(measures).map(([k, l]) => `<option value="${k}" ${k === r.measure ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
                    ${field(i, 'slabText', 'Levels (from:₹, …)', 'placeholder="5:1000, 10:2500"')}` : ''}
                ${['per_policy', 'premium_percent'].includes(r.kind) ? `<label class="text-[11px] text-slate-600">Only for<select class="corp-input mt-0.5 py-0.5" data-inc="${i}.limit">
                    <option value="">Every sale</option>${products.map(p => `<option value="product:${esc(p)}" ${r.product === p ? 'selected' : ''}>${esc(p)}</option>`).join('')}
                    ${sources.map(x => `<option value="source:${esc(x)}" ${r.source === x ? 'selected' : ''}>Leads from ${esc(x)}</option>`).join('')}</select></label>` : ''}
            </div>
            <div class="flex gap-2"><label class="auto-switch"><input type="checkbox" data-inc="${i}.enabled" ${r.enabled !== false ? 'checked' : ''}><span>On</span></label>
                <button class="fu-btn" onclick="collectIncentiveDraft(); incentiveDraft.splice(${i},1); renderIncentives()">Remove</button></div></div>`).join('')}
        <div class="flex gap-2"><button class="fu-btn" onclick="collectIncentiveDraft(); incentiveDraft.push({name:'', kind:'per_policy', amount:0, enabled:true}); renderIncentives()">+ Add rule</button>
            <button class="fu-btn is-primary" onclick="saveIncentivePlan()">Save rules</button></div></section>`;
}
function collectIncentiveDraft() {
    incentiveDraft.forEach(r => { if (r.slabs && r.slabText === undefined) r.slabText = r.slabs.map(x => `${x.from}:${x.amount}`).join(', '); });
    document.querySelectorAll('[data-inc]').forEach(el => {
        const [i, key] = el.dataset.inc.split('.'); const r = incentiveDraft[Number(i)]; if (!r) return;
        if (key === 'enabled') r.enabled = el.checked;
        else if (key === 'limit') { r.product = el.value.startsWith('product:') ? el.value.slice(8) : ''; r.source = el.value.startsWith('source:') ? el.value.slice(7) : ''; }
        else r[key] = el.type === 'number' ? (el.value === '' ? '' : Number(el.value)) : el.value;
    });
    incentiveDraft.forEach(r => { if (r.kind === 'slab') r.slabs = String(r.slabText || '').split(',').map(x => x.split(':').map(v => v.trim())).filter(x => x.length === 2).map(([from, amount]) => ({ from, amount })); });
}
async function saveIncentivePlan() {
    collectIncentiveDraft();
    try { await apiJson('/api/incentives/plan', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rules: incentiveDraft }) }); showToast('Incentive rules saved'); loadIncentives(); }
    catch (e) { showToast(e.message); }
}
async function approveIncentives() {
    if (!await confirmDestructive({ title: `Approve incentives for ${incentiveData.month}?`, body: 'The amounts are frozen for payroll. Later sales or rule changes will not change them.', confirmLabel: 'Approve', tone: 'primary' })) return;
    try { await apiJson(`/api/incentives/${incentiveData.month}/approve`, { method: 'POST' }); showToast('Approved'); loadIncentives(); } catch (e) { showToast(e.message); }
}

// ── Commission (slide 25) ──
let commissionData = null, commissionRates = [];
async function loadCommission(month) {
    const m = month || commissionData?.month || localCalendarDate().slice(0, 7);
    try { [commissionData, commissionRates] = await Promise.all([apiJson(`/api/commission?month=${m}`), apiJson('/api/commission/rules').then(r => r.rules)]); }
    catch (e) { return showToast(e.message); }
    const d = commissionData;
    document.getElementById('perf-commission-pane').innerHTML = `
        <div class="flex flex-wrap items-center gap-2 text-xs">
            <label class="flex items-center gap-1.5">Month <input type="month" class="corp-input w-auto py-0.5" value="${d.month}" onchange="loadCommission(this.value)"></label>
            <span>Expected <b>${inr(d.totals.expected)}</b> · received <b>${inr(d.totals.received)}</b></span>
            ${d.totals.unrated ? `<span class="text-amber-700">${d.totals.unrated} sale${d.totals.unrated === 1 ? ' has' : 's have'} no rate</span><button class="fu-btn" onclick="applyMissingCommission()">Apply today's rates</button>` : ''}
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-[1fr_1.6fr] gap-3">
            <section class="band space-y-2"><h3>By telecaller</h3>
                <table class="w-full perf-table"><thead><tr><th>Telecaller</th><th class="num">Sales</th><th class="num">New</th><th class="num">Renewal</th><th class="num">Total</th></tr></thead>
                <tbody>${d.byEmployee.map(r => `<tr><td class="font-semibold">${esc(r.employee)}</td><td class="num">${num(r.policies)}</td><td class="num">${inr(r.new)}</td><td class="num">${inr(r.renewal)}</td><td class="num font-semibold">${inr(r.total)}</td></tr>`).join('') || '<tr><td colspan="5" class="text-slate-400">No sales this month.</td></tr>'}</tbody></table></section>
            <section class="band space-y-2"><h3>Rates</h3>
                <p class="text-xs text-slate-500">A line can name a product, an insurer, both or neither; the most specific line applies. Commission is fixed when a policy is sold.</p>
                <div id="commission-rates" class="space-y-1.5">${commissionRates.map((r, i) => rateRow(r, i)).join('')}</div>
                <div class="flex gap-2"><button class="fu-btn" onclick="addRateRow()">+ Add rate</button><button class="fu-btn is-primary" onclick="saveCommissionRates()">Save rates</button></div></section>
        </div>
        <div class="bg-white border border-slateBorder rounded-lg overflow-x-auto"><table class="w-full text-left perf-table min-w-[900px]">
            <thead><tr><th>Sold</th><th>Customer</th><th>Telecaller</th><th>Product · insurer</th><th class="num">Premium</th><th>Basis</th><th class="num">Rate</th><th class="num">Commission</th><th>Status</th><th></th></tr></thead>
            <tbody>${d.rows.map(r => `<tr><td>${esc(formatShortDate(r.saleDate))}</td><td class="font-semibold">${esc(r.customerName)}</td><td>${esc(r.employee)}</td>
                <td>${esc(r.product)}<span class="perf-sub">${esc(r.insurer || '—')}</span></td><td class="num">${inr(r.premium)}</td><td>${r.basis === 'renewal' ? 'Renewal' : 'New'}</td>
                <td class="num">${r.rate === null ? '—' : pct(r.rate)}</td><td class="num">${r.amount === null ? '<span class="text-amber-700">No rate</span>' : inr(r.amount)}${r.override ? `<span class="perf-sub" title="${esc(r.note)}">changed by hand</span>` : ''}</td>
                <td><span class="auto-pill ${r.status === 'Received' ? 'on' : 'off'}">${esc(r.status)}</span></td>
                <td class="whitespace-nowrap">${r.status !== 'Received' && r.amount !== null ? `<button class="fu-btn" onclick="markCommissionReceived('${r.policyId}')">Received</button>` : ''}<button class="fu-btn" onclick="overrideCommission('${r.policyId}', ${r.amount ?? 0})">Change</button></td></tr>`).join('')
                || '<tr><td colspan="10" class="text-center text-slate-400 py-6">No policies sold this month.</td></tr>'}</tbody></table></div>`;
}
function rateRow(r, i) {
    const products = leadOptions.products || [];
    return `<div class="grid grid-cols-2 sm:grid-cols-[1fr_1fr_5rem_5rem_auto] gap-1.5 items-center" data-rate="${i}">
        <select class="corp-input py-0.5" data-rate-key="product"><option value="">Any product</option>${products.map(p => `<option ${p === r.product ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select>
        <input class="corp-input py-0.5" data-rate-key="insurer" placeholder="Any insurer" value="${esc(r.insurer || '')}">
        <input class="target-input" type="number" step="0.1" min="0" max="100" data-rate-key="newRate" placeholder="New %" value="${r.newRate ?? ''}" aria-label="New business rate">
        <input class="target-input" type="number" step="0.1" min="0" max="100" data-rate-key="renewalRate" placeholder="Renew %" value="${r.renewalRate ?? ''}" aria-label="Renewal rate">
        <button class="fu-btn" onclick="this.closest('[data-rate]').remove()" aria-label="Remove rate">✕</button></div>`;
}
function addRateRow() { document.getElementById('commission-rates').insertAdjacentHTML('beforeend', rateRow({}, Date.now())); }
async function saveCommissionRates() {
    const rules = [...document.querySelectorAll('[data-rate]')].map(row => Object.fromEntries([...row.querySelectorAll('[data-rate-key]')].map(el => [el.dataset.rateKey, el.value])));
    try { await apiJson('/api/commission/rules', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rules }) }); showToast('Rates saved — they apply to new sales'); loadCommission(); }
    catch (e) { showToast(e.message); }
}
async function applyMissingCommission() {
    try { const r = await apiJson('/api/commission/apply-missing', { method: 'POST' }); showToast(`Rates applied to ${r.applied} sale${r.applied === 1 ? '' : 's'}`); loadCommission(); } catch (e) { showToast(e.message); }
}
async function markCommissionReceived(policyId) {
    try { await apiJson(`/api/policies/${policyId}/commission`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'Received' }) }); showToast('Marked received'); loadCommission(); }
    catch (e) { showToast(e.message); }
}
function overrideCommission(policyId, amount) {
    openInsuranceForm('Change commission', [['amount', 'Commission (₹)', 'number', true], ['note', 'Why is it changing?', 'text', true]], async v => {
        await apiJson(`/api/policies/${policyId}/commission`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: Number(v.amount), note: v.note }) });
        loadCommission();
    }, { amount });
}

// ═══════════════════════════════════════════════════════════════════
// REPORTS — slide 31 (the sales funnel) and slide 32 (lead sources)
// ═══════════════════════════════════════════════════════════════════
function reportRangeChanged() {
    const custom = document.getElementById('rep-range').value === 'custom';
    const box = document.getElementById('rep-custom'); box.classList.toggle('hidden', !custom); box.classList.toggle('flex', custom);
    if (custom && !document.getElementById('rep-start').value) { document.getElementById('rep-start').value = isoDay(-30); document.getElementById('rep-end').value = isoDay(0); }
    if (!custom) loadReports();
}

function reportRange() {
    const range = document.getElementById('rep-range').value, today = new Date();
    if (range === 'custom') return [document.getElementById('rep-start').value, document.getElementById('rep-end').value];
    if (range === '90') return [isoDay(-89), isoDay(0)];
    if (range === 'last-month') {
        const first = new Date(today.getFullYear(), today.getMonth() - 1, 1), last = new Date(today.getFullYear(), today.getMonth(), 0);
        return [localCalendarDate(first), localCalendarDate(last)];
    }
    return [localCalendarDate(new Date(today.getFullYear(), today.getMonth(), 1)), isoDay(0)];
}

async function loadReports() {
    const [start, end] = reportRange();
    const params = new URLSearchParams({ start, end });
    ['person', 'product', 'source'].forEach(k => { const v = document.getElementById(`rep-${k}`).value; if (v) params.set(k, v); });
    let d;
    try { d = await apiJson(`/api/reports?${params}`); } catch (e) { return showToast(e.message); }
    const fill = (id, label, values) => { const el = document.getElementById(id), keep = el.value;
        el.innerHTML = `<option value="">${label}</option>` + values.map(v => `<option ${v === keep ? 'selected' : ''}>${esc(v)}</option>`).join(''); };
    fill('rep-person', 'All telecallers', d.options.people); fill('rep-product', 'All products', d.options.products); fill('rep-source', 'All sources', d.options.sources);
    const top = d.funnel[0]?.count || 0;
    const undated = d.undatedLeads ? `<p class="text-[11px] text-slate-500">${d.undatedLeads} older lead${d.undatedLeads === 1 ? ' has' : 's have'} no recorded arrival date, so ${d.undatedLeads === 1 ? 'it is' : 'they are'} not in any period.</p>` : '';
    document.getElementById('rep-body').innerHTML = `
        <section class="band">
            <h3>Sales funnel — ${num(d.cohortSize)} lead${d.cohortSize === 1 ? '' : 's'} that arrived ${esc(formatShortDate(d.period.start))} – ${esc(formatShortDate(d.period.end))}</h3>
            ${d.cohortSize ? `<div class="funnel" role="table" aria-label="Sales funnel">${d.funnel.map(st => {
                const width = top ? st.count * 100 / top : 0, inside = width > 18;
                return `<div class="funnel-row" role="row" title="${esc(st.stage)}: ${st.count} of ${d.cohortSize} (${pct(st.ofStart)})${st.ofPrevious !== null ? `, ${pct(st.ofPrevious)} of the stage before` : ''}">
                    <span role="rowheader" class="text-slate-700 font-medium">${esc(st.stage)}</span>
                    <div class="funnel-track" role="cell"><div class="funnel-bar" style="width:${width}%"></div>
                        <span class="funnel-count ${inside ? '' : 'is-outside'}" style="${inside ? '' : `left:calc(${width}% + 6px)`}">${num(st.count)}</span></div>
                    <span class="funnel-rate" role="cell">${pct(st.ofStart)}${st.ofPrevious !== null ? `<span class="perf-sub">${pct(st.ofPrevious)} of previous</span>` : ''}</span></div>`; }).join('')}</div>
            <p class="text-[11px] text-slate-500 mt-2">A lead counts at every stage it reached or passed, so a sale is also counted as contacted, interested and quoted.</p>`
            : '<p class="text-xs text-slate-400">No leads arrived in this period with these filters.</p>'}
            ${undated}
        </section>
        <section class="band">
            <h3>Lead sources — which bring the best customers, not just the most leads</h3>
            <div class="overflow-x-auto"><table class="w-full text-left perf-table min-w-[720px]"><thead><tr><th>Source</th><th class="num">Leads</th><th class="num">Contacted</th><th class="num">Interested</th><th class="num">Quoted</th><th class="num">Converted</th><th class="num">Premium</th><th class="num">Premium per lead</th></tr></thead>
            <tbody>${d.sources.map(r => `<tr><td class="font-semibold">${esc(r.source)}</td><td class="num">${num(r.leads)}</td><td class="num">${pct(r.contactRate)}</td><td class="num">${pct(r.interestedRate)}</td>
                <td class="num">${pct(r.quoteRate)}</td><td class="num">${pct(r.conversionRate)}<span class="perf-sub">${num(r.policies)} sold</span></td><td class="num">${inr(r.premium)}</td><td class="num">${inr(r.premiumPerLead)}</td></tr>`).join('')
                || '<tr><td colspan="8" class="text-center text-slate-400 py-4">No leads in this period.</td></tr>'}</tbody></table></div>
        </section>
        <section class="band">
            <h3>Why leads were lost</h3>
            ${d.lostReasons.length ? `<ul class="text-xs space-y-1">${d.lostReasons.map(r => `<li class="flex justify-between border-b border-slate-100 py-1"><span>${esc(r.reason)}</span><b class="font-mono">${num(r.count)}</b></li>`).join('')}</ul>`
                : '<p class="text-xs text-slate-400">No leads from this period were closed as not interested or lost.</p>'}
        </section>`;
}

// ── Quotations on a lead (slide 20) ──
const QUOTE_PILL = { Draft: 'off', Sent: 'later', Viewed: 'later', Negotiation: 'later', Accepted: 'on', Rejected: 'failed', Expired: 'failed' };
const QUOTE_ACTION = { Sent: 'Mark sent', Viewed: 'Customer viewed', Negotiation: 'Negotiating', Accepted: 'Accepted', Rejected: 'Rejected', Expired: 'Mark expired' };
const QUOTE_FLOW = ['Sent', 'Viewed', 'Negotiation', 'Accepted', 'Rejected', 'Expired'];

async function quotationsCard(l) {
    const quotes = await apiJson(`/api/quotations?leadId=${encodeURIComponent(l.id)}`).catch(() => []);
    const moves = leadOptions.quoteTransitions || {};
    return `<div class="border border-slateBorder rounded-lg p-3 bg-white space-y-2 text-xs">
        <div class="flex items-center justify-between gap-2"><span class="text-[11px] font-bold uppercase tracking-wider">Quotations (${quotes.length})</span>
            <span class="flex gap-1.5">${quotes.filter(q => q.status !== 'Rejected').length > 1 ? `<button class="fu-btn" onclick="openSideBySideQuoteComparison('lead','${l.id}')">Compare</button>` : ''}
            <button class="fu-btn is-primary" onclick="openQuoteForm('${l.id}')">Add quotation</button></span></div>
        ${quotes.map(q => `<div class="border-t border-slate-100 pt-2 space-y-1">
            <div class="flex flex-wrap items-center justify-between gap-2">
                <span><b>${esc(q.insurer)}</b> · <span class="font-mono">${inr(q.premium)}</span>${q.sumInsured ? ` <span class="text-slate-400">· cover ${inr(q.sumInsured)}</span>` : ''}</span>
                <span class="auto-pill ${QUOTE_PILL[q.status] || 'off'}">${esc(q.status)}</span></div>
            <div class="text-[11px] text-slate-500">${[q.sentAt ? `sent ${formatShortDate(q.sentAt)}` : 'not sent yet', q.validityDate ? `valid until ${formatShortDate(q.validityDate)}` : '',
                q.followUpDate ? `follow up ${formatShortDate(q.followUpDate)}` : ''].filter(Boolean).map(esc).join(' · ')}</div>
            ${q.coverageSummary ? `<div class="text-slate-600">${esc(q.coverageSummary)}</div>` : ''}
            ${q.customerResponse ? `<div class="text-slate-600">Customer said: “${esc(q.customerResponse)}”</div>` : ''}
            ${(moves[q.status] || []).length ? `<div class="flex flex-wrap gap-1.5">${[...moves[q.status]].sort((a, b) => QUOTE_FLOW.indexOf(a) - QUOTE_FLOW.indexOf(b)).map(to => `<button class="fu-btn ${to === 'Accepted' ? 'is-primary' : ''}" onclick="setQuoteStatus('${q.id}','${to}',false,'${l.id}')">${esc(QUOTE_ACTION[to] || to)}</button>`).join('')}</div>` : ''}
        </div>`).join('') || '<p class="text-slate-400">No quotations yet.</p>'}
    </div>`;
}

function openQuoteForm(leadId) {
    openInsuranceForm('Add quotation', [['insurer', 'Insurer', 'text', true], ['premium', 'Premium (₹)', 'number', true],
        ['sumInsured', 'Cover / IDV (₹)', 'number', false], ['coverageSummary', 'What it covers', 'textarea', false],
        ['validityDate', 'Valid until', 'date', false], ['followUpDate', 'Follow up on', 'date', false],
        ['status', 'Status', 'selectpairs:Draft::Draft — not sent yet|Sent::Sent to the customer', true]], async v => {
        await apiJson('/api/quotations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ leadId, ...v }) });
        openLeadDrawer(leadId);
    }, { status: 'Sent', followUpDate: isoDay(2) });
}

async function setQuoteStatus(id, status, quiet = false, leadId = '') {
    let body = { status };
    if (!quiet && ['Accepted', 'Rejected', 'Negotiation'].includes(status)) {
        const said = prompt(status === 'Negotiation' ? 'What does the customer want changed?' : 'What did the customer say? (optional)') ;
        if (said === null) return;
        if (said.trim()) body.customerResponse = said.trim();
    }
    try {
        await apiJson(`/api/quotations/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!quiet) { showToast(`Quotation ${status.toLowerCase()}`); if (leadId) openLeadDrawer(leadId); }
    } catch (e) { if (quiet) throw e; showToast(e.message); }
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

    document.getElementById('task-modal-date').value = isoDay(1);
    document.getElementById('task-modal-time').value = '';
    // Handing work to someone else is a manager's decision; a telecaller schedules their own.
    document.getElementById('task-modal-assignee-field').classList.toggle('hidden', !canAssignLeads());
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
    const dueTime = document.getElementById('task-modal-time').value;
    const assignedTo = canAssignLeads() ? document.getElementById('task-modal-assignee').value : undefined;
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
                dueTime,
                assignedTo,
                activityType
            })
        });
        closeTaskModal();
        showToast('Follow-up scheduled');
        if (currentView === 'tasks') loadTasks();
        else if (currentView === 'follow-ups') loadFollowUps();
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
// Suggested next actions for a telecalling day; any text is allowed.
const NEXT_ACTIONS = ['First call', 'Call back', 'Retry call', 'Send quotation', 'Follow up on quotation',
    'Collect documents', 'Confirm payment', 'Share policy copy'];
const STATUS_NEXT_ACTION = { 'New': 'First call', 'Assigned': 'First call', 'Contacted': 'Call back',
    'Interested': 'Send quotation', 'Quote Sent': 'Follow up on quotation', 'Follow-up': 'Call back',
    'Documents Pending': 'Collect documents', 'Call Later': 'Call back', 'Unreachable': 'Retry call' };

const isoDay = (offset = 0) => { const d = new Date(); d.setDate(d.getDate() + offset); return localCalendarDate(d); };
const optionsHtml = (values, selected = '', blank = '') =>
    (blank ? `<option value="">${esc(blank)}</option>` : '') +
    values.map(v => `<option value="${esc(String(v))}" ${String(v) === String(selected ?? '') ? 'selected' : ''}>${esc(String(v))}</option>`).join('');

async function prepareLeadForm() {
    await loadLeadOptions();
    const o = leadOptions;
    document.getElementById('lead-product').innerHTML = optionsHtml(o.products, '', 'Choose product');
    document.getElementById('lead-source').innerHTML = optionsHtml(o.sources, '', 'Not recorded');
    document.getElementById('car-fuel').innerHTML = optionsHtml(o.fuelTypes, '', '—');
    document.getElementById('car-ncb').innerHTML = optionsHtml(o.ncbLevels.map(n => `${n}`), '', '—');
    document.getElementById('health-plan').innerHTML = optionsHtml(o.healthPlanTypes, '', '—');
    document.getElementById('next-action-suggestions').innerHTML = NEXT_ACTIONS.map(a => `<option value="${esc(a)}"></option>`).join('');
    // Assigning work is a manager's decision; a telecaller's own leads stay theirs.
    document.getElementById('lead-owner-field').classList.toggle('hidden', !canAssignLeads());
}

function canAssignLeads() {
    return !signedInUser || ['admin', 'manager', 'Administrator'].includes(signedInUser.role) || /admin|manager/i.test(roleLabel(signedInUser));
}

function showProductDetails(product) {
    const p = (product || '').toLowerCase();
    document.getElementById('lead-car-details').classList.toggle('hidden', !p.includes('car'));
    document.getElementById('lead-health-details').classList.toggle('hidden', !p.includes('health'));
}

async function openCreateModal() {
    editingLeadId = null;
    document.querySelector('#create-modal form').reset();
    await prepareLeadForm();
    document.getElementById('lead-form-title').textContent = 'New Lead';
    document.getElementById('lead-form-submit').textContent = 'Save lead';
    document.getElementById('lead-next-action').value = 'First call';
    document.getElementById('lead-next-action-date').value = isoDay(0);
    showProductDetails('');
    document.getElementById('create-modal')?.classList.remove('hidden');
    document.getElementById('lead-name').focus();
}

async function openEditLead(id) {
    const data = await apiJson(`/api/leads/${id}`); const l = data.lead; editingLeadId = id;
    document.querySelector('#create-modal form').reset();
    await prepareLeadForm();
    document.getElementById('lead-form-title').textContent = 'Edit lead';
    document.getElementById('lead-form-submit').textContent = 'Save changes';
    const v = l.vehicleDetails || {}, h = l.healthDetails || {};
    const values = { 'lead-name': l.name, 'lead-mobile': l.mobile, 'lead-email': l.email, 'lead-city': l.city,
        'lead-product': l.product, 'lead-source': l.source === 'Not recorded' ? '' : l.source, 'lead-expiry': l.expiryDate,
        'lead-insurer': l.existingPolicy?.insurer, 'lead-premium': l.premium, 'lead-owner': l.assignedTo,
        'lead-next-action': l.nextAction, 'lead-next-action-date': l.nextActionDate, 'lead-next-action-time': l.nextActionTime,
        'car-registration': v.registrationNumber, 'car-make': v.make, 'car-model': [v.model, v.variant].filter(Boolean).join(' '),
        'car-year': v.manufactureYear, 'car-fuel': v.fuelType, 'car-ncb': v.ncbPercent,
        'health-plan': h.planType, 'health-sum': h.sumInsured, 'health-conditions': h.preExistingConditions,
        'health-members': (h.members || []).map(m => `${m.relation} ${m.age}`).join(', ') };
    Object.entries(values).forEach(([key, value]) => { const el = document.getElementById(key); if (el) el.value = value ?? ''; });
    showProductDetails(l.product);
    const open = needsNextAction(l.status);
    document.getElementById('lead-next-action').closest('.grid').classList.toggle('hidden', !open);
    document.getElementById('lead-next-action-date').required = open;
    document.getElementById('create-modal').classList.remove('hidden');
}

function closeCreateModal() {
    document.getElementById('create-modal')?.classList.add('hidden');
    document.getElementById('lead-next-action').closest('.grid').classList.remove('hidden');
    document.getElementById('lead-next-action-date').required = true;
}

// "Self 38, Spouse 35, Son 8" → [{relation, age}]. The server validates each entry.
function parseMembers(text) {
    return (text || '').split(',').map(part => part.trim()).filter(Boolean).map(part => {
        const match = part.match(/^(.*?)\s*(\d{1,3})$/);
        return match ? { relation: match[1].trim() || 'Self', age: Number(match[2]) } : { relation: part, age: -1 };
    });
}

function compact(obj) {
    return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== '' && v !== null && v !== undefined && !(Array.isArray(v) && !v.length)));
}

async function handleCreateLeadSubmit(e) {
    e.preventDefault();
    const val = id => document.getElementById(id).value.trim();
    const product = val('lead-product');
    const payload = {
        firstName: val('lead-name'), name: val('lead-name'), mobile: val('lead-mobile'), email: val('lead-email'),
        city: val('lead-city'), product, leadSource: val('lead-source'), expiryDate: val('lead-expiry'),
        premium: val('lead-premium'), notes: val('lead-notes'),
        existingPolicy: compact({ insurer: val('lead-insurer') }),
    };
    if (!document.getElementById('lead-next-action').closest('.grid').classList.contains('hidden')) {
        payload.nextAction = val('lead-next-action') || 'First call';
        payload.nextActionDate = val('lead-next-action-date');
        payload.nextActionTime = val('lead-next-action-time');
    }
    if (canAssignLeads() && val('lead-owner')) payload.assignedTo = val('lead-owner');
    if (product.toLowerCase().includes('car')) {
        const [model, ...variant] = val('car-model').split(' ');
        payload.vehicleDetails = compact({ registrationNumber: val('car-registration'), make: val('car-make'), model,
            variant: variant.join(' '), manufactureYear: val('car-year') ? Number(val('car-year')) : null,
            fuelType: val('car-fuel'), ncbPercent: val('car-ncb') === '' ? null : Number(val('car-ncb')) });
    }
    if (product.toLowerCase().includes('health')) {
        payload.healthDetails = compact({ planType: val('health-plan'), sumInsured: val('health-sum') ? Number(val('health-sum')) : null,
            members: parseMembers(val('health-members')), preExistingConditions: val('health-conditions') });
    }
    if (editingLeadId) delete payload.notes;
    try {
        await apiJson(editingLeadId ? `/api/leads/${editingLeadId}` : '/api/leads', {
            method: editingLeadId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const edited = editingLeadId;
        closeCreateModal();
        showToast(edited ? 'Lead updated' : 'Lead created');
        editingLeadId = null;
        await loadLeads();
        if (edited && document.getElementById('detail-drawer')?.classList.contains('translate-x-0')) openLeadDrawer(edited);
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
    renderRoleDashboard();
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
        const visible = layout.order.filter(id => !hidden.has(id));
        // "today" spans the full width; the rest sit in two columns so the page is
        // scannable in one screen rather than a single long scroll.
        const full = visible.filter(id => id === 'today');
        const rest = visible.filter(id => id !== 'today');
        const host = document.getElementById('dashboard-panels');
        host.innerHTML = visible.length ? `
            ${full.map(id => renderDashboardPanel(id, data)).join('')}
            <div class="dash-grid">
                ${rest.map(id => `<div class="dash-cell" data-panel="${id}">${renderDashboardPanel(id, data)}</div>`).join('')}
            </div>`
            : '<div class="text-xs text-slate-400 text-center py-10">Every panel is hidden. Use Customise to bring some back.</div>';
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
        <div class="p-4 dash-body">${body}</div>
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
            `<div class="day-tiles">
                ${tiles.map(([label, value, tone, go]) => `
                    <button onclick="${go}" class="day-tile ${tone}">
                        <strong class="day-tile-value">${value ?? 0}</strong>
                        <span class="day-tile-label">${label}</span>
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
        const range = Number(localStorage.getItem('crm_trend_days') || 7);
        return dashPanel('Work trend', `Scheduled versus completed, last ${range} days`,
            `<div id="work-trend" class="viz-root"></div>`,
            `<select onchange="setTrendRange(this.value)" class="corp-input text-[11px] py-0.5 w-auto">
                ${[7, 14, 30].map(d => `<option value="${d}" ${d === range ? 'selected' : ''}>${d} days</option>`).join('')}
             </select>`);
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
function setTrendRange(days) {
    localStorage.setItem('crm_trend_days', days);
    loadDashboard();
}

function drawWorkTrend(trend) {
    const host = document.getElementById('work-trend');
    if (!host) return;
    const days = Number(localStorage.getItem('crm_trend_days') || 7);
    trend = (trend || []).slice(-days);
    if (!trend.length) {
        host.innerHTML = '<p class="text-xs text-slate-400 py-8 text-center">No task history in this period yet.</p>';
        return;
    }
    const hasData = trend.some(d => d.due || d.completed);
    const max = Math.max(1, ...trend.map(d => Math.max(d.due, d.completed)));
    const H = 120;
    host.innerHTML = `
        <div class="viz-legend">
            <span><i style="background:var(--viz-series-1)"></i>Scheduled</span>
            <span><i style="background:var(--viz-series-2)"></i>Completed</span>
        </div>
        ${hasData ? '' : '<p class="text-[11px] text-slate-400 mb-2">No tasks scheduled or completed in this period — the axis is shown for scale.</p>'}
        <div class="viz-bars" role="img" aria-label="Tasks scheduled versus completed per day">
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
    openInsuranceForm('Edit customer profile',[['name','Customer name','text',true],['organization','Organization','text',false],['email','Email','email',false],['mobile','Mobile','text',false],['status','Status','select:Active|Inactive',true],['assignedTo','Account owner',ownerFieldOptions(),false],['city','City','text',false],['preferences','Preferences (language, best time to call…)','text',false],['gstNumber','GST number','text',false],['address','Address','textarea',false]],v=>apiJson(`/api/customers/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}),c);
}

function createCustomer() {
    openInsuranceForm('New customer', [['name','Customer name','text',true],['organization','Organization','text',false],['email','Email','email',false],['mobile','Mobile','text',false],['assignedTo','Account owner',ownerFieldOptions(),false],['gstNumber','GST number','text',false],['address','Address','textarea',false]],
        values => apiJson('/api/customers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)}));
}

// Slide 18: one customer, one complete history — the eight blocks of the client's profile.
async function openCustomer360(id) {
    try {
        const c = await apiJson(`/api/customers/${id}`);
        const root = document.getElementById('customer-360'); root.classList.remove('hidden');
        const box = (title, count, body) => `<section class="border border-slateBorder rounded-lg p-3 bg-white min-w-0"><h3 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 flex justify-between">${title}${count === null ? '' : `<span class="num-tabular">${count}</span>`}</h3><div class="mt-1.5 space-y-1.5 text-xs">${body}</div></section>`;
        const none = text => `<p class="text-slate-400">${text}</p>`;
        const row = (main, sub, right = '') => `<div class="border-t border-slate-100 first:border-0 pt-1.5 flex justify-between gap-2"><div class="min-w-0"><div class="font-medium truncate">${main}</div>${sub ? `<div class="text-slate-500">${sub}</div>` : ''}</div>${right ? `<span class="text-[11px] text-slate-400 shrink-0 font-mono">${right}</span>` : ''}</div>`;
        const openRenewals = c.renewals.filter(r => !['Renewed', 'Lost', 'Lapsed'].includes(r.stage));
        const docs = c.documents.filter(d => d.status !== 'Archived');
        root.innerHTML = `<div class="flex flex-wrap justify-between gap-3"><div><h2 class="font-semibold text-base">${esc(c.name)}</h2><p class="text-xs text-slate-500">${esc(c.mobile || 'No mobile')} · ${esc(c.email || 'No email')}${c.city ? ` · ${esc(c.city)}` : ''} · owned by ${esc(c.assignedTo || 'nobody')}</p></div>
            <div class="flex gap-2">${c.leads[0] ? callButton(c.leads[0].id) : ''}<button onclick="openCalendarEventForm('Customer','${c.id}')" class="px-2.5 py-1 border rounded text-xs font-semibold">Schedule</button><button onclick="editCustomer('${c.id}')" class="px-2.5 py-1 border rounded text-xs font-semibold">Edit profile</button><button aria-label="Close customer profile" onclick="document.getElementById('customer-360').classList.add('hidden')">✕</button></div></div>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 mt-4">
            ${box('Basic details', null, `${row('Contact', `${esc(c.mobile || '—')}<br>${esc(c.email || '—')}`)}${row('City', esc(c.city || 'Not recorded'))}${row('Preferences', esc(c.preferences || 'None recorded'))}
                ${c.leads.length ? row('Came to us as', c.leads.map(l => `<button class="underline" onclick="openLeadDrawer('${l.id}')">${esc(l.product || 'Lead')}</button> · ${esc(l.source || 'source not recorded')}${l.leadDate ? ` · ${esc(formatShortDate(l.leadDate))}` : ''}`).join('<br>')) : ''}`)}
            ${box('Insurance history', c.insuranceHistory.length, c.insuranceHistory.map(h => row(`${esc(h.insurer || 'Insurer not recorded')} · ${esc(h.product || '')}`,
                `${esc(h.source)}${h.policyNumber ? ` · ${esc(h.policyNumber)}` : ''}${h.status ? ` · ${esc(h.status)}` : ''}${h.hadClaim ? ' · had a claim' : ''}`, esc(h.expiryDate || ''))).join('') || none('No earlier policies recorded.'))}
            ${box('Call history', c.calls.length, c.calls.slice(0, 8).map(x => row(esc(x.status === 'In progress' ? 'Outcome not recorded' : (x.outcome || '—')),
                `${esc(x.assignedTo || '')}${x.notes ? ` · ${esc(x.notes)}` : ''}${x.recordingUrl ? ` · <a class="underline" href="${esc(x.recordingUrl)}" target="_blank" rel="noopener">recording</a>` : ''}`,
                `${esc(formatShortDate(x.startedAt))} · ${formatDuration(x.durationSeconds)}`)).join('') + (c.calls.length > 8 ? `<p class="text-slate-400">and ${c.calls.length - 8} earlier</p>` : '') || none('No calls yet.'))}
            ${box('Quotations', c.quotations.length, c.quotations.map(q => row(`${esc(q.insurer)} · ₹${Number(q.premium || 0).toLocaleString('en-IN')}`, `${esc(q.status)}${q.validityDate ? ` · valid to ${esc(q.validityDate)}` : ''}`, esc(formatShortDate(q.sentAt || q.createdAt)))).join('') || none('No quotations.'))}
            ${box('Documents', docs.length, docs.map(d => row(`<a class="underline" href="/api/documents/${d.id}/content" target="_blank" rel="noopener">${esc(d.docType || d.category || d.title)}</a>`, `${esc(d.originalName || '')} · ${esc(d.verification || '')}`, esc(formatShortDate(d.createdAt)))).join('') || none('No documents uploaded.'))}
            ${box('Policies', c.policies.length, c.policies.map(x => row(`${esc(x.policyNumber || 'Draft')} · ${esc(x.policyType || '')}`, `${esc(x.insurer || '')} · ${esc(x.status || x.issuanceStatus || '')}`, x.expiryDate ? `to ${esc(x.expiryDate)}` : '')).join('')
                + (openRenewals.length ? `<p class="text-amber-700">${openRenewals.length} renewal${openRenewals.length === 1 ? '' : 's'} open — <button class="underline" onclick="switchView('renewals')">Renewals</button></p>` : '') || none('No policies yet.'))}
            ${box('Follow-ups', c.followUps.upcoming.length, (c.followUps.upcoming.map(t => row(esc(t.title), esc(t.assignedTo || ''), `${esc(t.dueDate || '')} ${esc(t.dueTime || '')}`)).join('') || none('Nothing upcoming.'))
                + (c.followUps.completed.length ? `<p class="text-[11px] font-semibold text-slate-500 pt-1">Completed (${c.followUps.completed.length})</p>${c.followUps.completed.slice(0, 5).map(t => row(esc(t.title), esc(t.assignedTo || ''), esc(formatShortDate(t.completedAt)))).join('')}` : ''))}
            ${box('Notes', c.notes.length, c.notes.slice(0, 8).map(n => row(esc(n.title || 'Note'), esc(n.content || n.body || '').slice(0, 160), esc(formatShortDate(n.createdAt)))).join('') || none('No notes.'))}
        </div>`;
    } catch (e) { showToast(e.message) }
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
                        <div class="text-[11px] text-slate-500">${esc(roleLine(me))}${me.managerName ? ` · reports to ${esc(me.managerName)}` : ''}</div>
                    </div>
                    <div class="ml-auto grid grid-cols-3 gap-2 text-center shrink-0">
                        ${[['openLeads', 'Open leads'], ['wonLeads', 'Sold'], ['openTasks', 'Open tasks']].map(([k, l]) =>
                            `<div class="px-2"><strong class="block text-base font-semibold num-tabular">${me.stats[k]}</strong><span class="text-[10px] text-slate-400 uppercase tracking-wider">${l}</span></div>`).join('')}
                    </div>
                </div>
                <form onsubmit="saveProfile(event)" class="space-y-3">
                    <div class="grid grid-cols-2 gap-3">
                        <label class="block text-xs font-medium text-slate-700">Full name<input id="prof-name" class="corp-input mt-1" value="${esc(me.name)}" required></label>
                        <label class="block text-xs font-medium text-slate-700">Email<input id="prof-email" type="email" class="corp-input mt-1" value="${esc(me.email || '')}"></label>
                        <label class="block text-xs font-medium text-slate-700">Phone<input id="prof-phone" class="corp-input mt-1" value="${esc(me.phone || '')}"></label>
                        <label class="block text-xs font-medium text-slate-700">Job title<input id="prof-title" class="corp-input mt-1" value="${esc(me.title || '')}" placeholder="e.g. Senior Telecaller"></label>
                    </div>
                    <p class="text-[11px] text-slate-500">Renaming yourself moves every lead, task and policy you own to the new name.</p>
                    <button class="px-4 py-2 bg-slate-900 text-white rounded text-xs font-semibold">Save profile</button>
                </form>
                ${me.directReports.length ? `<div><h4 class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Reports to me</h4>
                    <div class="space-y-1">${me.directReports.map(r => `<div class="text-xs border border-slateBorder rounded px-2.5 py-1.5">${esc(r.name)} <span class="text-slate-400">· ${esc(roleLine(r))}</span></div>`).join('')}</div></div>` : ''}
            </div>`;
    } else if (tab === 'users') {
        const [users, leads] = await Promise.all([apiJson('/api/users'), apiJson('/api/leads')]);
        if (!stillCurrent()) return;
        const load = name => leads.filter(l => l.assignedTo === name && isOpenLead(l)).length;
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
                                    <div class="text-[11px] text-slate-500 truncate">${esc(roleLine(u))}${u.email ? ` · ${esc(u.email)}` : ''} · ${load(u.name)} open leads</div>
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
    } else if (tab === 'team') {
        const [users, leads] = await Promise.all([apiJson('/api/users'), apiJson('/api/leads')]);
        if (!stillCurrent()) return;
        const active = users.filter(u => (u.status || 'Active') === 'Active' && !['admin', 'readonly'].includes(u.role));
        const openLeads = leads.filter(isOpenLead);
        const countFor = name => openLeads.filter(l => l.assignedTo === name).length;
        const most = Math.max(1, ...active.map(u => countFor(u.name)));
        pane.innerHTML = `
            <div class="space-y-4">
                <div class="flex items-start justify-between gap-3">
                    <div><h3 class="font-semibold text-slate-900 text-sm">Team access & allocation</h3>
                    <p class="text-xs text-slate-500 mt-0.5">Invite login users, control their role and balance inbound work.</p></div>
                    <button onclick="createTeamUser()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-semibold">Add user</button>
                </div>
                <div class="border border-slateBorder rounded divide-y">${users.map(u=>`<div class="p-2.5 flex items-center justify-between gap-3"><div><strong class="text-xs">${esc(u.name)}</strong><div class="text-[11px] text-slate-500">${esc(u.email||'No login email')} · ${esc(roleLine(u))} · ${esc(u.status||'Active')}</div></div>${u.status!=='Inactive'?`<button onclick="deactivateTeamUser('${u.id}')" class="text-[11px] font-semibold text-rose-700">Deactivate</button>`:''}</div>`).join('')}</div>
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
        const [backups, jobs] = await Promise.all([apiJson('/api/backups'), apiJson('/api/admin/jobs').catch(() => null)]);
        if (!stillCurrent()) return;
        pane.innerHTML=`<div class="space-y-4"><div class="flex justify-between gap-3"><div><h3 class="font-semibold text-sm">Backups</h3><p class="text-xs text-slate-500">Reports on leads, sources and the sales funnel are on the <button class="underline" onclick="closeSettingsModal(); switchView('reports')">Reports</button> screen; each telecaller's figures are under <button class="underline" onclick="closeSettingsModal(); switchView('performance')">Performance</button>.</p></div><button onclick="createSystemBackup()" class="px-3 py-1.5 bg-slate-900 text-white rounded text-xs shrink-0">Create backup</button></div>
            <div class="border border-slateBorder rounded p-3 space-y-2" data-requires="admin"><h4 class="font-semibold text-xs">Export all data</h4><p class="text-[11px] text-slate-500">Download everything — leads, customers, policies, renewals, calls, quotations, follow-ups, notes, messages, targets and the audit log — as spreadsheets that open in Excel, plus one complete file for moving to another system. Passwords are never included. Each export is recorded in the audit log.</p>
                <div class="flex flex-wrap gap-2"><a href="/api/export" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold hover:bg-slate-50">Export records</a><a href="/api/export?includeFiles=true" class="px-3 py-1.5 border border-slate-300 rounded text-xs font-semibold hover:bg-slate-50">Export records and documents</a></div></div>${jobs ? `<p class="text-[11px] ${jobs.lastError ? 'text-rose-700' : 'text-slate-500'}">Reminders and renewals last ran ${jobs.lastRun ? esc(formatShortDate(jobs.lastRun)) + ' ' + esc(String(jobs.lastRun).slice(11, 16)) + ' UTC' : '— not yet'}.${jobs.lastError ? ` Last error (${esc(formatShortDate(jobs.lastErrorAt))}): ${esc(jobs.lastError)}` : ''}</p>` : ''}
            <div>${backups.map(b=>`<div class="text-xs py-2 border-b border-slate-100 flex justify-between gap-2 items-center"><span>${esc(b.name)} · ${Math.ceil(b.size/1024)} KB</span><button class="text-[11px] font-semibold text-rose-700" onclick="restoreSystemBackup('${esc(b.name)}')">Restore</button></div>`).join('')||'<p class="text-xs text-slate-400 mt-2">No backups created.</p>'}</div></div>`;
        applyRoleVisibility();
    }
}

// ── Profile, users & hierarchy actions ──────────────────────────────
async function saveProfile(event) {
    event.preventDefault();
    await apiJson('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: document.getElementById('prof-name').value.trim(),
            email: document.getElementById('prof-email').value.trim(),
            phone: document.getElementById('prof-phone').value.trim(),
            title: document.getElementById('prof-title').value.trim() }) });
    showToast('Profile saved'); await loadBrokerRoster(); switchSettingTab('profile');
}

// The four roles. Permission comes only from these; a job title is display text.
const ROLES = { admin: 'Owner / Admin', manager: 'Manager', telecaller: 'Telecaller', readonly: 'Read-only' };
const ROLE_PICKER = 'selectpairs:' + Object.entries(ROLES).map(([k, l]) => `${k}::${l}`).join('|');
const roleLabel = u => ROLES[u?.role] || u?.role || '';
const roleLine = u => [roleLabel(u), u?.title].filter(Boolean).join(' · ');

function addUser() {
    openInsuranceForm('Add user', [['name', 'Full name', 'text', true], ['email', 'Work email', 'email', true],
        ['role', 'Role', ROLE_PICKER, true], ['title', 'Job title (optional)', 'text', false],
        ['temporaryPassword', 'Temporary password (12+ characters)', 'password', true]], async v => {
        await apiJson('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
        await loadBrokerRoster(); switchSettingTab('users');
    });
}

async function editUser(id) {
    const user = (await apiJson('/api/users')).find(u => u.id === id);
    openInsuranceForm('Edit user', [['name', 'Full name', 'text', true], ['email', 'Email', 'email', false],
        ['role', 'Role', ROLE_PICKER, true], ['title', 'Job title (optional)', 'text', false],
        ['status', 'Status', 'select:Active|Inactive', true]], async v => {
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
function createTeamUser(){openInsuranceForm('Add CRM user',[['name','Full name','text',true],['email','Work email','email',true],['role','Role',ROLE_PICKER,true],['title','Job title (optional)','text',false],['temporaryPassword','Temporary password','password',true]],async values=>{await apiJson('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});await loadBrokerRoster();switchSettingTab('team')})}
async function deactivateTeamUser(id){if(!confirm('Deactivate this login? Historical ownership is retained and open work must be reassigned.'))return;await apiJson(`/api/users/${id}`,{method:'DELETE'});showToast('User deactivated');await switchSettingTab('team')}
async function saveCrmConfiguration(e){e.preventDefault();const lines=id=>document.getElementById(id).value.split('\n').map(x=>x.trim()).filter(Boolean);await apiJson('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({crm:{leadStages:lines('config-stages'),insuranceProducts:lines('config-products'),insurers:lines('config-insurers'),companyTimezone:document.getElementById('config-timezone').value,upcomingReminderMinutes:Number(document.getElementById('config-reminder-minutes').value)}})});showToast('CRM configuration saved')}
async function restoreLead(id){await apiJson(`/api/archived-leads/${id}/restore`,{method:'POST'});await switchSettingTab('archive');showToast('Lead restored')}
async function restoreOperationalRecord(id){await apiJson(`/api/archived-records/${id}/restore`,{method:'POST'});await switchSettingTab('archive');showToast('Record restored')}
// Restore replaces every record with the backup's. The server first saves a safety copy of the
// current data, which appears in this list, so a mistaken restore can itself be undone.
async function restoreSystemBackup(name) {
    if (!confirm(`Replace ALL current CRM data with backup ${name}?\n\nA safety copy of today's data is saved first and will appear in this list.`)) return;
    try { const r = await apiJson(`/api/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' });
        showToast(`Restored. Safety copy: ${r.safetyBackup}`); switchSettingTab('reports'); }
    catch (e) { showToast(e.message); }
}

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
        let allowDuplicate = false;
        const duplicate = (window.crmChannels || []).find(c => c.provider === provider);
        if (duplicate) {
            const proceed = await confirmDestructive({
                title: `${spec.label} is already connected`,
                body: `“${duplicate.name}” is already set up. Add a second one only if you genuinely run separate ad accounts — otherwise go back and finish setting up the existing connection.`,
                confirmLabel: 'Add a second one anyway', tone: 'neutral'
            });
            if (!proceed) { closeInsuranceForm(); loadChannels(); return; }
            allowDuplicate = true;
        }
        try {
            const created = await apiJson('/api/channels', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, name: values.name || spec.label, credentials, allowDuplicate,
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
async function openSendMessage(leadId, draft = '') {
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
    if (draft) {
        const channel = document.getElementById('msg-channel');
        const whatsapp = [...channel.options].find(o => o.value.toLowerCase() === 'whatsapp');
        if (whatsapp) channel.value = whatsapp.value;
        document.getElementById('msg-content').value = draft;
    }
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
    const palette = {
        'New': 'bg-slate-100 text-slate-800 border border-slate-200',
        'Assigned': 'bg-slate-100 text-slate-800 border border-slate-200',
        'Contacted': 'bg-blue-50 text-blue-800 border border-blue-200',
        'Follow-up': 'bg-blue-50 text-blue-800 border border-blue-200',
        'Call Later': 'bg-blue-50 text-blue-800 border border-blue-200',
        'Interested': 'bg-violet-50 text-violet-800 border border-violet-200',
        'Quote Sent': 'bg-violet-50 text-violet-800 border border-violet-200',
        'Documents Pending': 'bg-amber-50 text-amber-800 border border-amber-200',
        'Policy Sold': 'bg-emerald-50 text-emerald-900 border border-emerald-300 font-semibold',
        'Unreachable': 'bg-orange-50 text-orange-800 border border-orange-200',
        'Wrong Number': 'bg-orange-50 text-orange-800 border border-orange-200',
        'Not Interested': 'bg-rose-50 text-rose-800 border border-rose-200',
        'Lost': 'bg-rose-50 text-rose-800 border border-rose-200',
    };
    return palette[stage] || 'bg-slate-100 text-slate-700';
}

// Calling priority is shown as a word, not colour alone.
function priorityBadge(lead) {
    const p = (lead.leadPriority || '').toUpperCase();
    const cls = { HOT: 'bg-rose-50 text-rose-700 border-rose-200', WARM: 'bg-amber-50 text-amber-800 border-amber-200',
        COLD: 'bg-slate-50 text-slate-600 border-slate-200' }[p];
    return cls ? `<span class="inline-block px-1.5 py-0.5 rounded border text-[10px] font-bold tracking-wider ${cls}" title="Calling priority">${p}</span>`
        : '<span class="text-slate-300">—</span>';
}

const productLine = l => [l.product || l.policyType || 'Product not set', l.city].filter(Boolean).join(' · ');

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
