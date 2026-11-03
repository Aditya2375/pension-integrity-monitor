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
