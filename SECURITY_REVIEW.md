# Security review

Date: 2026-11-03. Scope: full application (Flask app, ingestion, pipeline, templates, dependencies, deployment config). Method: manual review of every route, query, template and config file, plus an automated dependency audit (pip-audit).

## Findings and fixes

1. Hardcoded default officer key (`officer`) in code and README. Fixed: no default exists; with `PIM_OFFICER_KEY` unset, officer sign-in renders "not configured" and all officer pages stay closed.
2. Hardcoded fallback session secret. Fixed: `PIM_SECRET` from the environment, else a random per-boot key (sessions invalidate on restart; no secret material in the repo).
3. Dashboard listed flagged pensioners by name without sign-in. Fixed: dashboard is officer-only.
4. Officer key compared with `==`, no rate limiting. Fixed: constant-time comparison (`secrets.compare_digest`) and a per-IP sliding-window throttle (5 failures / 15 min on sign-in, 20 posts / minute on the appeal portal). Session is cleared before it is established (fixation hygiene); `next` redirect target is restricted to local paths.
5. No security headers. Fixed: X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy no-referrer, a restrictive Content-Security-Policy, and HSTS on HTTPS.
6. Session cookies unhardened. Fixed: Secure (unless `PIM_INSECURE_HTTP=1` for local dev), HttpOnly, SameSite=Lax, 8-hour lifetime.
7. No upload size limit. Fixed: 300 MB cap (`MAX_CONTENT_LENGTH`); uploads stream to disk with constant memory; only `.csv` uploads accepted; feed IDs are whitelisted against the schema registry.
8. Unbounded text fields (appeal statement, contact, decision, tracking ID). Fixed: server-side length caps.
9. Development server in production config, unpinned dependencies. Fixed: pinned flask 3.1.3, werkzeug 3.1.9, gunicorn 23.0.0; gunicorn start command in render.yaml.
10. Unsafe temp-file creation and settings float parsing crash. Fixed: `mkstemp` and guarded parsing.

## Verified clean

- All SQL is parameterized; the only string-formatted SQL uses internal schema constants, never request input.
- Templates use Jinja autoescaping throughout; no `|safe`, no `Markup`.
- No secrets, tokens, databases or caches tracked in git (`.gitignore` covers `pim.sqlite3`, `__pycache__`, `.pytest_cache`).
- Appeal tracking IDs are 8 random characters from `secrets`; the appeal window is enforced server-side; a hold requires written reasons and completed verification steps.
- Dependency audit: `pip-audit -r requirements.txt` reports "No known vulnerabilities found" (2026-11-03).
- Test suite: 2 passed after all fixes.

## Known limits

- The login throttle is in-memory per process; with multiple gunicorn workers the effective limit multiplies by the worker count. A shared store can replace it when the deployment grows.
- Exported CSVs open in spreadsheet software; values are numeric IDs and scores, and free-text fields are not exported.

## Pre-ship checklist cross-check (2026-11-03, 45-item list)

Routine: diff read line by line (1 done). gitleaks detect --source . : no leaks across all 4 commits (2 done). pip-audit: no known vulnerabilities (3 done). bandit static scan: findings triaged below (4 done). Logged-out test of every route: automated, tests/test_auth.py, all 18 protected routes redirect to sign-in, public pages stay open, officer login fails closed with no key configured, throttle trips after 5 failures (5 done). MDN Observatory on the live URL (6 done; result noted in delivery report). Pushed after all of the above (7 done).

Secrets and keys: 1 no secret in code or git history: gitleaks clean over full history; GitHub secret scanning and push protection enabled via API. 2 public-by-design keys: none exist; no client JavaScript bundle at all. 3 .gitignore covers .env*, *.sqlite3, keystores, caches; present since first commit. 4 nothing ever leaked, so nothing to rotate; runtime secrets (PIM_OFFICER_KEY, PIM_SECRET) are vault-generated and live only in Render env settings.

Access control and data: 5 table-level access rules: single-user SQLite behind officer-only routes; equivalent check is the logged-out route test (all protected routes fail closed). 6 storage: the database file is never served; it is outside the web root and git-ignored. 7 server-side authorization on every protected route, verified by test_auth.py, including ID-changing attempts (case and appeal routes are officer-only regardless of ID). 8 collect less: person-level feeds stay empty until an officer uploads; appeal form stores only statement and optional contact.

Injection and input: 9 no innerHTML/eval/dangerouslySetInnerHTML anywhere (grep clean); Jinja autoescapes all rendered values. 10 parameterized queries throughout; bandit B608 hits reviewed: all placeholders or internal schema constants; no shell=True, os.system, eval, exec, pickle, yaml.load. 11 no URL or path fetching from user input; uploads are .csv-only, whitelisted feed IDs, streamed, schema-validated.

Dependencies: 12 all three dependencies (flask, werkzeug, gunicorn) are long-established packages, pinned by exact version. 13 lockfile equivalent: requirements.txt fully pinned; pip-audit clean; Dependabot alerts and security updates enabled. 14 no AI config files in the repo. 15 no production data exists to protect; the deployment starts empty.

Config, transport, accounts: 16 HTTPS only: http:// redirects 301 to https:// (verified on live). 17 security headers verified on live: CSP, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, HSTS. 18 debug off; production runs gunicorn, not the Werkzeug dev server; no source maps (no JS build). 19 officer access is a single vault-generated 24-character key, constant-time compared, throttled, never stored in code or history; there is no homemade password database. 20 rate limits: per-IP sliding-window throttle on sign-in and appeal posts; all other mutating routes sit behind officer auth. 21 fail closed: no officer key configured means no officer access; rejected uploads fail the transaction; audit log records actions without secrets. 22 two-factor on the user's own accounts is the user's call, per the checklist.

Static hosting items 23-28: 23 the repo is public and contains no personal data (grep for phone/email/name clean; author name appears only in git metadata as required). 24 no client-side login or hidden admin pages; all auth is server-side. 25 no browser bundle, so no env leakage into one. 26 no third-party scripts or fonts; everything self-hosted (verified by grep of templates). 27 the only public form (appeal portal) is throttled and writes only to the database; no email relay. 28 old deployments: none abandoned; this is the first deployment.

Android items 29-39: not applicable; this project has no APK, relay, or update channel.

Python tool items 40-45: 40 credentials from env only (PIM_OFFICER_KEY, PIM_SECRET, PIM_DB); gitleaks clean. 41 the monitor logs in to nothing external; it only receives uploads. 42 logs: the audit table records actions, no personal payloads; uploaded CSVs are not logged; grep for personal data in repo and logs clean. 43 parsing: csv module only, no yaml/pickle, no outbound HTTP. 44 no GitHub Actions in this repo. 45 no alert channels.

Bandit triage detail: B104 binding (fixed: localhost default, env override); B101 in pim/feedback.py (fixed: real ValueError); B101 in tests (fine); B306 mktemp in tests only (fine); B608 x3 (reviewed: parameter placeholders and internal constants only).

## Addendum 2026-11-05: officer-gaming and integrity safeguards

- Audit log is now hash-chained (each entry commits to the previous entry's SHA-256). The dashboard replays the chain on every load and shows TAMPER DETECTED with the first broken entry if history is edited or deleted. Limit: it detects, not prevents, tampering by someone with database write access; shipping the log to an external store is the stronger control and is not built.
- Holds are dual-control: the requesting officer's hold only pends the case; approval requires a different officer name signed in. Officer name is self-declared at sign-in (single shared officer key); this is process dual control, not strong per-officer identity. Real per-officer accounts are the known follow-up.
- Hold reasons must be at least 40 characters and are rejected if identical to reasons on any other case or pending request (boilerplate guard).
- Queue-flooding circuit breaker: one run creating more than `max_new_cases_per_run` new cases halts further case creation, logs a loud `circuit_breaker` audit entry, and surfaces a warning. Nothing is ever auto-held.
- Randomized audit sampling (`audit_sample_rate`) puts a small random share of unflagged still-paid pensioners into the queue as labelled audit-sample cases; their outcomes are the unbiased stream that estimates what flags miss.
- Appeals open past `appeal_response_sla_days` are marked overdue on the appeals page.
- Test suite extended: tamper detection, breaker, audit sampling, overdue marker, dual control, boilerplate rejection (tests/test_safeguards.py, tests/test_flow.py). All tests pass.

## Addendum 2026-11-05 (2): hostile-review round 2 fixes

Two external hostile reviews of the first safeguards round found the same core weaknesses. What was fixed in code, and what stays a documented limit:

Fixed in code:
- Audit log UPDATE/DELETE is now blocked by database triggers, not just detected after the fact. If the triggers are dropped and history rewritten, the hash chain still detects it (tested both ways).
- Hold approval now binds to a hash of the exact evidence snapshot (signals, verification state, score) the requesting officer saw; any change voids the request before approval.
- Boilerplate guard now catches near-duplicates (similarity >= 0.85), not only exact copies.
- A cumulative drip-flood watch warns when recent pipeline runs together exceed 3x the per-run cap, covering flooding that stays under the cap each run.

Still documented limits, honestly stated:
- Officer identity is self-declared at sign-in behind a single shared officer key. Dual control is process dual control; one motivated person can sign in twice under two names. Real per-officer accounts are the follow-up and are not built.
- The hash chain detects only tampering that does not recompute the whole chain. An attacker with full database write access who rewrites and re-chains the log defeats it; external hash shipping is the stronger control and is not built.
- Audit sampling at 0.1% has low statistical power on small rolls; the estimate of missed deaths is only meaningful as volume grows.
- The boilerplate guard checks text similarity, not whether the reasons are supported by the evidence.

## Addendum 2026-11-05 (3): per-officer identity and log anchoring

Built, responding to both hostile reviews naming these as the core walls:
- Real per-officer accounts: officers table with scrypt (n=2^14, r=8, p=1) salted password hashes; constant-time comparison; sign-in is username+password, no shared key at sign-in. First account ('admin') bootstraps from PIM_OFFICER_KEY only when the officers table is empty; with no key, no account exists and officer pages stay closed. Officers page adds (12+ char passwords) and deactivates accounts; self-deactivation is blocked; every add/deactivate/login is audited. Dual control now compares accounts, defeating the sign-in-twice-under-two-names attack.
- External log anchoring, free/local: every audit entry hash is dual-written with fsync to a separate anchor file (DB path + '.anchor'). Verification compares the database chain head to the anchor head; a database-only rewrite - even one that drops the triggers and recomputes the chain - is caught (tested). Documented limit: an attacker who rewrites both files defeats it; true external anchoring needs a second system, which is infrastructure, not code.
- Throttle unchanged (5 failures / 15 min per IP); passwords are never logged; audit rows record usernames, not credentials.

Scorer wall, stated straight: three further candidates (V16 multiregime risk-weighted, V17 consult-feature model, V18 gated-secondary retrain) were each frozen and tested under the freeze-then-score protocol and each failed to beat V15 at its precision. The measured miss mass is fresh unregistered deaths with no signal in any feed; the oracle catch-all tops at 92% recall at 6% precision. No remaining scorer lever exists that does not amount to inventing new synthetic signals, which would be overfitting the benchmark, not improving detection. V15 (99.13% precision / 88.81% recall, blind-verified) stays the frozen final.

## Threat model (2026-11-05, after three hostile review rounds)

What the system provides, in defensible words:
- Account-level attribution of every action, not verified human identity.
- Two-account approval for holds, not proven two-person approval. One person with two accounts defeats it; organizational process must keep accounts one-per-person.
- Local tamper evidence for the audit log (hash chain + append-only triggers + fsynced anchor file), not independent audit anchoring. Database-only rewrites are caught; rewriting both files defeats it.
- Detection of certain recorded-event modifications, not proof the log is complete: a code path that skips logging leaves no trace.
- Randomly sampled audit stream, whose estimates depend on adjudication quality and sample size.
- Benchmark performance on one specified synthetic benchmark (99.13% precision / 88.81% recall), not demonstrated deployment performance.
- Suspicion identification for human review, not autonomous fraud determination.

## Addendum 2026-11-05 (4): round-3 fixes

Built after the third hostile review:
- Session revocation: deactivation or password change bumps a per-account session_version; live sessions die on their next request (tested).
- Step-up re-authentication: hold approval and officer add/deactivate require re-entering the acting officer's password (tested).
- Forced password change at first sign-in for accounts created by another officer (tested).
- Crash-consistent anchor protocol: the anchor write happens before the database commit; verification reports an anchor exactly one entry ahead of an intact chain as INCOMPLETE (possible crash residue, manual review) and never silently reconciles; any other divergence is a break.
- Feed provenance: every upload's SHA-256 content hash, officer, row counts and time are written to the audit log as the file streams in.
- Tests added for all of the above, plus self-approval, stale-evidence approval, tamper, anchor-mismatch and session-revocation paths.

Known walls (need real infrastructure, stated plainly): verified human identity behind accounts, independent off-host log anchoring, hardware-backed credentials, and any scorer improvement past the measured signal ceiling.

## Addendum 2026-11-06: round-4 fixes

- Per-account login throttle (8 failures / 15 min) added alongside the per-IP throttle.
- Dashboard shows the count of appeals open past the response SLA.
- "Unbiased outcome stream" wording replaced with "randomly selected unflagged audit cohort"; estimates depend on adjudication, unresolved samples and sample size.
- Open, documented: rolling back database and anchor file together to an older consistent copy is undetected; crash recovery is reported (INCOMPLETE) but not chaos-tested at every write boundary; reason-quality checks are text similarity only.

## Addendum 2026-11-06 (2): round-4 local items built

- Rollback detection on one host: every audit hash is also written, fsynced, to a checkpoint file in a different directory (PIM_CHECKPOINT_DIR, default ~/.pim-checkpoints). Restoring an older database plus the local anchor is caught because the checkpoint is ahead (tested). Limit: someone who rewrites all three copies, or who can write the checkpoint directory, defeats it. Pointing it at a separately permissioned location raises the bar; true protection needs another system.
- Crash chaos test: the append is killed at each write boundary (before the first anchor, between anchor and checkpoint, after both anchors but before commit). No state is silently trusted: each shows as intact (nothing durable) or INCOMPLETE for manual review (tested).
- Hold requests must cite at least one evidence signal actually present on the case; the cited signals are stored and shown to the approving officer. This ties reasons to case evidence but does not prove they are correct.
- Completeness reconciliation: the dashboard flags any held case with no matching hold_approved audit entry.
