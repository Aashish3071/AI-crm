// ==============================================================================
// FRAPPE CRM CLIENT SCRIPT: "📞 Trigger AI Voice Call" Button
// ==============================================================================
// How to install in Frappe CRM / ERPNext:
// 1. Open Frappe Desk -> Search "Client Script" -> Add Client Script
// 2. DocType: "CRM Lead" (or "Lead")
// 3. Apply To: Form
// 4. Paste the code below and save!
// ==============================================================================

frappe.ui.form.on('CRM Lead', {
    refresh: function(frm) {
        if (!frm.is_new() && frm.doc.mobile_no) {
            frm.add_custom_button(__('📞 Trigger AI Voice Call'), function() {
                frappe.confirm(
                    `Are you sure you want to trigger an automated natural AI voice follow-up call to <b>${frm.doc.lead_name}</b> at <b>${frm.doc.mobile_no}</b>?`,
                    function() {
                        frappe.show_alert({
                            message: __('Initiating AI Voice Follow-up...'),
                            indicator: 'blue'
                        });

                        frappe.call({
                            method: 'frappe.integrations.utils.make_post_request',
                            args: {
                                url: 'http://localhost:3030/api/webhooks/frappe-lead',
                                data: {
                                    name: frm.doc.name,
                                    lead_name: frm.doc.lead_name,
                                    mobile_no: frm.doc.mobile_no,
                                    custom_insurance_type: frm.doc.custom_insurance_type || 'Comprehensive Policy',
                                    custom_policy_no: frm.doc.custom_policy_no || 'POL-DEFAULT',
                                    custom_premium_amount: frm.doc.custom_premium_amount || '$750.00',
                                    custom_campaign_type: 'policy_renewal'
                                }
                            },
                            callback: function(r) {
                                frappe.msgprint({
                                    title: __('AI Voice Call Initiated'),
                                    indicator: 'green',
                                    message: `AI Voice agent is now dialing <b>${frm.doc.lead_name}</b>. The conversation transcript, audio recording, and sentiment analysis will be automatically synced back to this lead's Call Log upon completion.`
                                });
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __('Actions'));
        }
    }
});
