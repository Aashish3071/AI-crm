# Broker User Acceptance

Use copied data only after names, email addresses, phone numbers, policy numbers, document contents and free-text notes have been anonymized outside the CRM. Never use live provider credentials in UAT.

## Entry criteria

- Automated API, security and browser checks pass.
- A fresh UAT company has been created with production-equivalent roles.
- The anonymized dataset has passed the relationship integrity report.
- Email and WhatsApp point to test/sandbox recipients.
- A backup and restore drill has completed in the UAT environment.

## Broker scenarios

| Scenario | Broker acceptance evidence | Result | Broker initials |
| --- | --- | --- | --- |
| UAT-01 New business | Lead attribution, duplicate handling, next action, conversion and issuance all match the source workflow. | Not run | |
| UAT-02 Renewal | Old policy, quotations, approval and successor policy remain linked end to end. | Not run | |
| UAT-03 Servicing | Customer 360 shows the request, policy, documents, owner and completion history. | Not run | |
| UAT-04 Work management | Overdue work reaches the correct inbox and can be assigned, snoozed and completed. | Not run | |
| UAT-05 Administration | Import errors are actionable; audit and recovery evidence is complete. | Not run | |
| UAT-06 Permissions | Broker, manager, administrator and read-only boundaries match company policy. | Not run | |

## Exit criteria

All critical scenarios must pass, no open severity-1/2 defects may remain, the broker owner must sign the table, and the migration/recovery runbook must be rehearsed once more immediately before live import.
