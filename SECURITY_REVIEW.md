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
