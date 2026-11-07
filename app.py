import os, secrets, string, threading, time
from datetime import datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, abort, Response)
from pim import db, ingest, pipeline, feedback, health, scoring

app = Flask(__name__)
# Session signing key: from the environment in every real deployment. When it
# is absent (local demo), fall back to a per-boot random key (existing sessions
# invalidate on restart) instead of shipping a hardcoded secret.
app.secret_key = os.environ.get("PIM_SECRET") or secrets.token_hex(32)
# Officer key: no default. If it is not configured, officer sign-in stays closed.
OFFICER_KEY = os.environ.get("PIM_OFFICER_KEY")
app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get("PIM_INSECURE_HTTP") != "1",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=300 * 1024 * 1024,  # feed uploads stream; this caps disk abuse
)

_LOCK = threading.Lock()
_ATTEMPTS = {}  # ip -> list of failure timestamps (sliding window)

def _throttled(ip, limit, window_s):
    now = time.time()
    with _LOCK:
        arr = [t for t in _ATTEMPTS.get(ip, []) if now - t < window_s]
        if arr:
            _ATTEMPTS[ip] = arr
        else:
            _ATTEMPTS.pop(ip, None)
        return len(arr) >= limit

def _record_fail(ip):
    with _LOCK:
        if len(_ATTEMPTS) > 50000:  # bound memory: drop keys idle for over an hour
            now = time.time()
            for k in [k for k, v in _ATTEMPTS.items() if not v or now - v[-1] > 3600]:
                _ATTEMPTS.pop(k, None)
        _ATTEMPTS.setdefault(ip, []).append(time.time())

@app.before_request
def csrf_guard():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, "Invalid form token. Reload the page and try again.")

@app.context_processor
def csrf_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    if request.scheme == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

with app.app_context():
    db.init_db()

def conn():
    return db.connect()

def officer_required():
    if not session.get("officer"):
        return redirect(url_for("login", next=request.path))
    # session revocation: deactivation or a password change bumps
    # session_version, killing every live session for that account.
    c = conn()
    row = c.execute("SELECT session_version, active, must_change FROM officers WHERE username=?",
                    (session.get("officer_name"),)).fetchone()
    c.close()
    if (not row or not row["active"]
            or row["session_version"] != session.get("session_version", -1)):
        session.clear()
        return redirect(url_for("login", next=request.path))
    if row["must_change"] and request.endpoint not in ("change_password", "logout", "static"):
        return redirect(url_for("change_password"))
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    c = conn()
    has_officers = c.execute("SELECT COUNT(*) n FROM officers").fetchone()["n"] > 0
    c.close()
    if not has_officers:
        return render_template("login.html", err="No officer account exists on this deployment. Set PIM_OFFICER_KEY before first start to bootstrap the admin account.")
    if request.method == "POST":
        ip = (request.access_route[0] if os.environ.get("PIM_TRUST_PROXY") == "1" else request.remote_addr) or "?"
        username = (request.form.get("username") or "").strip()[:40]
        if _throttled(ip, 5, 900) or _throttled("acct:" + username.lower(), 8, 900):
            err = "Too many attempts. Try again in 15 minutes."
        else:
            c = conn()
            ok = db.check_officer(c, username, request.form.get("key") or "")
            c.close()
            if ok:
                session.clear()
                session["officer"] = True
                session["officer_name"] = username
                c2 = conn()
                row = c2.execute("SELECT session_version FROM officers WHERE username=?", (username,)).fetchone()
                c2.close()
                session["session_version"] = row["session_version"]
                session.permanent = True
                c = conn()
                db.log(c, username, "login", "officer sign-in")
                c.commit()
                c.close()
                nxt = request.args.get("next") or ""
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = ""
                return redirect(nxt or url_for("dashboard"))
            _record_fail(ip)
            _record_fail("acct:" + username.lower())
            err = "Wrong username or password."
    return render_template("login.html", err=err)

def admin_required():
    r = officer_required()
    if r: return r
    c = conn()
    row = c.execute("SELECT role FROM officers WHERE username=?", (session.get("officer_name"),)).fetchone()
    c.close()
    if not row or row["role"] != "admin":
        abort(403)
    return None

@app.route("/officers")
def officers_page():
    r = admin_required()
    if r: return r
    c = conn()
    rows = c.execute("SELECT id,username,active,created_at FROM officers ORDER BY username").fetchall()
    c.close()
    return render_template("officers.html", rows=rows, me=session.get("officer_name"))

@app.route("/officers/add", methods=["POST"])
def officer_add():
    r = admin_required()
    if r: return r
    username = (request.form.get("username") or "").strip()[:40]
    pw = request.form.get("password") or ""
    me = session.get("officer_name", "officer")
    if not _fresh_auth(me, request.form.get("admin_password")):
        return redirect(url_for("officers_page", err="Re-enter your own password to add an officer."))
    if not username or len(pw) < 12:
        return redirect(url_for("officers_page", err="Username required; password must be at least 12 characters."))
    c = conn()
    exists = c.execute("SELECT 1 FROM officers WHERE username=?", (username,)).fetchone()
    if exists:
        c.close()
        return redirect(url_for("officers_page", err="That username already exists."))
    db.create_officer(c, username, pw)
    db.log(c, me, "officer_add", f"created officer account '{username}'")
    c.commit()
    c.close()
    return redirect(url_for("officers_page", msg=f"Officer '{username}' created."))

@app.route("/officers/<int:oid>/deactivate", methods=["POST"])
def officer_deactivate(oid):
    r = admin_required()
    if r: return r
    me = session.get("officer_name", "officer")
    if not _fresh_auth(me, request.form.get("admin_password")):
        return redirect(url_for("officers_page", err="Re-enter your own password to deactivate an officer."))
    c = conn()
    row = c.execute("SELECT username FROM officers WHERE id=?", (oid,)).fetchone()
    if row and row["username"] != me:
        c.execute("UPDATE officers SET active=0, session_version=session_version+1 WHERE id=?", (oid,))
        db.log(c, me, "officer_deactivate", f"deactivated '{row['username']}'")
        c.commit()
    c.close()
    return redirect(url_for("officers_page"))

def _fresh_auth(username, password):
    """Step-up: sensitive actions require the officer's current password again."""
    key = "stepup:" + (username or "").lower()
    if _throttled(key, 8, 900):
        return False
    c = conn()
    ok = db.check_officer(c, username, password or "")
    c.close()
    if not ok: _record_fail(key)
    return ok

@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    r = officer_required()
    if r: return r
    err = None
    if request.method == "POST":
        old_pw = request.form.get("old") or ""
        new_pw = request.form.get("new") or ""
        me = session.get("officer_name")
        if len(new_pw) < 12:
            err = "New password must be at least 12 characters."
        elif not _fresh_auth(me, old_pw):
            err = "Current password is wrong."
        else:
            import secrets as _s
            c = conn()
            salt = _s.token_hex(16)
            c.execute("UPDATE officers SET password_hash=?, salt=?, must_change=0, "
                      "session_version=session_version+1 WHERE username=?",
                      (db.hash_password(new_pw, salt), salt, me))
            db.log(c, me, "password_change", "officer changed own password")
            c.commit()
            row = c.execute("SELECT session_version FROM officers WHERE username=?", (me,)).fetchone()
            c.close()
            session["session_version"] = row["session_version"]
            return redirect(url_for("dashboard", msg="Password changed."))
    return render_template("change_password.html", err=err)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard"))

@app.route("/")
def dashboard():
    r = officer_required()
    if r: return r
    c = conn()
    counts = {r["state"]: r["n"] for r in
              c.execute("SELECT state, COUNT(*) n FROM cases GROUP BY state")}
    top = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme FROM cases "
        "JOIN pension_master USING(pensioner_id) WHERE cases.state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION','HOLD_PENDING') "
        "ORDER BY probability DESC LIMIT 10").fetchall()
    fh = health.feed_health(c)
    stats = feedback.stats(c)
    audit_ok, audit_bad, audit_n = db.verify_audit(c)
    recon = db.reconcile(c)
    sla = int(db.get_setting(c, "appeal_response_sla_days") or 14)
    overdue = sum(1 for a in c.execute("SELECT submitted_at FROM appeals WHERE status='OPEN'")
                  if a["submitted_at"] and (datetime.utcnow().date() - datetime.fromisoformat(a["submitted_at"].replace("Z","")).date()).days > sla)
    c.close()
    return render_template("dashboard.html", counts=counts, top=top, feeds=fh, stats=stats,
                           audit_ok=audit_ok, audit_bad=audit_bad, audit_n=audit_n, overdue=overdue, recon=recon)

@app.route("/ingest", methods=["GET"])
def ingest_page():
    r = officer_required()
    if r: return r
    c = conn()
    fh = health.feed_health(c)
    schemas = ingest.FEED_SCHEMAS
    c.close()
    return render_template("ingest.html", feeds=fh, schemas=schemas)

@app.route("/ingest/<feed_id>", methods=["POST"])
def ingest_upload(feed_id):
    r = officer_required()
    if r: return r
    if feed_id not in ingest.FEED_SCHEMAS:
        abort(404)
    f = request.files.get("file")
    if not f or not (f.filename or "").lower().endswith(".csv"):
        return redirect(url_for("ingest_page", msg="Upload a .csv file."))
    # Hash original bytes, not decoded/re-encoded text. Stage to a bounded
    # temporary file so parsing and the provenance digest refer to identical input.
    import hashlib, tempfile, io
    digest = hashlib.sha256()
    c = conn()
    try:
        with tempfile.TemporaryFile() as staged:
            while True:
                chunk = f.stream.read(65536)
                if not chunk: break
                digest.update(chunk)
                staged.write(chunk)
            staged.seek(0)
            loaded, rejected = ingest.ingest_csv_stream(c, feed_id, ingest.iter_text(staged))
        db.log(c, session.get("officer_name", "officer"), "feed_provenance",
               f"feed={feed_id} sha256={digest.hexdigest()} loaded={loaded} rejected={rejected}")
        c.commit()
        msg = f"Loaded {loaded} rows, rejected {rejected}."
    except (ValueError, UnicodeError) as e:
        c.rollback()
        msg = "Rejected file: " + str(e)
    c.close()
    return redirect(url_for("ingest_page", msg=msg))

@app.route("/templates/<feed_id>.csv")
def template(feed_id):
    if feed_id not in ingest.FEED_SCHEMAS:
        abort(404)
    return Response(ingest.template_csv(feed_id), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={feed_id}_template.csv"})

@app.route("/pipeline/run", methods=["POST"])
def run_pipeline():
    r = officer_required()
    if r: return r
    c = conn()
    made, p_star, breaker, watch = pipeline.run_pipeline(c)
    c.commit()
    c.close()
    msg = f"Pipeline complete: {made} new cases. Priority threshold p*={p_star:.2f}."
    if breaker:
        msg = (f"CIRCUIT BREAKER TRIPPED: case creation stopped at {made} after the run produced "
               f"more new cases than the configured cap (max_new_cases_per_run). "
               "Investigate feed integrity before rerunning. No pensions were held automatically.")
    elif watch:
        msg += (" FLOOD WATCH: cumulative new-case volume over recent runs exceeds 3x the per-run cap; "
                "a feed may be drip-flooding cases under the cap. Investigate feed integrity.")
    return redirect(url_for("queue", msg=msg))

@app.route("/queue")
def queue():
    r = officer_required()
    if r: return r
    c = conn()
    rows = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme, pension_master.monthly_amount, "
        "(SELECT COUNT(*) FROM signals s WHERE s.case_id=cases.id AND s.signal='audit_sample') AS audit FROM cases "
        "JOIN pension_master USING(pensioner_id) "
        "WHERE cases.state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION','HOLD_PENDING') "
        "ORDER BY CASE WHEN julianday('now')-julianday(created_at) >= 14 THEN 1 ELSE 0 END DESC, "
        "CASE WHEN julianday('now')-julianday(created_at) >= 14 THEN created_at END ASC, "
        "priority DESC, probability DESC").fetchall()
    p_star = scoring.cost_threshold(float(db.get_setting(c, "cost_false_hold")),
                                    float(db.get_setting(c, "cost_missed_death")))
    c.close()
    return render_template("queue.html", rows=rows, p_star=p_star)

def _case_or_404(c, cid):
    case = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.gender, pension_master.dob, "
        "pension_master.address, pension_master.scheme_code AS scheme, pension_master.monthly_amount "
        "FROM cases JOIN pension_master USING(pensioner_id) WHERE cases.id=?", (cid,)).fetchone()
    if not case:
        abort(404)
    return case

@app.route("/case/<int:cid>")
def case_detail(cid):
    r = officer_required()
    if r: return r
    c = conn()
    case = _case_or_404(c, cid)
    sigs = c.execute("SELECT * FROM signals WHERE case_id=?", (cid,)).fetchall()
    ver = c.execute("SELECT * FROM verifications WHERE case_id=?", (cid,)).fetchall()
    match = None
    if case["matched_death_id"]:
        match = c.execute(
            "SELECT registration_no, deceased_name AS dname, date_of_death, district AS registrar "
            "FROM death_registry WHERE registration_no=?",
            (case["matched_death_id"],)).fetchone()
    appeal = c.execute("SELECT * FROM appeals WHERE case_id=? ORDER BY id DESC", (cid,)).fetchall()
    window = int(db.get_setting(c, "appeal_window_days"))
    deadline = None
    if case["held_at"]:
        deadline = (datetime.fromisoformat(case["held_at"].replace("Z", "")) + timedelta(days=window)).date().isoformat()
    pending = c.execute("SELECT * FROM hold_requests WHERE case_id=? AND state='PENDING' ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    c.close()
    return render_template("case.html", case=case, sigs=sigs, ver=ver, match=match,
                           appeals=appeal, deadline=deadline, pending=pending,
                           officer_name=session.get("officer_name", "officer"))

@app.route("/case/<int:cid>/verify", methods=["POST"])
def verify(cid):
    r = officer_required()
    if r: return r
    c = conn()
    vid = request.form.get("vid")
    done = 1 if request.form.get("done") == "1" else 0
    c.execute("UPDATE verifications SET done=?, note=? WHERE id=? AND case_id=?",
              (done, request.form.get("note", ""), vid, cid))
    c.execute("UPDATE cases SET state='VERIFICATION' WHERE id=? AND state IN ('FLAGGED','UNDER_REVIEW')", (cid,))
    db.log(c, session.get("officer_name", "officer"), "verify_step", f"case={cid} step={vid} done={done}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid))

def _tracking_id():
    return "APL-" + secrets.token_hex(20).upper()

MIN_REASON_CHARS = 40

def _case_snapshot(c, cid):
    """Hash of the evidence the requesting officer saw: signals, verification
    state and probability. Approval binds to this snapshot."""
    import hashlib
    sigs = c.execute("SELECT signal,present,value FROM signals WHERE case_id=? ORDER BY signal", (cid,)).fetchall()
    ver = c.execute("SELECT step,done,note FROM verifications WHERE case_id=? ORDER BY step", (cid,)).fetchall()
    case = c.execute("SELECT probability,matched_death_id FROM cases WHERE id=?", (cid,)).fetchone()
    feeds = [dict(r) for r in c.execute("SELECT feed_id,last_ingest_at,rows_loaded,rows_rejected FROM feeds ORDER BY feed_id")]
    profile = c.execute("SELECT p.* FROM pension_master p JOIN cases c USING(pensioner_id) WHERE c.id=?", (cid,)).fetchone()
    provenance_head = c.execute("SELECT MAX(id) FROM audit WHERE action='feed_provenance'").fetchone()[0]
    body = repr(([dict(s) for s in sigs], [dict(v) for v in ver], case["probability"], case["matched_death_id"], feeds, dict(profile) if profile else None, provenance_head))
    return hashlib.sha256(body.encode()).hexdigest()

def _boilerplate(c, reasons):
    """Reject reused or near-reused justifications: exact duplicates and
    near-duplicates (>=0.85 similarity) of reasons on any other case or
    pending request. Cosmetic rewording of the same text is still boilerplate."""
    import difflib
    norm = " ".join(reasons.lower().split())
    rows = c.execute("SELECT hold_reasons FROM cases WHERE hold_reasons IS NOT NULL").fetchall()
    rows += c.execute("SELECT reasons AS hold_reasons FROM hold_requests WHERE state='PENDING'").fetchall()
    for r in rows:
        other = " ".join((r["hold_reasons"] or "").lower().split())
        if other and (other == norm or difflib.SequenceMatcher(None, norm, other).ratio() >= 0.85):
            return True
    return False

@app.route("/case/<int:cid>/hold", methods=["POST"])
def hold(cid):
    """Request a hold. Dual control: the request only marks the case
    HOLD_PENDING; a DIFFERENT officer must approve it before anything is held."""
    r = officer_required()
    if r: return r
    reasons = (request.form.get("reasons") or "").strip()[:4000]
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    case = _case_or_404(c, cid)
    if case["state"] not in ("FLAGGED", "UNDER_REVIEW", "VERIFICATION"):
        c.close()
        abort(409)
    ver = c.execute("SELECT COUNT(*) total, SUM(done) done FROM verifications WHERE case_id=?", (cid,)).fetchone()
    if len(reasons) < MIN_REASON_CHARS:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err=f"Written reasons are required, at least {MIN_REASON_CHARS} characters of case-specific detail."))
    if _boilerplate(c, reasons):
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="These reasons were already used on another case. Copied boilerplate is not accepted; write case-specific reasons."))
    if ver["total"] and ver["done"] < ver["total"]:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="All verification steps must be completed before a hold."))
    present = {r["signal"] for r in c.execute("SELECT signal FROM signals WHERE case_id=? AND present=1", (cid,))}
    cites = [s for s in request.form.getlist("cites") if s in present and not s.endswith("_cap") and s != "audit_sample"]
    if not cites:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="Cite at least one evidence signal from this case that supports the hold."))
    me = session.get("officer_name", "officer")
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    snap = _case_snapshot(c, cid)
    c.execute("INSERT INTO hold_requests(case_id,requester,reasons,requested_at,snapshot_hash,cites) VALUES(?,?,?,?,?,?)",
              (cid, me, reasons, now, snap, ",".join(cites)))
    c.execute("UPDATE cases SET state='HOLD_PENDING' WHERE id=?", (cid,))
    db.log(c, me, "hold_request", f"case={cid}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg="Hold requested. A second officer must approve it before the pension is held."))

@app.route("/case/<int:cid>/approve-hold", methods=["POST"])
def approve_hold(cid):
    r = officer_required()
    if r: return r
    me = session.get("officer_name", "officer")
    c = conn()
    if not _fresh_auth(me, request.form.get("password")):
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="Re-enter your password to approve a hold."))
    c.execute("BEGIN IMMEDIATE")
    case_state = _case_or_404(c, cid)["state"]
    req = c.execute("SELECT * FROM hold_requests WHERE case_id=? AND state='PENDING' ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if not req or case_state != "HOLD_PENDING":
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="No pending hold request."))
    if req["requester"] == me:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="Dual control: the officer who requested the hold cannot approve it. A different officer must sign in and approve."))
    if req["snapshot_hash"] and req["snapshot_hash"] != _case_snapshot(c, cid):
        c.execute("UPDATE hold_requests SET state='STALE' WHERE id=?", (req["id"],))
        c.execute("UPDATE cases SET state='VERIFICATION' WHERE id=? AND state='HOLD_PENDING'", (cid,))
        db.log(c, me, "hold_stale", f"case={cid} requester={req['requester']}")
        c.commit()
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="The case evidence changed since this hold was requested. The request is void; review the current evidence and request again."))
    now = datetime.utcnow()
    c.execute("UPDATE hold_requests SET state='APPROVED' WHERE id=?", (req["id"],))
    c.execute("UPDATE cases SET state='HELD', hold_reasons=?, held_at=? WHERE id=?",
              (req["reasons"], now.isoformat(timespec="seconds") + "Z", cid))
    case = c.execute("SELECT pensioner_id FROM cases WHERE id=?", (cid,)).fetchone()
    c.execute("UPDATE pension_master SET pension_status='HELD' WHERE pensioner_id=?", (case["pensioner_id"],))
    tid = _tracking_id()
    window = int(db.get_setting(c, "appeal_window_days"))
    c.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?,?)",
              (tid, cid, now.isoformat(timespec="seconds") + "Z",
               "Hold notice issued. Family may appeal by " + (now + timedelta(days=window)).date().isoformat() + ".",
               "NOTICE"))
    db.log(c, me, "hold_approved", f"case={cid} requester={req['requester']} tracking={tid}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg=f"Pension held after second-officer approval. Family appeal tracking ID: {tid}"))

@app.route("/case/<int:cid>/reject-hold", methods=["POST"])
def reject_hold(cid):
    r = officer_required()
    if r: return r
    me = session.get("officer_name", "officer")
    c = conn()
    req = c.execute("SELECT * FROM hold_requests WHERE case_id=? AND state='PENDING' ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if req:
        c.execute("UPDATE hold_requests SET state='REJECTED' WHERE id=?", (req["id"],))
        c.execute("UPDATE cases SET state='VERIFICATION' WHERE id=? AND state='HOLD_PENDING'", (cid,))
        db.log(c, me, "hold_rejected", f"case={cid} requester={req['requester']}")
        c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg="Hold request rejected; case returned to verification."))

@app.route("/case/<int:cid>/release", methods=["POST"])
def release(cid):
    r = officer_required()
    if r: return r
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    case = _case_or_404(c, cid)
    if case["state"] != "HELD":
        c.close(); abort(409)
    arrears = 0.0
    if case["held_at"]:
        held = datetime.fromisoformat(case["held_at"].replace("Z", ""))
        days = (datetime.utcnow() - held).days
        months = max(days / 30.44, 1 / 30.44)
        arrears = round(months * float(case["monthly_amount"] or 0), 2)
    c.execute("UPDATE cases SET state='RELEASED', released_at=?, arrears=? WHERE id=?",
              (datetime.utcnow().isoformat(timespec="seconds") + "Z", arrears, cid))
    c.execute("UPDATE pension_master SET pension_status='ACTIVE' WHERE pensioner_id=?", (case["pensioner_id"],))
    db.log(c, session.get("officer_name", "officer"), "release", f"case={cid} arrears={arrears}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg=f"Released in the local workflow with full arrears calculated at {arrears:,.2f}. No payment has been sent."))

@app.route("/case/<int:cid>/dismiss", methods=["POST"])
def dismiss(cid):
    r = officer_required()
    if r: return r
    note = (request.form.get("note") or "").strip()
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    case = _case_or_404(c, cid)
    if case["state"] not in ("FLAGGED", "UNDER_REVIEW", "VERIFICATION", "HOLD_PENDING"):
        c.close(); abort(409)
    c.execute("UPDATE hold_requests SET state='CANCELLED' WHERE case_id=? AND state='PENDING'", (cid,))
    c.execute("UPDATE cases SET state='DISMISSED', outcome_note=? WHERE id=?", (note, cid))
    db.log(c, session.get("officer_name", "officer"), "dismiss", f"case={cid} note={note[:80]}")
    c.commit()
    c.close()
    return redirect(url_for("queue"))

@app.route("/case/<int:cid>/outcome", methods=["POST"])
def outcome(cid):
    r = officer_required()
    if r: return r
    o = request.form.get("outcome")
    if o not in feedback.OUTCOMES:
        abort(400)
    c = conn()
    feedback.record_outcome(c, cid, o, request.form.get("note", ""),
                        actor=session.get("officer_name", "officer"))
    if o == "confirmed_deceased":
        case = c.execute("SELECT pensioner_id FROM cases WHERE id=?", (cid,)).fetchone()
        # An outcome is a recorded finding, not authority to stop payment.
        # Only the separately reviewed hold workflow changes pension status.
        c.execute("UPDATE cases SET state='CLOSED_CONFIRMED' WHERE id=? AND state!='RELEASED'", (cid,))
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid))

@app.route("/queue/export")
def queue_export():
    r = officer_required()
    if r: return r
    import tempfile, os as _os
    from scripts.export_flags import export
    fd, path = tempfile.mkstemp(suffix=".csv")
    _os.close(fd)
    try:
        export(path)
        with open(path) as fh:
            body = fh.read()
    finally:
        _os.unlink(path)
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=ranked_flags.csv"})

@app.route("/appeals")
def appeals():
    r = officer_required()
    if r: return r
    c = conn()
    rows = c.execute(
        "SELECT appeals.*, cases.pensioner_id, pension_master.full_name AS name FROM appeals "
        "JOIN cases ON appeals.case_id=cases.id JOIN pension_master USING(pensioner_id) "
        "ORDER BY appeals.id DESC").fetchall()
    sla = int(db.get_setting(c, "appeal_response_sla_days") or 14)
    today = datetime.utcnow().date()
    rows = [dict(r) for r in rows]
    for r in rows:
        r["overdue"] = (r["status"] == "OPEN" and r["submitted_at"] and
                        (today - datetime.fromisoformat(r["submitted_at"].replace("Z", "")).date()).days > sla)
    c.close()
    return render_template("appeals.html", rows=rows, sla=sla)

@app.route("/appeals/<int:aid>/resolve", methods=["POST"])
def appeal_resolve(aid):
    r = officer_required()
    if r: return r
    decision = (request.form.get("decision") or "").strip()[:2000]
    status = request.form.get("status")
    if status not in ("UPHELD", "RELEASED"):
        abort(400)
    c = conn()
    c.execute("UPDATE appeals SET status=?, decision=?, resolved_at=? WHERE id=?",
              (status, decision, datetime.utcnow().isoformat(timespec="seconds") + "Z", aid))
    db.log(c, session.get("officer_name", "officer"), "appeal_resolve", f"appeal={aid} status={status}")
    c.commit()
    c.close()
    return redirect(url_for("appeals"))

@app.route("/appeal", methods=["GET", "POST"])
def appeal_portal():
    c = conn()
    found, err = None, None
    if request.method == "POST":
        ip = (request.access_route[0] if os.environ.get("PIM_TRUST_PROXY") == "1" else request.remote_addr) or "?"
        if _throttled(ip, 20, 60):
            c.close()
            return render_template("appeal.html", err="Too many attempts. Please wait a minute and try again.", found=None, deadline=None, submitted=False)
        _record_fail(ip)
        tid = (request.form.get("tracking_id") or "").strip().upper()[:64]
        row = c.execute(
            "SELECT appeals.*, cases.held_at, cases.state, pension_master.scheme_code AS scheme FROM appeals "
            "JOIN cases ON appeals.case_id=cases.id JOIN pension_master USING(pensioner_id) "
            "WHERE tracking_id=?", (tid,)).fetchone()
        if not row:
            err = "No case found for that tracking ID."
        elif request.form.get("statement"):
            window = int(db.get_setting(c, "appeal_window_days"))
            held = datetime.fromisoformat(row["held_at"].replace("Z", "")) if row["held_at"] else None
            if held and datetime.utcnow() > held + timedelta(days=window):
                err = "The appeal window for this case has closed."
            elif c.execute("SELECT COUNT(*) FROM appeals WHERE case_id=? AND status='OPEN'", (row["case_id"],)).fetchone()[0]:
                err = "An appeal is already open for this case. Please wait for its review."
            else:
                c.execute(
                    "INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,contact,status) "
                    "VALUES(?,?,?,?,?, 'OPEN')",
                    (_tracking_id(), row["case_id"], datetime.utcnow().isoformat(timespec="seconds") + "Z",
                     request.form["statement"].strip()[:5000], request.form.get("contact", "")[:200],))
                db.log(c, "family", "appeal_submit", f"case={row['case_id']} via={tid}")
                c.commit()
                c.close()
                return render_template("appeal.html", submitted=True)
        found = row
    window = int(db.get_setting(c, "appeal_window_days"))
    deadline = None
    if found and found["held_at"]:
        deadline = (datetime.fromisoformat(found["held_at"].replace("Z", "")) + timedelta(days=window)).date().isoformat()
    c.close()
    return render_template("appeal.html", found=found, err=err, deadline=deadline, submitted=False)

@app.route("/context")
def context_page():
    c = conn()
    rows = c.execute("SELECT * FROM public_context ORDER BY id").fetchall()
    c.close()
    return render_template("context.html", rows=rows)

@app.route("/health")
def health_page():
    r = officer_required()
    if r: return r
    c = conn()
    fh = health.feed_health(c)
    c.close()
    return render_template("health.html", feeds=fh)

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    r = admin_required()
    if r: return r
    c = conn()
    msg = None
    if request.method == "POST":
        for k in db.DEFAULT_SETTINGS:
            v = request.form.get(k)
            if v:
                db.set_setting(c, k, v)
        for sig in db.DEFAULT_WEIGHTS:
            lp, lm = request.form.get(f"lp_{sig}"), request.form.get(f"lm_{sig}")
            if lp and lm:
                c.execute("UPDATE weights SET lr_plus=?, lr_minus=? WHERE signal=?",
                          (float(lp), float(lm), sig))
        c.commit()
        msg = "Settings saved."
    cur = {k: db.get_setting(c, k) for k in db.DEFAULT_SETTINGS}
    w = c.execute("SELECT * FROM weights").fetchall()
    p_star = scoring.cost_threshold(float(cur["cost_false_hold"]), float(cur["cost_missed_death"]))
    c.close()
    return render_template("settings.html", s=cur, weights=w, p_star=p_star, msg=msg)

@app.route("/feedback", methods=["GET"])
def feedback_page():
    r = officer_required()
    if r: return r
    c = conn()
    st = feedback.stats(c)
    au = feedback.audit_stats(c)
    w = c.execute("SELECT * FROM weights").fetchall()
    c.close()
    return render_template("feedback.html", stats=st, weights=w, audit=au)

@app.route("/feedback/recalibrate", methods=["POST"])
def recalibrate():
    r = officer_required()
    if r: return r
    c = conn()
    _, msg = feedback.recalibrate(c)
    c.close()
    return redirect(url_for("feedback_page", msg=msg))

@app.context_processor
def inject():
    return {"request": request}

if __name__ == "__main__":
    app.run(host=os.environ.get("PIM_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
