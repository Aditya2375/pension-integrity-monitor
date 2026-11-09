# Machine feed intake security acceptance criteria

Proposed API, not an implemented or certified mTLS gateway. Disabled unless the department provisions trust/configuration. No public self-registration or credentials in repository. Browser officer sessions are not machine credentials.

## Authentication and scope

Production ingress terminates TLS with department-controlled mTLS or approved equivalent machine identity. Verify issuer, signature, expiry and revocation; map certificate/service subject to allowed agency, feed kind, schema version and jurisdiction using trusted server config. Do not accept client-supplied identity/scope headers except from a known locked-down edge that strips and replaces them. Never trust arbitrary X-Forwarded-For or X-User. Demo bearer auth must use high-entropy credentials, constant-time comparison, rotation/revocation and TLS, and must not be described as production mTLS.

If manifests are signed, pin agency-specific signing keys and bind signature to canonical bytes containing body digest, agency, feed/schema version, source snapshot/sequence, request ID and timestamp. Reject unsupported algorithms, wrong audience, unknown key IDs, expired/revoked keys, stale/future timestamps and replay. A digest alone is integrity, not sender authenticity. Keep a persistent idempotency ledger: same key+same authenticated scope+same content yields same result, conflicting content yields 409. Rotate keys under signed change control, not caller-selected env names.

## Validation, staging and publication

Require exact allowed content types. Reject compression/archives by default. Enforce maximum bytes at proxy AND streaming application reader, maximum field/header/physical-row counts and lengths, encoding/delimiter/schema versions, date/numeric ranges and finite values. Constrain request duration, disk quota and outstanding jobs per service and globally. No source path/URL supplied by caller is fetched or opened. Generate internal filenames, reject alias/symlink escape, use restrictive file modes and a private directory.

Accept into durable quarantine only after authenticated scope and hash/provenance are recorded. Return 202 with opaque job ID if asynchronous. Never report success before durable acceptance; distinguish accepted, quarantined, validated, rejected and published. Validation failure publishes nothing. Immutable version directories/commit records require exclusive publication lock and directory fsync or a storage system with equivalent atomic semantics. Retrying a job cannot overwrite a prior publication or silently remove an in-progress orphan.

Promote only when schema, allowed fields, authority, per-record jurisdiction, freshness/coverage, expected completeness and signature checks pass. Strip/drop/tokenize protected fields under reviewed contracts, with stable authority-scoped identifier domains shared across legitimate feed types. No raw identifiers in generic columns, no shared sentinel as a join key, no invented money/status defaults. Preserve original source evidence separately and read-only. Detector cannot modify source snapshot or payment system.

## Abuse, observability and response

Shared per-service and per-IP limits, global concurrency/storage caps, bounded queues, clear 429/Retry-After and 413 responses. Network failures must not create duplicate jobs. Uniform non-personal errors; no parser row values, tokens or credentials in exceptions/responses/logs. Audit named machine subject, authenticated agency/feed, contract/version, source digest, request/job/idempotency references, row counts and state transitions. Anchor audit checkpoints independently, monitor rejection/rate-limit/publication anomalies and prove restore.

## Required tests

Missing/invalid/wrong-scope/revoked identity, forged forwarding headers, missing trust config, wrong signature/key/audience/body, replay and changed replay; oversize stream despite dishonest Content-Length, compression bomb refusal, long field, invalid UTF-8/date/nonfinite number, missing filters, extra positional column, alias/symlink, two concurrent publishers, failure between data and manifest commit, disk full, cancellation/retry; raw-sensitive mapping bypass, same ID across feed domains, different-authority unlinkability, key rotation and missing identifiers; audit failure prevents promotion, no private values in logs, endpoint/tenant isolation and job authorization. Independent review is required on the exact combined commit.
