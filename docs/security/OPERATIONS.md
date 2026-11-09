# Incident response, retention and recovery runbook

Status: proposed department runbook. No real-data operator, reporting contact, storage location or retention authority is configured by these documents.

## Owners before pilot

Name primary/deputy for service operations, incident command, privacy/legal, CERT-In contact, data steward, independent reviewer and pension-scheme liaison. Publish only approved business contacts. Keep escalation details restricted and test them. No owner may approve their own adverse decision.

## Incident response

- At discovery: create incident ID and record UTC discovery time, reporter, affected service and known impact. Preserve evidence and independently anchor its hash; do not paste records/tokens into chat, public issues or standard logs. Start the CERT-In deadline tracker immediately for potentially covered incidents.
- First 15 minutes (internal target): page incident owner; isolate affected intake/export/job routes, preserve read-only appeal/help access where safe, stop further derived recommendations. Keep official pension payments unchanged. Do not destroy files or logs while containing the incident.
- First hour (internal target): assess personal-data exposure, malicious feed/model/software changes, account abuse, scope and unsafe decisions. Snapshot restricted evidence, collect access/audit/proxy/job logs and clock status. Revoke affected credentials through the department-approved process; never put credentials into tickets.
- Covered incidents: designated contact reports to CERT-In within six hours of noticing/being informed under applicable directions. Submit known facts if investigation is incomplete and supplement them. Do not wait for a root-cause report. Verify the current official reporting route/form at the time.
- Personal-data breach: privacy lead determines currently operative DPDP duties. Plan for Rule 7 notices to affected persons/Board without delay and detailed Board update within 72 hours or allowed extension once applicable. This does not replace the CERT-In clock.
- Recovery: restore a known-good immutable software/data/model version into quarantine; validate database, manifests and external audit checkpoint; replay only idempotent operations. Two named owners approve resumption; start shadow-only and review affected cases. Pension-scheme officials own any corrective benefit actions.
- Close: record root cause, timeline, scope, notices, affected decisions, fixes/retests and lessons. Remove temporary access. Schedule and test preventive changes. No automatic public disclosure or external communication is authorized by this runbook.

## Retention matrix to be approved

| Class | Proposed handling, not a statutory blanket period | Deletion/hold evidence |
| --- | --- | --- |
| Public demo fixtures | Synthetic only; reset derived demo state periodically | Reproducible fixture regeneration and no private artifacts |
| Source feed snapshots | Department-owned immutable evidence, minimum fields, per-feed lawful schedule | Manifest/version, authority, retention start/end, legal hold, steward approval |
| Quarantine/rejected files | Shortest operational time under approved purpose; restricted access; no public row dumps | Rejection counts, non-personal error code, deletion manifest |
| Review evidence/case/appeal | Scheme-specific record/appeal and litigation schedule; preserve corrections and reinstatement trail | Case closure, requester verification, retention authority and hold release |
| Security/ICT logs | At least rolling 180 days for applicable CERT-In direction; plan for operative DPDP one-year requirements and stricter sector schedules | India-resident store, access logs, verified export/restore, signed policy |
| Exports and temporary work files | Restricted, time-limited downloads; no-cache and purpose-specific access; delete after approved task | Export actor/scope/count, access expiry, verified file and backup removal |
| Backups | Encrypted, access-separated, expiring generations; no indefinite raw-data archive | Restore tests, key custody, expiry manifest, deletion tombstone replay |

Do not use 'erase all after 30 days' or 'keep everything forever'. Compute eligible dates from approved record-class policy; pause deletion on valid legal hold; require steward approval and dry-run counts before purge. Include replicas, offline exports, object versions, WAL/temp files and backups. Restored backups must reapply erasure/correction tombstones before serving. Filesystem deletion/VACUUM alone does not prove secure media erasure. Key erasure only works with correct key isolation and no remaining copies.

## Recovery acceptance drill

Department sets approved RPO/RTO, then measures them rather than assuming numbers. Restore encrypted backup into isolated host without outbound access, verify feed manifest digests, database integrity and named-actor audit chain against external checkpoint; confirm jurisdiction access and appeals; re-run sample detector output deterministically and compare versions; validate deletion tombstones, test no payment connection, record actual lost data/time and officer approval. Test operator absence and disk-full conditions. No real personal data in drill screenshots or public reports.
