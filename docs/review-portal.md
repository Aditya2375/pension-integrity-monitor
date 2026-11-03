# Review queue and family appeal portal

## Configuration (environment)
| variable | purpose |
|---|---|
| PIM_USERS | `name:role:JUR1\|JUR2:key;...` first-run users (roles: officer, supervisor, auditor, admin). Stored as scrypt hashes. Stand-in for the department identity system. |
| PIM_SECRET | session signing key (required in any real deployment) |
| PIM_TRUSTED_PROXIES | comma-separated CIDRs of your reverse proxy. Empty means the socket address is used and X-Forwarded-For is ignored. |
| PIM_LIMITER_DB | path for the shared rate-limit store (local disk, not a network share) |
| PIM_EVIDENCE_DIR | where appeal evidence files are kept (restricted directory) |
| PIM_DEMO_SHOW_OTP | `1` shows the one-time code on screen. Synthetic demo only. Unset in any real deployment. |
| PIM_INSECURE_HTTP | `1` for local plain-HTTP development only |

## Who can do what
- officer: verify steps, notes, propose hold or death confirmation, dismiss, survivor-routing steps.
- supervisor: approve or send back, suspend after notice, release, decide appeals (never one who took part in the original decision).
- auditor: read only. admin: ingestion, pipeline, settings.
- Every case read is limited to the user's jurisdictions (the pensioner's state). Out of scope reads as not found.

## Flow
Flag -> review and verify -> officer proposes -> different supervisor approves -> notice to family (payment continues for `notice_period_days`) -> supervisor may recommend suspension after the period (or earlier with a written reason) -> family can appeal at any time in the window and payment is restored provisionally -> a different supervisor decides.
Outputs to the payment system: `cases.payment_status` and `reinstatement_requests`. This system records requests. It does not move money, and the pension feed tables are never written.

## Family portal
Reference from the notice, then a one-time code through the notification outbox (hashed, 10 minutes, 5 tries). No account. Appeal text plus one optional PDF, JPG or PNG (checked by content, 5 MB, stored under a random name, downloadable by staff only). English and Hindi catalogues in `pim/i18n.py`; Hindi text is a working draft needing native review.

## Notifications
`pim/notify.py` writes an outbox row in the same transaction as the state change. The integration lane supplies a `notify.Adapter` (SMS, email, post) that looks up the contact itself. The outbox holds template code, case id and non-personal parameters only. Failed sends retry up to 5 times and then show as FAILED.

## Not done yet
Visual design pass (waiting for references), screen-reader and keyboard audit on the final design, more languages, a supervisor dashboard for SLA overdue counts, production identity provider adapter, external audit checkpoint export job.
README.md, render.yaml and SECURITY_REVIEW.md still describe the old single officer key and need updating by the docs owner.
