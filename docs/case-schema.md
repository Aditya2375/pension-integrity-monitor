# Case schema (review queue and appeal portal)

Contract with the detection and integration lanes. The detector outputs ranked
`pensioner_id, score` plus review reasons. `score` is review priority only. It
is never authority to stop a pension.

## Inbound (from detection)
| field | type | notes |
|---|---|---|
| pensioner_id | text | key into the immutable source feed |
| score | real | review priority; never shown alone to officers |
| review_reasons | list of {code, text, source_feed} | plain-language, shown beside conflicting evidence |
| source_feed_refs | list of {feed_id, record_key} | pointers only, no copies of personal data |

Stored on `cases` as `probability`/`priority` (existing), `review_reasons` and
`source_feed_refs` (JSON text).

## Case states
FLAGGED, UNDER_REVIEW, VERIFICATION, HOLD_PROPOSED, DEATH_PROPOSED, NOTICE,
HELD, APPEAL_REVIEW, RELEASED, DISMISSED, SURVIVOR_ROUTING, CLOSED_CONFIRMED.
`cases.case_kind` is `hold` or `death`. Both kinds pass through NOTICE.
The transition table is `pim/workflow.py: TRANSITIONS`; anything else raises.

## Outbound (to payment systems and integration adapters)
`cases.payment_status` is the only payment recommendation. The source feed
(`pension_master.pension_status`) is never written.
| payment_status | meaning |
|---|---|
| ACTIVE | pay normally (default; also after release) |
| PROVISIONALLY_RESTORED | appeal filed, pay while a second supervisor reviews |
| SUSPENDED | notice period ran (or supervisor override), payment held |
| STOP_DECEASED | death finalised after notice and appeal period with no appeal, or after an independent appeal review upheld it; route to survivor/family pension. Can be reopened. |

Other case fields: `case_kind`, `appeal_deadline_at`, `reopened_by`, `proposed_by`, `approved_by`, `notice_issued_at`,
`notice_due_at`, `suspended_at`, `restored_at`, `arrears`, `state_changed_at`.

## Related tables
`decisions` (proposal and approval, two different users), `case_notes`,
`survivor_steps`, `appeal_evidence`, `users`, and `audit_chain` (append-only,
SHA-256 hash chain, `audit.verify()` reports the first bad row).

## Roles
officer (proposes), supervisor (approves, decides appeals; must not have
taken part in the original decision), auditor (read-only), admin, family
(appellant, tracking ID plus OTP only).

## Rules
1. Hold needs written reasons and at least one verification step, all done.
2. Approver is a different user from the proposer.
3. Approved hold starts a notice period (setting `notice_period_days`, default 30). Payment continues until it ends, unless a supervisor records a reason to override.
4. An appeal restores payment at once; arrears for any suspended period are recorded.
5. Appeal reviewer took no part in the original proposal or approval.
6. Every change writes an audit entry in the same transaction.
