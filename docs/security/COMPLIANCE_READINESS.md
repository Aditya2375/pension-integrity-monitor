# Privacy, security and government audit readiness

As of 2026-11-04. Design notes, not legal advice, certification or permission to access government data. A department must appoint accountable owners and counsel before any real-data pilot. Source titles and links are in SOURCES.md.

## DPDP status and design

G.S.R. 843(E) phases commencement: listed institutional provisions at publication, section 6(9) and section 27(1)(d) after one year, and most processing/rights duties after eighteen months. Rule 1 of G.S.R. 846(E) likewise phases Rules 1, 2 and 17-21 at publication; Rule 4 after one year; Rules 3, 5-16, 22 and 23 after eighteen months. The Gazette is dated 13 November 2025 with a 14 November upload/publication identifier. Do not convert this into an unverified calendar deadline: legal owner must confirm the operative publication date, current amendments and December 2025 corrigendum. As of this review it is inaccurate to say all processing obligations are already in force. Design to them now and recheck before launch.

| Design requirement | Required implementation/evidence | Current gap |
| --- | --- | --- |
| Purpose and lawful processing | Department names the Data Fiduciary, processor contract, feed-level purpose/legal basis, notice language, permitted recipients and retention authority | No real-data agreement exists in reviewed repo |
| Limited lawful government use | Counsel assesses Act section 7 and Rule 5/Second Schedule where applicable, not a blanket government exemption or consent waiver | No project-wide inference is allowed |
| Notice and rights | Plain standalone notice, itemised fields, purposes and contact; access/correction/erasure/grievance channel with verified requester identity | Public appeal is not a complete privacy-rights workflow |
| Minimise linkage | Prefer purpose-specific tokens/derived activity summaries; keep identifiers local to authorised authority; prohibit unrelated central pooling | Prototype stores raw Aadhaar, PAN, account, phone and address |
| Accurate decisions | Versioned source provenance, correction propagation, conflict/missingness flags, representative validation, human review | Scoring output is not a death declaration |
| Security safeguards | Encryption at rest/in transit, masking/tokenisation, least privilege, monitoring, backups, processor clauses and tested recovery (Rule 6 target) | SQLite file alone is not encryption or access isolation |
| Breach response | Rule 7 target: affected principals and Board without delay, detailed Board information within 72 hours or permitted extension | Separate from CERT-In six-hour clock; effective-date check required |
| Retention/erasure | Rule 6 security evidence and Rule 8(3) describe one-year retention when operative; reconcile with CERT-In 180-day ICT logs, record schedules and legal holds | No automatic deletion until approved matrix exists |
| Significant Data Fiduciary | Assess only if designated; Rule 13 has periodic DPIA/audit requirements | Do not self-claim designation or exemptions |
| Cross-border/sector rules | Counsel reviews government orders, hosting terms, Aadhaar law, banking/telecom and state records rules independently | DPDP is not a complete data-access licence |

Pension scheme appeals differ from privacy grievances. A 30-day demo appeal window is not established as a legal rule for every scheme. Do not deny late claims automatically; route exceptions and offline assistance to an authorised officer. A reinstatement request does not prove pension payment or arrears disbursal.

## CERT-In readiness

Directions under IT Act section 70B dated 28 April 2022 cover relevant service providers, intermediaries, data centres, bodies corporate and government organisations. They require clock synchronisation to NIC/NPL or traceable/accurate sources, designated contact, reporting covered incidents within six hours of noticing/being informed, and secure rolling 180-day ICT logs maintained within Indian jurisdiction. The FAQ explains partial initial reports can be followed by more information, and discusses log-copy arrangements. Use an India-resident authoritative log store as the conservative operating control; obtain deployment-specific legal review.

Before pilot: assign CERT-In contact and deputy; retain reporting procedure and current official form; test UTC timestamps with timezone, clock drift alerts, incident triage, log access/recovery, chain checkpoint retention and an on-call six-hour drill. A hash chain is only one application evidence control, not compliance with all ICT logging.

## GIGW 3.0 / STQC readiness

Official GIGW sources state WCAG 2.1 Level AA and a safe-to-host clearance from recognised/empanelled audit routes. GIGW scope says these guidelines underpin STQC website quality certification. They do not let a developer award a certificate to itself. The STQC linked scheme page failed SSL retrieval during this review; do not claim its current scheme details were verified.

Evidence pack needed:
- Department-approved ownership, Web Information Manager, contact/grievance details, privacy/copyright/hyperlink/content-review policies and accessibility statement.
- Complete content inventory, language plan, no false government emblem/endorsement, reliable help and offline appeals.
- Keyboard-only and screen-reader tests, focus order/visibility, form labels/errors, semantic tables, reflow/zoom, contrast, mobile and accessible documents. Automated scans are insufficient.
- Independent application/infrastructure security audit, remediation and retest evidence, scope-matched safe-to-host clearance, TLS/proxy/WAF configuration evidence and incident/backup drill.
- Dated checklist mapped to each GIGW checkpoint, named owner, evidence link and unresolved exception. No 'compliant' badge until the appropriate assessment is complete.

## Release levels

1. Local synthetic development: no government claims, no real feeds. Unit tests are not certification.
2. Public synthetic demo: only after combined application security sign-off, anonymous-data review, actual browser verification and immutable data-write guard tests. No adverse pension/payment execution.
3. Department shadow pilot: signed agreements, legal purpose, isolated hosting, real SSO/roles, jurisdiction scope, encryption, independent audit, representative validation and incident/restore proof. Observe only; keep official benefits unaffected.
4. Operational workflow: separate department authority and signed change control, human approval, notice/appeal/reinstatement/payment-reconciliation proof, external clearance and monitored rollback. Nothing in this repository authorizes this step.
