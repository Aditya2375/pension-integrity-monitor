import csv, hashlib, io, os, secrets, tempfile, uuid
from datetime import datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, abort, Response, send_file, g)
from pim import db, ingest, pipeline, feedback, health, scoring, workflow as wf, audit, users, notify, otp, i18n, evidence
from pim.workflow import Actor, WorkflowError
from security.web import install_csrf, client_ip, csv_cell
from security.limiter import Limiter

app = Flask(__name__)
# Session signing key: from the environment in every real deployment. Without
# it (local synthetic demo) a per-boot random key is used and sessions end on restart.
app.secret_key = os.environ.get("PIM_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get("PIM_INSECURE_HTTP") != "1",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=300 * 1024 * 1024,  # feed uploads stream; this caps disk abuse
)
install_csrf(app)

TRUSTED_PROXIES = tuple(x.strip() for x in os.environ.get("PIM_TRUSTED_PROXIES", "").split(",") if x.strip())
DEMO_SHOW_OTP = os.environ.get("PIM_DEMO_SHOW_OTP") == "1"   # synthetic demo only
EVIDENCE_DIR = os.environ.get("PIM_EVIDENCE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence"))
EVIDENCE_ENABLED = os.environ.get("PIM_EVIDENCE_ENABLED") == "1"   # off unless explicitly enabled
app.config["NOTIFY_ADAPTER"] = None   # set by the integration lane; None means nothing is ever sent
_limiter = None


def limiter():
    global _limiter
    path = os.environ.get("PIM_LIMITER_DB") or db.DB_PATH + ".limits"
    if _limiter is None or _limiter.path != path:
        _limiter = Limiter(path)
    return _limiter


def allow(scope, ident, limit, window):
    """Rate limit on a hashed key so no raw IP or reference is stored."""
    key = scope + ":" + hashlib.sha256(ident.encode()).hexdigest()[:32]
    return limiter().allow(key, limit, window)


def ip():
    return client_ip(request.remote_addr, request.headers.get("X-Forwarded-For"), TRUSTED_PROXIES)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.scheme == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

with app.app_context():
    db.init_db()
    _c = db.connect()
    wf.ensure_schema(_c)
    users.bootstrap_from_env(_c)
    _c.close()

def conn():
    return db.connect()

READ_ROLES = ("officer", "supervisor", "auditor", "admin")

def current_actor():
    """The signed-in user, re-read from the users table on every request, so a
    disabled account or changed role or jurisdiction takes effect at once. The
    session holds only the username."""
    if "actor" in g:
        return g.actor
    actor = None
    name = session.get("user")
    if name:
        c = conn()
        try:
            actor = users.get(c, name)
            if actor is None:
                audit.append(c, "system", "session_revoked", None, "", None)
                c.commit()
        finally:
            c.close()
        if actor is None:
            session.clear()
    g.actor = actor
    return actor

def guard(*roles):
    """None when the signed-in user may proceed, else a redirect or 403."""
    a = current_actor()
    if not a:
        return redirect(url_for("login", next=request.path))
    if roles and a.role not in roles:
        abort(403)
    return None

def officer_required():
    return guard(*READ_ROLES)

def lang():
    if request.args.get("lang") in i18n.LANGS:
        session["lang"] = request.args["lang"]
    return i18n.pick(session.get("lang", "en"))

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", title="Not allowed", text="Your role cannot do this."), 403

@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        who = (request.form.get("username") or "").strip()[:80]
        if not allow("login-ip", ip(), 10, 900) or not allow("login-user", who.lower(), 8, 900):
            err = "Too many attempts. Try again in 15 minutes."
        else:
            c = conn()
            actor = users.authenticate(c, who, request.form.get("key"))
            if actor:
                audit.append(c, actor.username, "login", None, "", actor.role)
                c.commit()
            else:
                audit.append(c, "anonymous", "login_failed", None, "", None)
                c.commit()
            c.close()
            if actor:
                session.clear()   # new session and CSRF token after authentication
                session.update(user=actor.username)
                session.permanent = True
                nxt = request.args.get("next") or ""
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = ""
                return redirect(nxt or url_for("dashboard"))
            err = "Wrong username or key."
    return render_template("login.html", err=err)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    r = officer_required()
    if r: return r
    me = current_actor()
    frag, params = scope_sql(me)
    c = conn()
    counts = {r["state"]: r["n"] for r in c.execute(
        f"SELECT cases.state AS state, COUNT(*) n FROM cases JOIN pension_master USING(pensioner_id) WHERE {frag} GROUP BY cases.state", params)}
    top = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme FROM cases "
        "JOIN pension_master USING(pensioner_id) WHERE cases.state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') "
        f"AND {frag} ORDER BY probability DESC LIMIT 10", params).fetchall()
    fh = health.feed_health(c)
    stats = {r["outcome"]: r["n"] for r in c.execute(
        f"SELECT cases.outcome AS outcome, COUNT(*) n FROM cases JOIN pension_master USING(pensioner_id) WHERE cases.outcome IS NOT NULL AND {frag} GROUP BY cases.outcome", params)}
    c.close()
    return render_template("dashboard.html", counts=counts, top=top, feeds=fh, stats=stats)

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
    r = guard("admin")
    if r: return r
    if feed_id not in ingest.FEED_SCHEMAS:
        abort(404)
    f = request.files.get("file")
    if not f or not (f.filename or "").lower().endswith(".csv"):
        return redirect(url_for("ingest_page", msg="Upload a .csv file."))
    c = conn()
    try:
        loaded, rejected = ingest.ingest_csv_stream(c, feed_id, ingest.iter_text(f.stream))
        c.commit()
        msg = f"Loaded {loaded} rows, rejected {rejected}."
    except ValueError as e:
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
    r = guard("admin")
    if r: return r
    c = conn()
    made, p_star = pipeline.run_pipeline(c)
    c.commit()
    c.close()
    return redirect(url_for("queue", msg=f"Pipeline complete: {made} new cases. Priority threshold p*={p_star:.2f}."))

def _case_row(c, cid):
    case = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.gender, pension_master.dob, "
        "pension_master.address, pension_master.scheme_code AS scheme, pension_master.monthly_amount, "
        "pension_master.state AS juris FROM cases JOIN pension_master USING(pensioner_id) WHERE cases.id=?", (cid,)).fetchone()
    if not case:
        abort(404)
    me = current_actor()
    if (case["juris"] or "NA") not in me.jurisdictions:
        abort(404)   # outside this user's jurisdiction: not found, not forbidden
    return case

def scope_sql(me):
    """SQL fragment limiting a query that joins pension_master to the user's
    jurisdictions. Every case-level read goes through this or _case_row."""
    js = sorted(me.jurisdictions)
    if not js:
        return "0", []
    return "COALESCE(pension_master.state,'NA') IN (%s)" % ",".join("?" * len(js)), js

def _mask(v, keep=4):
    v = str(v or "")
    return ("*" * max(len(v) - keep, 0)) + v[-keep:] if v else ""

@app.route("/queue")
def queue():
    r = guard(*READ_ROLES)
    if r: return r
    me = current_actor()
    f_state = request.args.get("state", "")
    frag, params = scope_sql(me)
    c = conn()
    rows = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme, pension_master.monthly_amount, "
        "pension_master.state AS juris FROM cases JOIN pension_master USING(pensioner_id) "
        "WHERE cases.state NOT IN ('RELEASED','DISMISSED','CLOSED_CONFIRMED') AND " + frag +
        " ORDER BY priority DESC, probability DESC", params).fetchall()
    rows = [dict(r, sla=wf.sla_status(r)) for r in rows if not f_state or r["state"] == f_state]
    states = sorted({r["state"] for r in rows} | ({f_state} if f_state else set()))
    p_star = scoring.cost_threshold(float(db.get_setting(c, "cost_false_hold")),
                                    float(db.get_setting(c, "cost_missed_death")))
    c.close()
    return render_template("queue.html", rows=rows, p_star=p_star, f_state=f_state, states=states)

@app.route("/case/<int:cid>")
def case_detail(cid):
    r = guard(*READ_ROLES)
    if r: return r
    c = conn()
    case = _case_row(c, cid)
    sigs = c.execute("SELECT * FROM signals WHERE case_id=?", (cid,)).fetchall()
    ver = c.execute("SELECT * FROM verifications WHERE case_id=?", (cid,)).fetchall()
    match = None
    if case["matched_death_id"]:
        match = c.execute(
            "SELECT registration_no, deceased_name AS dname, date_of_death, district AS registrar "
            "FROM death_registry WHERE registration_no=?", (case["matched_death_id"],)).fetchone()
    appeals = c.execute("SELECT * FROM appeals WHERE case_id=? ORDER BY id DESC", (cid,)).fetchall()
    evidence = c.execute("SELECT appeal_evidence.* FROM appeal_evidence JOIN appeals ON appeals.id=appeal_id WHERE case_id=?", (cid,)).fetchall()
    decisions = c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()
    notes = c.execute("SELECT * FROM case_notes WHERE case_id=? ORDER BY id", (cid,)).fetchall()
    survivor = c.execute("SELECT * FROM survivor_steps WHERE case_id=?", (cid,)).fetchall()
    reinst = c.execute("SELECT * FROM reinstatement_requests WHERE case_id=? ORDER BY id", (cid,)).fetchall()
    outbox = c.execute("SELECT id,template,status,attempts,created_at,last_error FROM notifications WHERE case_id=? ORDER BY id", (cid,)).fetchall()
    trail = [e for e in audit.events(c) if e["object_ref"] == f"case:{cid}"]
    pending = next((d for d in decisions if d["status"] == "PENDING"), None)
    c.close()
    return render_template("case.html", case=case, sigs=sigs, ver=ver, match=match, appeals=appeals,
                           evidence=evidence, decisions=decisions, notes=notes, survivor=survivor,
                           reinst=reinst, outbox=outbox, delivery_ready=bool(app.config.get('NOTIFY_ADAPTER')), trail=trail, pending=pending, me=current_actor(), mask=_mask,
                           sla=wf.sla_status(case))

def _act(cid, fn, ok_msg, roles=("officer", "supervisor")):
    """Run one workflow action for the signed-in user, committing the change
    and its audit entry together or neither."""
    r = guard(*roles)
    if r: return r
    c = conn()
    try:
        _case_row(c, cid)
        result = fn(c, current_actor())
        c.commit()
        msg = ok_msg(result) if callable(ok_msg) else ok_msg
        key = "msg"
    except WorkflowError as e:
        c.rollback()
        msg, key = str(e), "err"
    finally:
        c.close()
    return redirect(url_for("case_detail", cid=cid, **{key: msg}))

@app.route("/case/<int:cid>/start", methods=["POST"])
def case_start(cid):
    return _act(cid, lambda c, a: wf.start_review(c, cid, a), "Review started.", ("officer",))

@app.route("/case/<int:cid>/verify", methods=["POST"])
def verify(cid):
    f = request.form
    return _act(cid, lambda c, a: wf.complete_step(c, cid, f.get("vid"), f.get("done") == "1", f.get("note", "")[:500], a),
                "Step updated.", ("officer",))

@app.route("/case/<int:cid>/note", methods=["POST"])
def case_note(cid):
    return _act(cid, lambda c, a: wf.add_note(c, cid, a, request.form.get("body")), "Note added.", ("officer",))

@app.route("/case/<int:cid>/propose", methods=["POST"])
def case_propose(cid):
    kind = request.form.get("kind")
    return _act(cid, lambda c, a: wf.propose(c, cid, kind, a, request.form.get("reason")),
                "Sent to a supervisor for second approval. Nothing changes for the pensioner yet.", ("officer",))

def _delivery_note():
    return ("Delivery is handled by the connected message service; check the status below."
            if app.config.get("NOTIFY_ADAPTER") else
            "No message service is connected on this system, so nothing has been sent. Give the family their reference another way.")

@app.route("/case/<int:cid>/decide", methods=["POST"])
def case_decide(cid):
    approve = request.form.get("verdict") == "approve"
    return _act(cid, lambda c, a: wf.decide(c, cid, a, approve, request.form.get("note", "")),
                ("Approved. A notice for the family is queued. " + _delivery_note() + " Payment continues during the notice period.") if approve else "Proposal sent back to the officer.",
                ("supervisor",))

@app.route("/case/<int:cid>/suspend", methods=["POST"])
def case_suspend(cid):
    return _act(cid, lambda c, a: wf.suspend(c, cid, a, request.form.get("override_reason", "")),
                "Suspension recorded as a recommendation for the payment system. This system does not stop payments itself.", ("supervisor",))

@app.route("/case/<int:cid>/release", methods=["POST"])
def release(cid):
    return _act(cid, lambda c, a: wf.release(c, cid, a, request.form.get("note")),
                lambda arrears: f"Released. A reinstatement request was recorded; arrears due {arrears:,.2f}. This system does not pay: the payer confirms payment.",
                ("supervisor",))

@app.route("/case/<int:cid>/dismiss", methods=["POST"])
def dismiss(cid):
    return _act(cid, lambda c, a: wf.dismiss(c, cid, a, request.form.get("note")), "Case dismissed.", ("officer",))

@app.route("/case/<int:cid>/survivor/<int:sid>", methods=["POST"])
def survivor_step(cid, sid):
    f = request.form
    return _act(cid, lambda c, a: wf.complete_survivor_step(c, cid, sid, f.get("done") == "1", f.get("note", "")[:500], a),
                "Step updated.", ("officer",))

@app.route("/case/<int:cid>/finalize-death", methods=["POST"])
def finalize_death_route(cid):
    return _act(cid, lambda c, a: wf.finalize_death(c, cid, a),
                "Death confirmation finalised after the full notice and appeal period. " + _delivery_note(), ("supervisor",))

@app.route("/case/<int:cid>/reopen", methods=["POST"])
def reopen_route(cid):
    return _act(cid, lambda c, a: wf.reopen(c, cid, a, request.form.get("note")),
                "Reopened. A reinstatement request was recorded and an independent supervisor will decide.", ("supervisor",))

@app.route("/case/<int:cid>/appeal-decision", methods=["POST"])
def appeal_decision(cid):
    uphold = request.form.get("verdict") == "uphold"
    return _act(cid, lambda c, a: wf.resolve_appeal(c, cid, a, uphold, request.form.get("note")),
                "Appeal decided." , ("supervisor",))

@app.route("/appeals")
def appeals():
    r = guard(*READ_ROLES)
    if r: return r
    me = current_actor()
    frag, params = scope_sql(me)
    c = conn()
    rows = c.execute(
        "SELECT appeals.*, cases.pensioner_id, cases.state AS case_state, pension_master.full_name AS name, "
        "pension_master.state AS juris FROM appeals JOIN cases ON appeals.case_id=cases.id "
        "JOIN pension_master USING(pensioner_id) WHERE " + frag + " ORDER BY appeals.id DESC", params).fetchall()
    c.close()
    return render_template("appeals.html", rows=rows)

@app.route("/evidence/<int:eid>")
def evidence_file(eid):
    r = guard(*READ_ROLES)
    if r: return r
    c = conn()
    e = c.execute("SELECT appeal_evidence.*, appeals.case_id FROM appeal_evidence JOIN appeals ON appeals.id=appeal_id WHERE appeal_evidence.id=?", (eid,)).fetchone()
    if not e:
        c.close(); abort(404)
    _case_row(c, e["case_id"])
    if e["status"] != "RELEASED":
        c.close()
        return redirect(url_for("case_detail", cid=e["case_id"], err="This file is still in quarantine. A supervisor must release it after checking it in an isolated viewer."))
    try:
        real = evidence.readable_path(EVIDENCE_DIR, e["stored_path"], e["sha256"])
    except evidence.EvidenceError as ex:
        c.close()
        return redirect(url_for("case_detail", cid=e["case_id"], err=str(ex)))
    audit.append(c, current_actor().username, "evidence_viewed", e["case_id"], f"evidence{eid}", current_actor().role)
    c.commit(); c.close()
    ext = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}.get(e["mime"], "bin")
    resp = send_file(real, mimetype="application/octet-stream", as_attachment=True, download_name=f"evidence-{eid}.{ext}")
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return resp

@app.route("/evidence/<int:eid>/release", methods=["POST"])
def evidence_release(eid):
    r = guard("supervisor")
    if r: return r
    me = current_actor()
    c = conn()
    e = c.execute("SELECT appeal_evidence.*, appeals.case_id FROM appeal_evidence JOIN appeals ON appeals.id=appeal_id WHERE appeal_evidence.id=?", (eid,)).fetchone()
    if not e:
        c.close(); abort(404)
    _case_row(c, e["case_id"])
    if request.form.get("attest") != "1":
        c.close()
        return redirect(url_for("case_detail", cid=e["case_id"], err="Tick the box to confirm you checked the file in an isolated viewer."))
    try:
        evidence.readable_path(EVIDENCE_DIR, e["stored_path"], e["sha256"])
    except evidence.EvidenceError as ex:
        c.close()
        return redirect(url_for("case_detail", cid=e["case_id"], err=str(ex)))
    c.execute("UPDATE appeal_evidence SET status='RELEASED' WHERE id=? AND status='QUARANTINED'", (eid,))
    audit.append(c, me.username, "evidence_released", e["case_id"], f"evidence{eid}", me.role)
    c.commit(); c.close()
    return redirect(url_for("case_detail", cid=e["case_id"], msg="File released to staff for download."))

# ---- public family portal ---------------------------------------------------
def _store_evidence(c, appeal_id, f):
    """Parse the file (not just its first bytes), then keep it in the private
    quarantine area. Raises WorkflowError with a plain message on any problem."""
    if not f or not getattr(f, "filename", ""):
        return None
    if not EVIDENCE_ENABLED:
        raise WorkflowError("Uploading documents is switched off on this system. Take your documents to your pension office.")
    data = f.stream.read(evidence.MAX_BYTES + 1)
    try:
        ext, mime = evidence.validate(data)
    except evidence.EvidenceError as e:
        raise WorkflowError(str(e))
    path = evidence.store(EVIDENCE_DIR, data, ext)
    cur = c.execute("INSERT INTO appeal_evidence(appeal_id,ts,filename,mime,size,sha256,stored_path,status) VALUES(?,?,?,?,?,?,?,'QUARANTINED')",
                    (appeal_id, wf._now(), "upload." + ext, mime, len(data), hashlib.sha256(data).hexdigest(), path))
    case_id = c.execute("SELECT case_id FROM appeals WHERE id=?", (appeal_id,)).fetchone()["case_id"]
    audit.append(c, "appellant", "evidence_uploaded", case_id, f"evidence{cur.lastrowid}", "family")
    return path

def _portal_ctx(c, tid, L):
    row = c.execute("SELECT appeals.*, cases.state, cases.notice_issued_at, cases.held_at, cases.payment_status, cases.id AS cid "
                    "FROM appeals JOIN cases ON appeals.case_id=cases.id WHERE tracking_id=?", (tid,)).fetchone()
    if not row:
        return None
    window = int(db.get_setting(c, "appeal_window_days"))
    start = row["notice_issued_at"] or row["held_at"]
    deadline = (wf._parse(start) + timedelta(days=window)).date().isoformat() if start else None
    return dict(row=row, deadline=deadline)

@app.route("/appeal", methods=["GET", "POST"])
def appeal_portal():
    L = lang()
    c0 = conn()
    verified = otp.grant_tid(c0, session.get("appeal_grant"))
    c0.close()
    ctx = dict(evidence_enabled=EVIDENCE_ENABLED, delivery_ready=bool(app.config.get("NOTIFY_ADAPTER")), L=L, t=lambda k, **kw: i18n.t(k, L, **kw), langs=i18n.LANGS, step="ref", err=None, info=None,
               demo_code=None, found=None, submitted=False)
    c = conn()
    try:
        if request.method == "POST":
            action = request.form.get("action")
            if not allow("appeal-ip", ip(), 20, 60):
                ctx["err"] = "Too many attempts. Please wait a minute and try again."
            elif action == "send_code":
                tid = (request.form.get("tracking_id") or "").strip().upper()[:20]
                if allow("otp-ref", tid, 3, 600):
                    code = otp.issue(c, tid, L)
                    if code:
                        cid_ = c.execute("SELECT case_id FROM appeals WHERE tracking_id=?", (tid,)).fetchone()["case_id"]
                        audit.append(c, "appellant", "portal_code_requested", cid_, "", "family")
                    c.commit()
                    if code and DEMO_SHOW_OTP:
                        ctx["demo_code"] = code
                session["appeal_pending"] = tid
                ctx.update(step="code", info=(
                    "If that reference is valid, a code has been queued for the contact on record. It can take a few minutes to arrive."
                    if app.config.get("NOTIFY_ADAPTER") else
                    "If that reference is valid, a code has been queued. This system has no message service connected, so it cannot be delivered here. Please ask your pension office."))
            elif action == "check_code":
                tid = session.get("appeal_pending", "")
                ok = bool(tid) and allow("otp-try", tid, 8, 900) and otp.check(c, tid, request.form.get("code"))
                c.commit()
                if ok:
                    session["appeal_grant"] = otp.grant(c, tid)
                    c.commit()
                    verified = tid
                else:
                    ctx.update(step="code", err="That code is not valid or has expired.")
            elif action == "appeal" and verified:
                stored = []
                try:
                    cid = wf.file_appeal(c, verified, request.form.get("statement"), request.form.get("contact", ""))
                    aid = c.execute("SELECT id FROM appeals WHERE tracking_id=?", (verified,)).fetchone()["id"]
                    p = _store_evidence(c, aid, request.files.get("evidence"))
                    if p:
                        stored.append(p)
                    if not otp.consume_grant(c, session.get("appeal_grant")):
                        raise WorkflowError("Your session has ended. Please ask for a new code.")
                    c.commit()
                    session.pop("appeal_grant", None)
                    ctx["submitted"] = True
                    verified = None
                except Exception as e:   # roll back the database and remove any file already written
                    c.rollback()
                    for p in stored:
                        try:
                            os.unlink(p)
                        except OSError:
                            pass
                    if not isinstance(e, WorkflowError):
                        raise
                    ctx["err"] = str(e)
            elif action == "signout":
                otp.revoke_grant(c, session.get("appeal_grant")); c.commit()
                session.pop("appeal_grant", None); session.pop("appeal_pending", None); verified = None
        if verified:
            ctx.update(step="status", found=_portal_ctx(c, verified, L))
            if not ctx["found"]:
                session.pop("appeal_grant", None); ctx.update(step="ref", found=None)
    finally:
        c.close()
    return render_template("appeal.html", **ctx)

EXPORT_SIGNALS = ["death_registry_match", "hospital_died_match", "electoral_deletion", "bank_cliff", "telecom_cliff",
                  "aligned_cliff", "life_cert_overdue", "bank_inactivity", "telecom_quiet", "alive_itr", "alive_utility"]

@app.route("/queue/export")
def queue_export():
    r = guard("officer", "supervisor", "auditor")
    if r: return r
    me = current_actor()
    frag, params = scope_sql(me)
    c = conn()
    cases = c.execute(
        "SELECT cases.* FROM cases JOIN pension_master USING(pensioner_id) "
        f"WHERE cases.state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') AND {frag} "
        "ORDER BY priority DESC, probability DESC", params).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["rank", "case_id", "pensioner_id", "review_priority_score", "priority_flag"]
               + [f"sig_{s}" for s in EXPORT_SIGNALS] + [f"effect_{s}" for s in EXPORT_SIGNALS])
    for i, case in enumerate(cases, 1):
        sigs = {x["signal"]: x for x in c.execute("SELECT * FROM signals WHERE case_id=?", (case["id"],))}
        row = [i, case["id"], case["pensioner_id"], case["probability"], case["priority"]] \
            + [int(sigs[x]["present"]) if x in sigs else "" for x in EXPORT_SIGNALS] \
            + [sigs[x]["value"] if x in sigs else "" for x in EXPORT_SIGNALS]
        w.writerow([csv_cell(v) if isinstance(v, str) else v for v in row])
    audit.append(c, me.username, "queue_export", None, "", me.role)
    c.commit()
    c.close()
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=ranked_flags.csv"})

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

import math

SETTING_BOUNDS = {"base_rate": (1e-6, 0.5, False), "match_threshold": (0.0, 1.0, False), "appeal_window_days": (1, 365, True), "notice_period_days": (1, 180, True)}

def _num(v, name, lo=0.0, hi=1e12, integer=False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(x) or x < lo or x > hi or (integer and x != int(x)):
        raise ValueError(f"{name} is out of range")
    return int(x) if integer else x

def _validate_settings(form):
    """Validate everything first; apply nothing unless every value is sound."""
    out, weights = {}, {}
    for k in db.DEFAULT_SETTINGS:
        v = form.get(k)
        if v:
            lo, hi, integer = SETTING_BOUNDS.get(k, (0.0, 1e12, False))
            out[k] = _num(v, k, lo, hi, integer)
    for sig in db.DEFAULT_WEIGHTS:
        lp, lm = form.get(f"lp_{sig}"), form.get(f"lm_{sig}")
        if lp and lm:
            weights[sig] = (_num(lp, "lr_plus " + sig, 1e-6, 1e6), _num(lm, "lr_minus " + sig, 1e-6, 1e6))
    return {"settings": out, "weights": weights}

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    r = guard("admin")
    if r: return r
    c = conn()
    msg = None
    if request.method == "POST":
        try:
            clean = _validate_settings(request.form)
        except ValueError as e:
            c.close()
            return redirect(url_for("settings_page", err=str(e)))
        for k, v in clean["settings"].items():
            db.set_setting(c, k, v)
        for sig, (lp, lm) in clean["weights"].items():
            c.execute("UPDATE weights SET lr_plus=?, lr_minus=? WHERE signal=?", (lp, lm, sig))
        audit.append(c, current_actor().username, "settings_changed", None, "", current_actor().role)
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
    w = c.execute("SELECT * FROM weights").fetchall()
    c.close()
    return render_template("feedback.html", stats=st, weights=w)

@app.route("/feedback/recalibrate", methods=["POST"])
def recalibrate():
    r = guard("admin")
    if r: return r
    c = conn()
    _, msg = feedback.recalibrate(c)
    c.close()
    return redirect(url_for("feedback_page", msg=msg))

@app.context_processor
def inject():
    a = current_actor()
    return {"request": request, "me_user": a.username if a else None, "me_role": a.role if a else None}

if __name__ == "__main__":
    app.run(host=os.environ.get("PIM_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
