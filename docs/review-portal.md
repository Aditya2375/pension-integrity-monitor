# Review queue and family appeal portal

## Configuration (environment)
| variable | purpose |
|---|---|
| PIM_OFFICER_KEY | Legacy single deployment key. If no named account exists, it becomes the first admin account (username `admin`) once. |
| PIM_USERS | `name:role:JUR1\|JUR2:key;...` first-run users (roles: officer, supervisor, auditor, admin). Stored as scrypt hashes. Stand-in for the department identity system. |
| PIM_SECRET | session signing key, also the key for one-time-code hashes (required in any real deployment) |
| PIM_TRUSTED_PROXIES | comma-separated CIDRs of your reverse proxy. Empty means the socket address is used and X-Forwarded-For is ignored. |
| PIM_CLIENT_IP_HEADER | name of a header the edge sets itself, such as `CF-Connecting-IP` behind Render's Cloudflare. Used only when the socket peer is inside `PIM_TRUSTED_PROXIES`; otherwise ignored. |
| PIM_IDLE_SECONDS | staff session idle timeout in seconds (default 1800) |
| PIM_LIMITER_DB | path for the shared rate-limit store (local disk, not a network share) |
| PIM_EVIDENCE_DIR | where appeal evidence files are kept (restricted directory) |
| PIM_EVIDENCE_ENABLED | `1` turns on appeal document upload. Off by default. |
| PIM_DEMO_SHOW_OTP | `1` shows the one-time code on screen. Synthetic demo only. Unset in any real deployment. |
| PIM_INSECURE_HTTP | `1` for local plain-HTTP development only |

## Who can do what
- officer: verify steps, notes, propose hold or death confirmation, dismiss, survivor-routing steps.
- supervisor: approve or send back, suspend after notice, release, decide appeals (never one who took part in the original decision).
- auditor: read only. admin: ingestion, pipeline, settings.
- Every case read is limited to the user's jurisdictions (the pensioner's state). Out of scope reads as not found.

## Flow
Flag -> review and verify (exactly the four pipeline checks, each once) -> officer proposes -> a different supervisor approves -> notice to the family. The notice sets a fixed appeal deadline (setting `appeal_window_days`, copied onto the case at issue, so later setting changes cannot move it). Payment continues during the notice.

Hold: after the notice period a supervisor may recommend suspension (earlier only with a written reason).
Death confirmation: never final on first approval. It goes through the same notice. It can be finalised only after the whole notice and appeal period has ended with no appeal, with no override, by a supervisor other than the proposer. After finalising, a supervisor who took no part in the original decision can reopen it at any time with a written reason. Payment is then requested back provisionally and a third supervisor decides.

Appeal: the family portal accepts it until the deadline and refuses after it. The window length is a configurable demo policy and is not taken from any scheme rule. After the deadline a supervisor who took no part in the decision can still take a late appeal into review with a fixed reason code (notice not received, illness, address change, new evidence, other) and a written note. It restores payment provisionally and a different supervisor decides it. A missing deadline is treated as closed. It restores payment provisionally at once. A supervisor who was not the proposer, approver or reopener decides it. If it is accepted, a full reinstatement request is recorded.

Every edge in the state machine can only be taken by its named workflow action (`EDGE_ACTIONS`), so no route can bypass a rule.
Outputs to the payment system: `cases.payment_status` and `reinstatement_requests`. This system records requests. It does not move money, and the pension feed tables are never written.

## Family portal
Reference from the notice, then a one-time code through the notification outbox (stored as a keyed HMAC hash, 10 minutes, 5 tries, redeemed atomically so one code works once). A correct code gives a server-side grant that lasts 30 minutes and is used up when an appeal is filed or the person signs out. No account.
Nothing is sent unless a message service is connected (`app.config["NOTIFY_ADAPTER"]`). Until then every screen says messages are queued only.
English and Hindi catalogues in `pim/i18n.py`. The Hindi text is a working draft needing native review.

## Appeal documents
Off by default. When enabled: a PDF, JPG or PNG up to 5 MB goes through a structural check only (PNG chunk CRCs and size caps, JPEG marker walk, PDF header, xref, matched objects, and refusal of scripts and similar features). This is a sanity check, not a malware scan, and it can be fooled. Files are kept in a private quarantine directory (0700 dir, 0600 files, random names). Staff cannot download a file until a supervisor releases it after opening it in an isolated viewer and ticking the attestation. Downloads re-check the file location and SHA-256, are sent as opaque attachments, and are audited. If filing fails, the written file is deleted.

## Notifications
`pim/notify.py` writes an outbox row in the same transaction as the state change. The integration lane supplies a `notify.Adapter` (SMS, email, post) that looks up the contact itself. The outbox holds template code, case id and non-personal parameters only. Failed sends retry up to 5 times and then show as FAILED.

## Not done yet
Visual design pass (waiting for references), screen-reader and keyboard audit on the final design, more languages, a supervisor dashboard for SLA overdue counts, production identity provider adapter, external audit checkpoint export job.

## Concurrency
Every workflow action takes the database write lock (`BEGIN IMMEDIATE`) before it reads the case, so two people cannot act on the same state. A unique index allows one pending decision per case. The account is re-checked inside the transaction, so a user revoked or re-roled mid-request cannot complete the action. Tests race proposals, approvals, rejections, appeals, finalise, late intake, reopen and revocation. SQLite is single-writer; a production database would use row locks or version checks with the same unique index.
