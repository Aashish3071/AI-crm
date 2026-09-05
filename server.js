/**
 * InsureVoice AI - Production Server
 * REST API and Webhook Engine for AI Voice Follow-ups with Frappe CRM Integration
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const callManager = require('./callManager');
const FrappeCRMClient = require('./frappeClient');

const PORT = process.env.PORT || 3030;

// Helper to parse JSON request bodies
function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
      if (body.length > 5 * 1024 * 1024) {
        reject(new Error('Payload too large'));
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

// Send JSON response with standard CORS
function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization'
  });
  res.end(JSON.stringify(data));
}

// MIME types for static assets
const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

const server = http.createServer(async (req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;
  const method = req.method;

  // Handle CORS Preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization'
    });
    return res.end();
  }

  try {
    // -------------------------------------------------------------
    // API ROUTES
    // -------------------------------------------------------------

    // 1. Health & Connection Status
    if (pathname === '/api/health' && method === 'GET') {
      const frappeStatus = await callManager.frappeClient.testConnection();
      return sendJson(res, 200, {
        status: 'healthy',
        timestamp: new Date().toISOString(),
        service: 'InsureVoice AI Engine',
        frappeCrm: frappeStatus,
        voiceEngine: {
          status: 'ready',
          provider: 'ElevenLabs Turbo v2.5 / Cartesia Sonic',
          vadLatency: '120ms',
          synthesizerLatency: '350ms'
        }
      });
    }

    // 2. Metrics & KPI Summary
    if (pathname === '/api/metrics' && method === 'GET') {
      const metrics = callManager.getMetrics();
      return sendJson(res, 200, metrics);
    }

    // 3. Leads Eligible for Insurance Follow-up
    if (pathname === '/api/leads' && method === 'GET') {
      const leads = await callManager.frappeClient.getFollowUpLeads();
      return sendJson(res, 200, { leads });
    }

    // 4. Calls List & Search
    if (pathname === '/api/calls' && method === 'GET') {
      const filter = {
        search: parsedUrl.query.search || '',
        sentiment: parsedUrl.query.sentiment || ''
      };
      const calls = callManager.getAllCalls(filter);
      return sendJson(res, 200, { calls });
    }

    // 5. Single Call Detail
    if (pathname.startsWith('/api/calls/') && !pathname.endsWith('/turn') && !pathname.endsWith('/sync') && method === 'GET') {
      const callId = pathname.replace('/api/calls/', '');
      const call = callManager.getCallById(callId);
      if (!call) return sendJson(res, 404, { error: 'Call session not found' });
      return sendJson(res, 200, { call });
    }

    // 6. Initiate Call Session
    if (pathname === '/api/calls/initiate' && method === 'POST') {
      const body = await parseJsonBody(req);
      if (!body.lead) {
        return sendJson(res, 400, { error: 'Lead data is required' });
      }
      const session = await callManager.startCallSession(body.lead, body.campaignType || 'policy_renewal');
      return sendJson(res, 201, session);
    }

    // 7. Conversational Turn (Interactive AI Voice Simulator)
    if (pathname.includes('/turn') && method === 'POST') {
      const parts = pathname.split('/');
      const callId = parts[3];
      const body = await parseJsonBody(req);

      if (!body.customerSpeech) {
        return sendJson(res, 400, { error: 'customerSpeech text is required' });
      }

      const turnResult = await callManager.submitCustomerTurn(callId, body.customerSpeech);
      return sendJson(res, 200, turnResult);
    }

    // 8. Manual Trigger to Sync Call to Frappe CRM
    if (pathname.includes('/sync') && method === 'POST') {
      const parts = pathname.split('/');
      const callId = parts[3];
      const result = await callManager.syncCallToFrappe(callId);
      return sendJson(res, 200, result);
    }

    // 9. Campaigns List & Batch Trigger
    if (pathname === '/api/campaigns' && method === 'GET') {
      return sendJson(res, 200, { campaigns: callManager.campaigns });
    }

    if (pathname.startsWith('/api/campaigns/') && pathname.endsWith('/run') && method === 'POST') {
      const campId = pathname.split('/')[3];
      const campaign = callManager.campaigns.find(c => c.id === campId);
      if (!campaign) return sendJson(res, 404, { error: 'Campaign not found' });

      // Trigger calls for pending leads
      const leads = await callManager.frappeClient.getFollowUpLeads();
      const triggered = [];

      for (const lead of leads.slice(0, 3)) {
        const session = await callManager.startCallSession(lead, campaign.type);
        triggered.push(session.callRecord.id);
      }

      campaign.completedCalls += triggered.length;
      campaign.pendingFollowUps = Math.max(0, campaign.pendingFollowUps - triggered.length);

      return sendJson(res, 200, {
        success: true,
        campaignId: campId,
        message: `Batch voice dispatch initiated for ${triggered.length} Frappe CRM leads`,
        callIds: triggered
      });
    }

    // 10. Frappe CRM Connection Settings & Test
    if (pathname === '/api/frappe/test-connection' && method === 'POST') {
      const body = await parseJsonBody(req);
      const testClient = new FrappeCRMClient({
        baseUrl: body.baseUrl,
        apiKey: body.apiKey,
        apiSecret: body.apiSecret
      });
      const result = await testClient.testConnection();
      if (result.success) {
        // Update live client
        callManager.frappeClient = testClient;
      }
      return sendJson(res, 200, result);
    }

    // 11. Inbound Webhook from Frappe CRM
    // Frappe Server Script sends POST here whenever a Lead or Policy status updates
    if (pathname === '/api/webhooks/frappe-lead' && method === 'POST') {
      const body = await parseJsonBody(req);
      console.log('Received Frappe CRM Webhook Event:', body.event, 'for Lead:', body.lead_name || body.name);

      const lead = {
        id: body.name || `LEAD-${Date.now()}`,
        name: body.lead_name || body.customer_name || 'Valued Client',
        phone: body.mobile_no || body.phone || '+15551234567',
        policyType: body.custom_insurance_type || 'Comprehensive Auto',
        policyNumber: body.custom_policy_no || 'POL-AUT-789',
        expiryDate: body.custom_expiry_date || '2026-09-15',
        premiumAmount: body.custom_premium_amount || '$680.00',
        campaignType: body.custom_campaign_type || 'policy_renewal'
      };

      const session = await callManager.startCallSession(lead, lead.campaignType);
      return sendJson(res, 200, {
        received: true,
        callId: session.callRecord.id,
        status: 'Initiated outbound voice follow-up'
      });
    }

    // -------------------------------------------------------------
    // STATIC FILE SERVING
    // -------------------------------------------------------------
    let filePath = path.join(__dirname, 'public', pathname === '/' ? 'index.html' : pathname);

    // Prevent directory traversal
    if (!filePath.startsWith(path.join(__dirname, 'public'))) {
      res.writeHead(403);
      return res.end('Forbidden');
    }

    fs.stat(filePath, (err, stats) => {
      if (err || !stats.isFile()) {
        // Fallback to index.html for SPA
        filePath = path.join(__dirname, 'public', 'index.html');
      }

      const ext = path.extname(filePath).toLowerCase();
      const contentType = MIME_TYPES[ext] || 'application/octet-stream';

      fs.readFile(filePath, (readErr, content) => {
        if (readErr) {
          res.writeHead(500);
          res.end('Server Error loading asset');
        } else {
          res.writeHead(200, { 'Content-Type': contentType });
          res.end(content);
        }
      });
    });

  } catch (err) {
    console.error('API Error:', err);
    return sendJson(res, 500, { error: 'Internal server error', message: err.message });
  }
});

server.listen(PORT, () => {
  console.log(`=======================================================`);
  console.log(`🚀 InsureVoice AI (Frappe CRM Follow-up Engine) Started`);
  console.log(`📍 Web Dashboard: http://localhost:${PORT}`);
  console.log(`🔌 Frappe Inbound Webhook: http://localhost:${PORT}/api/webhooks/frappe-lead`);
  console.log(`⚡ Voice Model: ElevenLabs Turbo v2.5 / Cartesia Sonic`);
  console.log(`=======================================================`);
});
