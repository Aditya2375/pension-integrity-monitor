# Threat model and deployment boundary

Reviewed base: 972d2b3. Date: 2026-11-04. This is a review-priority prototype, not a pension payment or death-certification authority. Security controls are supporting code until integrated and tested at the portal boundary.

## Assets and trust boundaries

- Personal identifiers, pension records, bank/telecom signals, family contacts and appeals. None belong in public demos, screenshots, logs, source history or hosted previews.
- Immutable department source snapshots, integrity manifests and authorization records enter through a quarantined intake boundary. Schema validity is not proof of provenance or legal access.
- Detector derives candidates in an isolated read-only workspace. Ranked outputs cross to the review database, never back into source records or a payment API.
- A department identity provider authenticates named officers; server-owned roles and jurisdiction assignments govern every object lookup, export and mutation. A shared demo key cannot provide accountability or tenancy isolation.
- Review decisions, appeals and reinstatement requests are separate from payment-system execution. Human approval must not masquerade as authority to stop a benefit.
- Signed/checksummed software and private model artifacts enter through separate supply-chain gates. Never deserialize untrusted pickle/joblib artifacts.
- TLS edge, application, database, job runner, backup store, audit anchor and administrator are distinct trust boundaries. Hash chaining does not protect against a database administrator unless checkpoints are retained independently.

## Abuse cases and controls

| Threat | Required prevention/detection | Proof needed |
| --- | --- | --- |
| Cross-site officer mutation or login CSRF | Session-bound token on every unsafe method, no state-changing GET, no cross-origin exemptions | Route-level negative and positive tests, every form inspected |
| Stolen/shared officer access | Department SSO/MFA, session revocation, short idle timeout, distinct reviewer/approver, access recertification | IdP claims tests and actor attribution for each action |
| Cross-state case/export leakage | Deny-by-default jurisdiction-scoped query, not UI filtering | Two-jurisdiction object-ID and export tests |
| Forged death feed or swapped snapshot | Feed owner signature, manifest hash, immutable storage, intake quarantine, freshness/coverage checks | Changed byte, wrong issuer, replay and partial-file tests |
| Repeated upload changes evidence | Idempotency key per immutable feed version; reject conflicting replay; transaction staging | Identical replay no-op and conflicting replay fail |
| Missing/stale feeds turn living people into flags | Explicit missingness, no silence-as-death conclusion, evidence sufficiency and review-only output | Missing-feed challenge set; per-region false-positive audit |
| Tampered decision/appeal evidence | Append-only audit with named actor, case reference, revision and external checkpoint | Rewrite, deletion, truncation, backup-restore tests |
| Public appeal token guessed or leaked | High-entropy bearer token, uniform errors, shared limits, minimal response, no-store, no token in logs/URL | Token entropy check, enumeration and cache tests |
| CSV/HTML injection | Autoescaped templates, formula-neutralized export text, validated lengths/types/finite numbers/dates | Malicious fixture tests and rendered review |
| Resource exhaustion | Proxy body/time limits, field/row limits, bounded job queue, disk quota, atomic intake staging | Oversized field, disk-full, timeout and worker-concurrency tests |
| Inappropriate official appearance | Synthetic-demo label; no government emblem, claimed endorsement or certification | Public-page review |
| Supply chain compromise | Complete hash lock, offline wheelhouse, SBOM, dependency scan, private artifact allowlist | Fresh environment install and hash-mismatch rejection |

## Residual risks that code alone cannot close

Department data authority, lawful linkage, Aadhaar-specific obligations, bank/telecom secrecy, hosting approval, trained review staff, notice delivery, offline appeals, payment-system reinstatement and a qualified independent audit. A model may systematically disadvantage populations with transliteration, inaccurate ages or sparse digital activity. National coverage and shard equivalence remain unproven. Do not pool Jeevan Pramaan across unrelated authorities.
