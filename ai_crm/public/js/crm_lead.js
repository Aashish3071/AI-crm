frappe.ui.form.on('CRM Lead', {
    refresh: function(frm) {
        // Add a custom button group for AI actions
        frm.page.add_inner_button(__('Recalculate AI Score'), function() {
            frappe.show_alert({message: __('Scoring lead via AI...'), indicator: 'blue'});
            frappe.call({
                method: 'ai_crm.api.score_lead',
                args: {
                    lead_name: frm.doc.name
                },
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        frappe.show_alert({message: __('Lead scored: ') + r.message.score + '%', indicator: 'green'});
                        frm.reload_doc();
                    } else {
                        frappe.msgprint(__('Failed to calculate AI score. Check if LM Studio is running.'));
                    }
                }
            });
        }, __('AI Tools'));

        frm.page.add_inner_button(__('Draft AI Follow-up'), function() {
            frappe.show_alert({message: __('Drafting follow-up email...'), indicator: 'blue'});
            frappe.call({
                method: 'ai_crm.api.recommend_action',
                args: {
                    lead_name: frm.doc.name
                },
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        frappe.show_alert({message: __('Follow-up drafted successfully!'), indicator: 'green'});
                        frm.reload_doc();
                    } else {
                        frappe.msgprint(__('Failed to draft follow-up email. Check if LM Studio is running.'));
                    }
                }
            });
        }, __('AI Tools'));
    }
});
