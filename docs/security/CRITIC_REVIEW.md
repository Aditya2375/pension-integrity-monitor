# Independent adversarial review

Base inspected: 972d2b3 (includes published 009a1a5). Date: 2026-11-04.
Verdict: **NO production sign-off. No public demo sign-off until integrated fixes are re-tested.** Tests at base: 6 passed. They do not exercise the attacks below.

| Severity | Finding from source inspection | Release condition |
| --- | --- | --- |
| Critical real-data | Shared officer session grants all data/actions, no jurisdiction query scope or individual attribution | Verified IdP roles and two-jurisdiction tests before real data |
| High | No CSRF tokens on mutations, GET logout | CSRF every unsafe method and integrated negative tests |
| High | Every hold/release/outcome edits pension_master.pension_status, violating source immutability | Derived review state only; no payment-write authority |
| High | Hold check permits zero verification rows; no state transition or second-officer guard | Exact required verification set and allowed states, atomic approval |
| High | Appeal resolution RELEASED changes appeal only; release is separate; displayed arrears are a rough estimate, not a payment | Atomic review reinstatement request; honest estimated-payment wording |
| High | Client-supplied X-Forwarded-For bypasses worker-local throttle; memory grows with unique keys | Trusted proxy parse, shared bounded limiter and external edge limits |
| High real-data | SQLite audit is mutable, uses generic actor, includes free-text note fragments and appeal bearer tokens | No bearer/personal payload logging, named actors, external audit anchors |
| High | Ingest commits each 5,000 rows, so later parse failure does not roll back file; source rows upsert; no replay protection | Staged immutable snapshots with manifest and idempotency |
| Medium | Settings accept arbitrary strings, unguarded float conversion and nonfinite values despite prior review claiming guarded parsing | Atomic validated settings tests |
| Medium | Public appeals reveal data using ~41-bit bearer tracking IDs and may allow new appeal against another appeal record beyond notice-window logic | Strong tokens, independent subject verification for disclosures, no hard-coded statutory deadline |
| Medium | pensioner_id exported unescaped can begin a spreadsheet formula; IDs are not guaranteed numeric | Formula-neutralized text exports |
| Medium | No no-store for case/appeal content, no independent job queue, 300 MB intake cap alone inadequate | Cache headers, bounded background processing and disk/field limits |
| Methodological | Display calls judgment-set outputs probabilities/calibrated; settings weights recorded with signals are not those actually used by hardcoded pipeline | Review-priority label, versioned evidence and honest calibration limits |
| Methodological | Selected resolved-queue sample used as population base rate; five outcomes is not validation | Freeze automatic recalibration pending representative held-out validation |
| Legal/readiness | No project licence, data-sharing authorization, retention implementation, DPIA or independent clearance | Owner-selected licence and department-owned gates |

## Static scan adjudication

Bandit on app.py, pim/, scripts/, security/: three B608 medium findings at pim/ingest.py (two) and scripts/export_flags.py (one). At this frozen base, dynamic identifiers come from internal whitelisted schemas; exported IN placeholders derive only from count, with values parameterized. Reviewed as non-exploitable in this scope, not a general SQL-injection guarantee. No blanket scanner suppression is added.

## Existing review corrections

`SECURITY_REVIEW.md` is historical, not a current release certificate. Its claims that rejected uploads roll back, settings conversion is guarded, identifiers cannot carry formulas, all audit logs lack personal payloads, and three direct pins equal a complete lock are not supported by the inspected code. A logged-out route test is not equivalent to per-record authorization. No live deployment, account security settings, secret scanning settings or previous public-data statements were independently verified in this review. Do not repeat them as current proof.

## Before final sign-off

Re-run all tests on combined frozen commit; inspect app/template diff; test CSRF, proxy spoofing, shared rate limits, all missing IDs, state transitions, immutable-feed digests, appeal/reinstatement atomicity, export injection and unsafe settings. Scan exact full dependency set including detector/native packages; inspect no personal artifacts in candidate git tree/history. Verify actual TLS/cache/headers and public synthetic-only UI pixels. Require independent penetration/accessibility testing for department hosting. Sign-off must state commit, deployment mode, exclusions, tests, findings, owner and expiry/review trigger.

## Detection branch follow-up: 2945905

Experimental v3/v4 loaders directly call pickle.load on CLI-supplied model/aggregate paths; code does not enforce the README's hash-verification statement. Keep frozen validation scripts isolated/trusted/offline during blind rounds. Production needs a separate constrained runner, independently provisioned digest allowlist and verified exact bytes before any deserialization, or a non-executable format. `security.artifacts.verified_bytes` supplies only read-once size/hash verification, not a safe pickle loader. Full numpy/pandas/model/native dependency lock/SBOM is still outside the root runtime inventory. Hardcoded /downloads import paths also prevent portable reproduction. None of this implies an observed compromise.
