# Blueprint Assessment

Generated: 2026-09-06T06:24:07.169967+00:00

Decision: the current CRM does not yet meet the commercial blueprint. This report records demonstrated gaps without modifying the product to conceal them.

Test cases: {'PASS': 105, 'FAIL': 8, 'BLOCKED': 4}. Criterion register: {'PARTIAL': 60, 'PASS': 8, 'BLOCKED': 4, 'NOT VERIFIED': 4, 'FAIL': 8}.

Read the [target blueprint](CRM_BLUEPRINT.md) first. [Machine-readable evidence](blueprint-results.json) contains source hashes, individual results and the endpoint observation inventory.

Passing scenarios demonstrate only their assertions. PARTIAL is not a release pass. FAIL means a reproducible violation. BLOCKED names an unavailable external prerequisite. NOT VERIFIED means missing/errored execution. Every one of the 84 criteria is listed below.

## Highest-priority remediation

1. Access and identity: bind Profile to the session; prevent editing another user's profile; derive note authorship from the authenticated actor.
2. Policy and renewal integrity: reject invalid terms/amounts, enforce actual issuance evidence, validate quote ownership/validity and make renewal completion idempotent.
3. Relationship continuity: unify source/import next-action creation, synchronize conversion/master changes, protect edited imports and complete the deletion/service graph.
4. Work and communication: finish service/renewal alerts, manager escalation, quote calendar validity, consent continuity and safe send/callback retries.
5. Operator experience: deal/note editing gaps, task search, truthful dashboard calculations, report periods and configuration-driven validation.
6. Production proof: complete authorized provider sandboxes, PostgreSQL/object storage/scanner testing, worker crash/retry, accessibility/load and broker UAT.

## Journey verdicts

- J01: **PARTIAL**. Failed component criteria: none demonstrated. This is a component-derived verdict, not a completed production journey.
- J02: **FAIL**. Failed component criteria: M24.3. This is a component-derived verdict, not a completed production journey.
- J03: **FAIL**. Failed component criteria: M19.2. This is a component-derived verdict, not a completed production journey.
- J04: **FAIL**. Failed component criteria: M14.2. This is a component-derived verdict, not a completed production journey.
- J05: **FAIL**. Failed component criteria: M26.3. This is a component-derived verdict, not a completed production journey.
- J06: **PARTIAL**. Failed component criteria: none demonstrated. This is a component-derived verdict, not a completed production journey.
- J07: **FAIL**. Failed component criteria: M22.2. This is a component-derived verdict, not a completed production journey.

## Criterion-by-criterion register

### M01 — Dashboard and onboarding

- **M01.1 — PARTIAL**: startup opens Dashboard and primary navigation remains usable at a narrow mobile viewport.
  - PASS: `test_read_contract_` ([test](../tests/test_blueprint_acceptance.py#L705)). 
- **M01.2 — PASS**: “Tasks due today” contains only today's active tasks, excluding future, completed and archived work.
  - PASS: `test_dashboard_today_filters_dates_and_archives` ([test](../tests/test_blueprint_acceptance.py#L83)). 
- **M01.3 — PARTIAL**: pipeline premium preserves decimal amounts and excludes closed opportunities from open-pipeline value; date-labelled KPIs use their stated period.
  - PASS: `test_dashboard_preserves_decimal_premium` ([test](../tests/test_blueprint_acceptance.py#L93)). 

### M02 — Login, users, profile and hierarchy

- **M02.1 — PARTIAL**: unauthenticated access and missing-CSRF mutations fail; tenant and read-only boundaries hold, including direct record requests.
  - PASS: `test_auth_csrf_roles_and_company_isolation` ([test](../test_security_foundation.py#L40)). 
  - PASS: `test_read_contract_api_auth_status` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - PASS: `test_logout_clears_current_browser_access` ([test](../tests/test_blueprint_acceptance.py#L677)). 
- **M02.2 — PARTIAL**: profile editing changes the signed-in user's identity/profile, not another team member selected by a shared company setting.
  - PASS: `test_profile_is_signed_in_identity` ([test](../tests/test_blueprint_acceptance.py#L633)). 
- **M02.3 — PARTIAL**: deactivation revokes access immediately and a user cannot become their own manager or form a reporting cycle.
  - PASS: `test_auth_csrf_roles_and_company_isolation` ([test](../test_security_foundation.py#L40)). 
  - PASS: `test_read_contract_api_users_hierarchy` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - PASS: `test_reporting_hierarchy_rejects_cycles` ([test](../tests/test_blueprint_acceptance.py#L476)). 

### M03 — Lead Sources

- **M03.1 — PARTIAL**: a valid signed synthetic webhook creates one attributed lead; replay does not create duplicates and invalid signatures fail.
  - PASS: `test_lead_source_connect_test_ingest_and_deduplicate` ([test](../test_insurance_operations.py#L249)). 
  - PASS: `test_source_update_sample_disconnect_and_invalid_oauth` ([test](../tests/test_blueprint_acceptance.py#L590)). 
- **M03.2 — PARTIAL**: an ingested lead has a linked canonical first task and contact/organization relationships, matching direct-entry behavior.
  - PASS: `test_webhook_ingestion_has_canonical_task_reference` ([test](../tests/test_blueprint_acceptance.py#L100)). 
- **M03.3 — BLOCKED**: a real provider sandbox completes authorization, asset selection, subscription, delivery, token renewal and disconnect without manual database edits.
  - BLOCKED: `test_real_lead_source_oauth_lifecycle` ([test](../tests/test_blueprint_acceptance.py#L687)). No authorized provider sandbox/asset and callback subscription supplied for this audit

### M04 — Spreadsheet import

- **M04.1 — PARTIAL**: mapped import accepts valid rows, reports invalid rows and preserves a retrievable import result/error file.
  - PASS: `test_import_mapping_and_error_download` ([test](../tests/test_blueprint_acceptance.py#L109)). 
  - PASS: `test_read_contract_api_imports` ([test](../tests/test_blueprint_acceptance.py#L705)). 
- **M04.2 — PASS**: imported leads receive the same canonical next-action/task relationship as directly entered leads.
  - PASS: `test_imported_lead_links_canonical_task` ([test](../tests/test_blueprint_acceptance.py#L117)). 
- **M04.3 — PARTIAL**: retrying a committed batch does not duplicate records; rollback preserves records subsequently edited/converted or reports a conflict.
  - PASS: `test_import_retry_and_rollback_preserves_edited_lead` ([test](../tests/test_blueprint_acceptance.py#L124)). 

### M05 — Assignment rules

- **M05.1 — PARTIAL**: preview does not alter rotation state; supported rule creation, editing and ordering are retrievable.
  - PASS: `test_assignment_rule_crud_and_preview` ([test](../tests/test_blueprint_acceptance.py#L531)). 
  - PASS: `test_rule_preview_does_not_consume_rotation` ([test](../tests/test_blueprint_acceptance.py#L135)). 
- **M05.2 — PARTIAL**: bulk lead reassignment propagates to open tasks, appointments and notification ownership with conflict protection.
  - PASS: `test_lead_edit_and_bulk_work_management_sync` ([test](../test_insurance_operations.py#L186)). 
  - PASS: `test_bulk_assignment_moves_appointment_and_notification_together` ([test](../tests/test_workflow_integrity.py#L57)). 
- **M05.3 — PARTIAL**: direct-entry, imported and webhook leads apply the same enabled routing rules when no explicit owner is supplied.
  - PASS: `test_direct_entry_uses_enabled_routing` ([test](../tests/test_blueprint_acceptance.py#L142)). 

### M06 — Leads and Accounts

- **M06.1 — NOT VERIFIED**: authenticated browser creation and stage change persist; conversion can be reached from the lead row.
  - Evidence: no sufficient automated test executed for this criterion; manual/source inspection does not establish a pass.
- **M06.2 — PARTIAL**: canonical task rename/date/completion updates the lead; failed conflicting changes roll back.
  - PASS: `test_lead_edit_and_bulk_work_management_sync` ([test](../test_insurance_operations.py#L186)). 
  - PASS: `test_canonical_task_rename_date_and_completion_update_lead` ([test](../tests/test_workflow_integrity.py#L27)). 
  - PASS: `test_task_and_calendar_moves_cannot_bypass_conflicts` ([test](../tests/test_workflow_integrity.py#L37)). 
- **M06.3 — PARTIAL**: invalid stages and Lost without a reason are rejected; only configured valid stages are accepted.
  - PASS: `test_lead_invalid_stage_and_loss_reason` ([test](../tests/test_blueprint_acceptance.py#L152)). 

### M07 — Pipeline Deals

- **M07.1 — PARTIAL**: an independent deal can be created, edited and linked to its customer or lead through supported API/UI paths.
  - PASS: `test_independent_deal_creation_exists` ([test](../tests/test_blueprint_acceptance.py#L160)). 
- **M07.2 — PASS**: converting a lead with an existing deal sets that deal to Won and links the converted customer, without creating a second deal.
  - PASS: `test_conversion_updates_existing_deal` ([test](../tests/test_blueprint_acceptance.py#L167)). 
- **M07.3 — PARTIAL**: expected close date appears once in Calendar and opens the deal context.
  - PASS: `test_deal_close_is_projected_to_calendar` ([test](../tests/test_blueprint_acceptance.py#L178)). 

### M08 — Guided conversion

- **M08.1 — PARTIAL**: conversion creates a customer and linked draft policy, keeps source history, and rejects/reuses a repeated conversion without duplicating records.
  - PASS: `test_end_to_end_lead_to_renewed_policy` ([test](../test_insurance_operations.py#L151)). 
  - PASS: `test_conversion_retry_does_not_duplicate` ([test](../tests/test_blueprint_acceptance.py#L186)). 
- **M08.2 — PARTIAL**: choosing a different organization during conversion produces a valid organization ID and consistent customer/contact/policy relationships.
  - PASS: `test_conversion_new_organization_has_stable_relationship` ([test](../tests/test_blueprint_acceptance.py#L195)). 
- **M08.3 — PASS**: already scheduled lead appointments and follow-ups remain visible under the converted customer.
  - PASS: `test_calendar_canonical_projection_and_two_way_sync` ([test](../test_insurance_operations.py#L94)). 
  - PASS: `test_conversion_keeps_appointments_and_followups_in_360` ([test](../tests/test_blueprint_acceptance.py#L482)). 

### M09 — Customers and Customer 360°

- **M09.1 — PARTIAL**: multiple policies and contacts belong to one customer and are included in its 360° response.
  - PASS: `test_master_record_editing_customer_360_and_audit` ([test](../test_insurance_operations.py#L199)). 
  - PASS: `test_multiple_contacts_and_policies_in_customer_360` ([test](../tests/test_blueprint_acceptance.py#L203)). 
- **M09.2 — PARTIAL**: profile edits show consistently in linked active policy/customer labels without changing IDs or historical snapshots.
  - PASS: `test_customer_rename_updates_policy_label` ([test](../tests/test_blueprint_acceptance.py#L214)). 
- **M09.3 — PARTIAL**: 360° includes related appointments, tasks, notes, communications, documents and servicing, including policy-linked items.
  - PASS: `test_customer_360_includes_servicing` ([test](../tests/test_blueprint_acceptance.py#L492)). 

### M10 — Organizations

- **M10.1 — PARTIAL**: organization creation and editing persist and are audited.
  - PASS: `test_master_record_editing_customer_360_and_audit` ([test](../test_insurance_operations.py#L199)). 
  - PASS: `test_organization_create_edit_audit` ([test](../tests/test_blueprint_acceptance.py#L221)). 
- **M10.2 — PARTIAL**: renaming an organization updates active display labels through stable IDs across customers, contacts and policies.
  - PASS: `test_organization_rename_updates_customer_label` ([test](../tests/test_blueprint_acceptance.py#L228)). 
- **M10.3 — PARTIAL**: invalid relationship IDs are rejected rather than saved as disconnected masters.
  - PASS: `test_contact_rejects_nonexistent_parent` ([test](../tests/test_blueprint_acceptance.py#L236)). 

### M11 — Contacts

- **M11.1 — PARTIAL**: multiple contacts can be created and edited without overwriting each other.
  - PASS: `test_master_record_editing_customer_360_and_audit` ([test](../test_insurance_operations.py#L199)). 
  - PASS: `test_multiple_contacts_and_policies_in_customer_360` ([test](../tests/test_blueprint_acceptance.py#L203)). 
- **M11.2 — PASS**: editing a lead's primary contact details preserves a secondary contact's name and details.
  - PASS: `test_secondary_contact_survives_lead_edit` ([test](../tests/test_blueprint_acceptance.py#L241)). 
- **M11.3 — PARTIAL**: nonexistent customer/organization references cannot be saved to contacts.
  - PASS: `test_contact_rejects_nonexistent_parent` ([test](../tests/test_blueprint_acceptance.py#L236)). 

### M12 — Action Tasks

- **M12.1 — PARTIAL**: task creation rejects invalid dates and missing titles; edits synchronize canonical related work.
  - PASS: `test_canonical_task_rename_date_and_completion_update_lead` ([test](../tests/test_workflow_integrity.py#L27)). 
  - PASS: `test_deleting_appointment_task_archives_calendar_and_resolves_alert` ([test](../tests/test_blueprint_acceptance.py#L553)). 
  - PASS: `test_task_validation` ([test](../tests/test_blueprint_acceptance.py#L249)). 
- **M12.2 — NOT VERIFIED**: rejected browser saves show the server error and preserve the open form; archived tasks are excluded from active lists.
  - Evidence: no sufficient automated test executed for this criterion; manual/source inspection does not establish a pass.
- **M12.3 — NOT VERIFIED**: a task linked to a customer opens customer context rather than a lead drawer.
  - Evidence: no sufficient automated test executed for this criterion; manual/source inspection does not establish a pass.

### M13 — Calendar

- **M13.1 — PARTIAL**: appointment and linked task appear once in Calendar; edits synchronize both ways; booking/follow-up works in the authenticated browser.
  - PASS: `test_calendar_canonical_projection_and_two_way_sync` ([test](../test_insurance_operations.py#L94)). 
  - PASS: `test_legacy_same_day_task_is_not_mistaken_for_next_action` ([test](../tests/test_workflow_integrity.py#L117)). 
- **M13.2 — PARTIAL**: conflict checks apply through task edits and Calendar moves, including cross-midnight appointments.
  - PASS: `test_calendar_conflicts_reminders_archive_and_repair` ([test](../test_insurance_operations.py#L123)). 
  - PASS: `test_conflicts_across_midnight_and_invalid_duration` ([test](../tests/test_workflow_integrity.py#L50)). 
  - PASS: `test_task_and_calendar_moves_cannot_bypass_conflicts` ([test](../tests/test_workflow_integrity.py#L37)). 
- **M13.3 — PARTIAL**: timezone validation rejects invalid zones; DST nonexistent/ambiguous local times require explicit handling rather than silent reinterpretation.
  - PASS: `test_calendar_rejects_dst_nonexistent_time` ([test](../tests/test_blueprint_acceptance.py#L254)). 

### M14 — Notifications, reminders and escalation

- **M14.1 — PARTIAL**: upcoming work creates a deduplicated notification; completed/deleted work resolves alerts and reassignment updates the owner.
  - PASS: `test_calendar_conflicts_reminders_archive_and_repair` ([test](../test_insurance_operations.py#L123)). 
  - PASS: `test_policy_document_checklist_and_notification_workflow` ([test](../test_insurance_operations.py#L234)). 
  - PASS: `test_whatsapp_delivery_failure_updates_timeline_and_notifies_owner` ([test](../test_insurance_operations.py#L65)). 
  - PASS: `test_bulk_assignment_moves_appointment_and_notification_together` ([test](../tests/test_workflow_integrity.py#L57)). 
  - PASS: `test_deleting_appointment_task_archives_calendar_and_resolves_alert` ([test](../tests/test_blueprint_acceptance.py#L553)). 
- **M14.2 — FAIL**: renewal/service/task/appointment reassignment and completion consistently update their own related alerts.
  - FAIL: `test_completed_renewal_resolves_renewal_alert` ([test](../tests/test_blueprint_acceptance.py#L260)). True is not false : Closed renewal retains an unread overdue alert
- **M14.3 — PARTIAL**: a restarted durable worker processes due work once across concurrent workers; escalation reaches the configured manager after the configured delay.
  - PASS: `test_audit_chain_and_scheduler_concurrency_guard` ([test](../test_insurance_operations.py#L356)). 
  - PASS: `test_relational_repair_service_request_and_scheduler` ([test](../test_insurance_operations.py#L319)). 
  - PASS: `test_overdue_escalation_reaches_configured_manager` ([test](../tests/test_blueprint_acceptance.py#L500)). 
  - PASS: `test_read_contract_api_admin_jobs` ([test](../tests/test_blueprint_acceptance.py#L705)). 

### M15 — Activity Notes

- **M15.1 — PARTIAL**: notes persist with their relationship and remain archived when their lead is deleted.
  - PASS: `test_lead_delete_cascades_but_archives_notes` ([test](../test_insurance_operations.py#L169)). 
  - PASS: `test_explicit_note_delete_and_list` ([test](../tests/test_blueprint_acceptance.py#L608)). 
- **M15.2 — PARTIAL**: a user can correct a note through a supported edit operation with an audit record.
  - PASS: `test_note_edit_is_supported` ([test](../tests/test_blueprint_acceptance.py#L269)). 
- **M15.3 — PARTIAL**: note authorship uses the authenticated actor, not a caller-supplied impersonation label.
  - PASS: `test_note_author_cannot_be_impersonated` ([test](../tests/test_blueprint_acceptance.py#L651)). 

### M16 — Quotations and comparison

- **M16.1 — PARTIAL**: quote selection rejects an offer belonging to another renewal/opportunity and rejects an expired offer.
  - PASS: `test_expired_quote_cannot_be_selected` ([test](../tests/test_blueprint_acceptance.py#L283)). 
  - PASS: `test_quote_from_another_renewal_cannot_be_selected` ([test](../tests/test_blueprint_acceptance.py#L276)). 
- **M16.2 — PASS**: quotation validity uses one field contract across create/edit and Calendar projection.
  - PASS: `test_quote_edit_uses_same_validity_field` ([test](../tests/test_blueprint_acceptance.py#L600)). 
  - PASS: `test_quote_validity_appears_in_calendar` ([test](../tests/test_blueprint_acceptance.py#L289)). 
- **M16.3 — PARTIAL**: new-business quotes can attach to an open deal before any existing policy renewal; selected terms/version remain traceable in issuance.
  - PASS: `test_new_business_quote_without_renewal` ([test](../tests/test_blueprint_acceptance.py#L296)). 

### M17 — Policies and issuance

- **M17.1 — PARTIAL**: backend calculates decimal premium and tax consistently; negative values and invalid/reversed term dates are rejected.
  - PASS: `test_negative_policy_premium_rejected` ([test](../tests/test_blueprint_acceptance.py#L308)). 
  - PASS: `test_policy_financial_calculation` ([test](../tests/test_blueprint_acceptance.py#L302)). 
  - PASS: `test_reversed_policy_term_rejected` ([test](../tests/test_blueprint_acceptance.py#L314)). 
- **M17.2 — PARTIAL**: issuance requires insurer, number, term and real linked checklist evidence; another update endpoint cannot bypass issuance gates.
  - PASS: `test_policy_document_checklist_and_notification_workflow` ([test](../test_insurance_operations.py#L234)). 
  - PASS: `test_issuance_checkboxes_are_not_document_evidence` ([test](../tests/test_blueprint_acceptance.py#L326)). 
  - PASS: `test_policy_activation_cannot_bypass_issuance` ([test](../tests/test_blueprint_acceptance.py#L320)). 
- **M17.3 — PARTIAL**: new policies belong to a valid customer; policy modifications are audited and visible in customer history.
  - PASS: `test_end_to_end_lead_to_renewed_policy` ([test](../test_insurance_operations.py#L151)). 
  - PASS: `test_policy_document_checklist_and_notification_workflow` ([test](../test_insurance_operations.py#L234)). 

### M18 — Renewals

- **M18.1 — PARTIAL**: generation excludes drafts/cancelled policies and does not create two active renewals for the same policy term.
  - PASS: `test_policy_renewal_and_quotation_flow` ([test](../test_insurance_operations.py#L38)). 
  - PASS: `test_read_contract_api_renewals` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - PASS: `test_renewal_generation_excludes_drafts` ([test](../tests/test_blueprint_acceptance.py#L333)). 
- **M18.2 — PARTIAL**: completing the same renewal twice creates at most one successor policy, preserving predecessor links and customer continuity.
  - PASS: `test_end_to_end_lead_to_renewed_policy` ([test](../test_insurance_operations.py#L151)). 
  - PASS: `test_renewal_completion_retry_is_idempotent` ([test](../tests/test_blueprint_acceptance.py#L340)). 
- **M18.3 — PARTIAL**: loss/lapse requires a reason and completion requires a selected quote plus valid issuance evidence.
  - PASS: `test_end_to_end_lead_to_renewed_policy` ([test](../test_insurance_operations.py#L151)). 
  - PASS: `test_policy_renewal_and_quotation_flow` ([test](../test_insurance_operations.py#L38)). 

### M19 — Servicing and endorsements

- **M19.1 — PASS**: a service request cannot use a policy belonging to a different customer.
  - PASS: `test_relational_repair_service_request_and_scheduler` ([test](../test_insurance_operations.py#L319)). 
  - PASS: `test_service_rejects_other_customers_policy` ([test](../tests/test_blueprint_acceptance.py#L350)). 
- **M19.2 — FAIL**: endorsement completion synchronizes its servicing workflow; linked service work is visible in 360°/Calendar and alerts.
  - PASS: `test_relational_repair_service_request_and_scheduler` ([test](../test_insurance_operations.py#L319)). 
  - FAIL: `test_endorsement_tracks_service_completion` ([test](../tests/test_blueprint_acceptance.py#L357)). 422 not less than 300 : Setup/action put /api/service-requests/SR_08a0a70c: 422 {"detail":"Resolution outcome is mandatory when completing a service request"}
- **M19.3 — PARTIAL**: completing a service request requires an outcome/evidence appropriate to the request rather than losing unresolved work.
  - PASS: `test_service_completion_requires_outcome` ([test](../tests/test_blueprint_acceptance.py#L366)). 

### M20 — Communications: Email and WhatsApp

- **M20.1 — PARTIAL**: missing provider configuration does not claim successful delivery; SMS is rejected.
  - PASS: `test_sms_is_removed_saved_filters_paginate_and_reports_segment` ([test](../test_insurance_operations.py#L297)). 
  - PASS: `test_record_message_options_and_unconfigured_send` ([test](../tests/test_blueprint_acceptance.py#L582)). 
  - PASS: `test_unconfigured_sender_does_not_claim_delivery` ([test](../tests/test_blueprint_acceptance.py#L373)). 
- **M20.2 — PARTIAL**: delivered/read states do not regress from older callbacks; a replay cannot duplicate a delivery event or resend an already sent message.
  - PASS: `test_whatsapp_delivery_failure_updates_timeline_and_notifies_owner` ([test](../test_insurance_operations.py#L65)). 
  - PASS: `test_out_of_order_delivery_does_not_regress_read` ([test](../tests/test_blueprint_acceptance.py#L381)). 
  - PASS: `test_sent_message_retry_does_not_dispatch_twice` ([test](../tests/test_blueprint_acceptance.py#L518)). 
- **M20.3 — BLOCKED**: real sandbox Email and WhatsApp delivery, inbound replies, bounce/failure, opt-out and retry are verified with provider evidence.
  - BLOCKED: `test_real_email_whatsapp_delivery_and_reply` ([test](../tests/test_blueprint_acceptance.py#L691)). No authorized sandbox recipient/provider environment; no external messages sent

### M21 — Templates and consent

- **M21.1 — PARTIAL**: reusable templates can be created, edited, archived and restored; archive is distinct from sending.
  - PASS: `test_message_template_archive_restore_and_permanent_delete` ([test](../test_insurance_operations.py#L275)). 
  - PASS: `test_template_edit_and_whatsapp_local_lifecycle` ([test](../tests/test_blueprint_acceptance.py#L571)). 
- **M21.2 — PARTIAL**: customer-level opt-out is honored for customer-linked messages and after lead conversion, not only on the original lead ID.
  - PASS: `test_opt_out_blocks_delivery` ([test](../test_insurance_operations.py#L55)). 
  - PASS: `test_lead_opt_out_survives_customer_conversion` ([test](../tests/test_blueprint_acceptance.py#L389)). 
  - PASS: `test_read_contract_api_consents` ([test](../tests/test_blueprint_acceptance.py#L705)). 
- **M21.3 — PARTIAL**: invalid template references/unresolved variables and unapproved WhatsApp templates cannot silently become queued outbound messages.
  - PASS: `test_missing_template_reference_rejected` ([test](../tests/test_blueprint_acceptance.py#L398)). 
  - PASS: `test_template_edit_and_whatsapp_local_lifecycle` ([test](../tests/test_blueprint_acceptance.py#L571)). 

### M22 — Documents

- **M22.1 — PARTIAL**: supported files are versioned and readable; unsupported extensions/content mismatch are rejected.
  - PASS: `test_document_versioning_backup_and_health` ([test](../test_insurance_operations.py#L210)). 
  - PASS: `test_document_list_preview_archive_and_invalid_type` ([test](../tests/test_blueprint_acceptance.py#L561)). 
- **M22.2 — FAIL**: nonexistent/wrong-company record references are rejected before storage, and failed metadata saves do not leave untracked objects.
  - FAIL: `test_document_rejects_missing_parent_before_storage` ([test](../tests/test_blueprint_acceptance.py#L405)). 200 not found in {404, 422} : Document upload accepted a nonexistent parent
- **M22.3 — BLOCKED**: production private-object access, malware scanning and object restoration are verified against the deployed services.
  - BLOCKED: `test_deployed_private_storage_scan_and_restore` ([test](../tests/test_blueprint_acceptance.py#L695)). Requires disposable production-equivalent object storage and malware scanner

### M23 — Search, filters and navigation

- **M23.1 — PARTIAL**: search returns stable typed IDs and pagination boundaries work on leads.
  - PASS: `test_sms_is_removed_saved_filters_paginate_and_reports_segment` ([test](../test_insurance_operations.py#L297)). 
  - PASS: `test_read_contract_api_entities` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - PASS: `test_search_and_lead_pagination` ([test](../tests/test_blueprint_acceptance.py#L410)). 
- **M23.2 — PASS**: saved views are user-owned, persist criteria and do not expose another user's private view.
  - PASS: `test_sms_is_removed_saved_filters_paginate_and_reports_segment` ([test](../test_insurance_operations.py#L297)). 
  - PASS: `test_private_saved_view_is_not_visible_or_deletable_by_peer` ([test](../tests/test_blueprint_acceptance.py#L659)). 
- **M23.3 — FAIL**: search can find tasks/service work as well as customer masters; lists remain usable at realistic volume with bounded responses.
  - FAIL: `test_global_search_finds_task_work` ([test](../tests/test_blueprint_acceptance.py#L419)). False is not true : Global search cannot find action tasks

### M24 — Reporting

- **M24.1 — FAIL**: win rate is Won / (Won + Lost); conversion is converted leads / eligible leads, clearly labelled with period and population.
  - FAIL: `test_conversion_metric_uses_all_eligible_leads` ([test](../tests/test_blueprint_acceptance.py#L425)). 100.0 != 50 : Labelled conversion metric uses closed-only win-rate denominator
- **M24.2 — PARTIAL**: open-work counts exclude completed/archived tasks and aggregate owners consistently with the work queue.
  - PASS: `test_sms_is_removed_saved_filters_paginate_and_reports_segment` ([test](../test_insurance_operations.py#L297)). 
  - PASS: `test_report_excludes_archived_work` ([test](../tests/test_blueprint_acceptance.py#L433)). 
- **M24.3 — FAIL**: reports support a date cohort/period and reconcile to underlying eligible records; retained premium and renewal retention have explicit denominators.
  - PASS: `test_read_contract_api_renewals_report` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - FAIL: `test_report_period_filters_population` ([test](../tests/test_blueprint_acceptance.py#L439)). 1 != 0 : Report ignored requested historical period

### M25 — Company settings

- **M25.1 — PARTIAL**: invalid timezone/reminder values are rejected; valid settings are retrievable.
  - PASS: `test_settings_timezone_validation` ([test](../tests/test_blueprint_acceptance.py#L445)). 
- **M25.2 — FAIL**: configured lead stages are accepted by transition validation and included in pipeline/reporting, or unsupported configuration is rejected explicitly.
  - FAIL: `test_configured_stage_is_used_by_transition_engine` ([test](../tests/test_blueprint_acceptance.py#L451)). 422 != 200 : Settings accepted a stage the transition engine rejects
- **M25.3 — PARTIAL**: product and insurer choices drive relevant forms and validation consistently; existing records survive configuration changes.
  - PASS: `test_configured_product_choices_are_enforced` ([test](../tests/test_blueprint_acceptance.py#L510)). 

### M26 — Duplicates, merge, archive and deletion

- **M26.1 — PARTIAL**: merge relinks operational references and refuses implicit merging of distinct converted customers.
  - PASS: `test_archive_restore_duplicate_merge_and_report` ([test](../test_insurance_operations.py#L221)). 
  - PASS: `test_merge_relinks_appointments_and_converted_customer` ([test](../tests/test_workflow_integrity.py#L71)). 
- **M26.2 — PARTIAL**: archive/restore does not reopen previously archived tasks; lead deletion retains archived notes.
  - PASS: `test_archive_restore_duplicate_merge_and_report` ([test](../test_insurance_operations.py#L221)). 
  - PASS: `test_lead_delete_cascades_but_archives_notes` ([test](../test_insurance_operations.py#L169)). 
  - PASS: `test_archive_restore_does_not_reopen_previously_archived_tasks` ([test](../tests/test_workflow_integrity.py#L106)). 
  - PASS: `test_policy_archive_restore_retains_identity` ([test](../tests/test_blueprint_acceptance.py#L543)). 
  - PASS: `test_read_contract_api_archived_leads` ([test](../tests/test_blueprint_acceptance.py#L705)). 
  - PASS: `test_read_contract_api_demo_data` ([test](../tests/test_blueprint_acceptance.py#L705)). 
- **M26.3 — FAIL**: deleting a lead removes dependent servicing/endorsement/calendar relationships while retaining independent shared records; no dangling IDs remain.
  - FAIL: `test_lead_delete_removes_dependent_service_graph` ([test](../tests/test_blueprint_acceptance.py#L461)). True is not false : Cascade left servicing records pointing at deleted policy/customer

### M27 — Audit and accountability

- **M27.1 — PARTIAL**: core mutations produce actor/company-labelled audit events and chain verification detects tampering.
  - PASS: `test_audit_chain_and_scheduler_concurrency_guard` ([test](../test_insurance_operations.py#L356)). 
  - PASS: `test_master_record_editing_customer_360_and_audit` ([test](../test_insurance_operations.py#L199)). 
  - PASS: `test_read_contract_api_admin_integrity` ([test](../tests/test_blueprint_acceptance.py#L705)). 
- **M27.2 — PARTIAL**: integration replay, migration, assignment and archive operations are audited; no mutating route is silently exempt.
  - PASS: `test_legacy_policy_migration_is_audited` ([test](../tests/test_blueprint_acceptance.py#L469)). 
- **M27.3 — PARTIAL**: rejected role access cannot modify another team member's profile or administrative credentials through alternate endpoints.
  - PASS: `test_broker_cannot_bypass_import_permission_on_legacy_endpoint` ([test](../tests/test_blueprint_acceptance.py#L670)). 
  - PASS: `test_broker_cannot_switch_edit_another_profile` ([test](../tests/test_blueprint_acceptance.py#L639)). 

### M28 — Persistence, recovery, deployment and accessibility

- **M28.1 — PARTIAL**: concurrent local writers cannot silently overwrite each other; corrupt storage is not replaced with demo data; logical restore keeps a safety copy.
  - PASS: `test_document_versioning_backup_and_health` ([test](../test_insurance_operations.py#L210)). 
  - PASS: `test_restore_replaces_changed_data_and_keeps_safety_copy` ([test](../test_insurance_operations.py#L347)). 
  - PASS: `test_concurrent_writers_reject_stale_snapshot_without_lost_update` ([test](../tests/test_workflow_integrity.py#L80)). 
  - PASS: `test_corrupt_database_is_not_overwritten_with_demo_records` ([test](../tests/test_workflow_integrity.py#L98)). 
- **M28.2 — BLOCKED**: production PostgreSQL migration, constraints, concurrent writes, worker restarts and database-plus-object recovery are rehearsed with measured RPO/RTO.
  - BLOCKED: `test_postgres_migration_and_combined_recovery` ([test](../tests/test_blueprint_acceptance.py#L699)). Requires designated disposable PostgreSQL/object-store environment and measured restore drill
- **M28.3 — NOT VERIFIED**: authenticated screens load without JavaScript/request failures, mobile layouts avoid horizontal overflow, and full keyboard/screen-reader and load testing are completed.
  - Evidence: no sufficient automated test executed for this criterion; manual/source inspection does not establish a pass.

## Endpoint observation scope

Registered routes: 159; observed by API tests: 145; unobserved by API tests: 14.

Observed TestClient method/path requests only. Browser requests are not counted. A route hit is not full functional coverage.

Unobserved routes remain explicitly unverified at the request level; some may be visited in browser tests. AI advisor routes are outside the CRM acceptance boundary.

- `GET /api/dashboard/layout` — `get_dashboard_layout`, pipecat_server.py:909
- `PUT /api/dashboard/layout` — `save_dashboard_layout`, pipecat_server.py:921
- `POST /api/notes/{id}/archive` — `archive_note`, pipecat_server.py:1516
- `POST /api/notes/{id}/restore` — `restore_note`, pipecat_server.py:1527
- `DELETE /api/customers/{id}` — `delete_customer`, pipecat_server.py:1966
- `GET /api/communications/{id}` — `get_communication`, pipecat_server.py:2804
- `GET /api/webhooks/{company_id}/{channel_id}` — `verify_company_channel_webhook`, pipecat_server.py:4163
- `POST /api/webhooks/{company_id}/{channel_id}` — `receive_company_channel_webhook`, pipecat_server.py:4170
- `GET /api/webhooks/{channel_id}` — `verify_channel_webhook`, pipecat_server.py:4177
- `POST /api/channel-events/{id}/reprocess` — `reprocess_channel_event`, pipecat_server.py:4248
- `POST /api/demo-data/purge` — `purge_demo_data`, pipecat_server.py:4988
- `PUT /api/users/{id}` — `update_user`, pipecat_server.py:5579
- `GET /api/ai-advisor/status` — `advisor_status`, pipecat_server.py:6120
- `POST /api/ai-advisor` — `ai_advisor_query`, pipecat_server.py:6147

## Repeat the comparison

```bash
PYTHONWARNINGS=ignore .venv/bin/python3 -m tests.run_blueprint_audit --browser
```

The runner refuses a deployed browser target or configured database. It writes only the evidence files and disposable test data. Exit 1 is intentional when blueprint defects remain; no expected-failure decorators hide them. Product files are unchanged by this assessment.

External and manual acceptance remains necessary. A full keyboard/screen-reader audit, realistic load run, provider round trip and combined database/document recovery were not executed here. Existing green smoke tests must not be interpreted as proof that these checks passed.

Optional PostgreSQL adapter tests run when CRM_BLUEPRINT_PG_DSN names a designated disposable localhost database named blueprint. These cover adapter transactions/rollback, competing writers, company isolation, archived targets and scheduler locks; they do not certify the full deployment or combined recovery.
