import csv, hashlib, io, os, secrets, tempfile, uuid
from datetime import datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, abort, Response, send_file)
from pim import db, ingest, pipeline, feedback, health, scoring, workflow as wf, audit, users, notify, otp, i18n
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
EVIDENCE_MAX = 5 * 1024 * 1024
EVIDENCE_TYPES = {b"%PDF-": ("pdf", "application/pdf"), b"\xff\xd8\xff": ("jpg", "image/jpeg"),
                  b"\x89PNG\r\n\x1a\n": ("png", "image/png")}
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
    if not session.get("user"):
        return None
    return Actor(session["user"], session["role"], tuple(session.get("juris") or ("NA",)))

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
                session.update(user=actor.username, role=actor.role, juris=sorted(actor.jurisdictions))
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
    c = conn()
    counts = {r["state"]: r["n"] for r in
              c.execute("SELECT state, COUNT(*) n FROM cases GROUP BY state")}
    top = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme FROM cases "
        "JOIN pension_master USING(pensioner_id) WHERE cases.state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') "
        "ORDER BY probability DESC LIMIT 10").fetchall()
    fh = health.feed_health(c)
    stats = feedback.stats(c)
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

def _mask(v, keep=4):
    v = str(v or "")
    return ("*" * max(len(v) - keep, 0)) + v[-keep:] if v else ""

@app.route("/queue")
def queue():
    r = guard(*READ_ROLES)
    if r: return r
    me = current_actor()
    f_state = request.args.get("state", "")
    c = conn()
    rows = c.execute(
        "SELECT cases.*, pension_master.full_name AS name, pension_master.scheme_code AS scheme, pension_master.monthly_amount, "
        "pension_master.state AS juris FROM cases JOIN pension_master USING(pensioner_id) "
        "WHERE cases.state NOT IN ('RELEASED','DISMISSED','CLOSED_CONFIRMED') "
        "ORDER BY priority DESC, probability DESC").fetchall()
    rows = [dict(r, sla=wf.sla_status(r)) for r in rows if (r["juris"] or "NA") in me.jurisdictions
            and (not f_state or r["state"] == f_state)]
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
    trail = [e for e in audit.events(c) if e["object_ref"] == f"case:{cid}"]
    pending = next((d for d in decisions if d["status"] == "PENDING"), None)
    c.close()
    return render_template("case.html", case=case, sigs=sigs, ver=ver, match=match, appeals=appeals,
                           evidence=evidence, decisions=decisions, notes=notes, survivor=survivor,
                           reinst=reinst, trail=trail, pending=pending, me=current_actor(), mask=_mask,
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

@app.route("/case/<int:cid>/decide", methods=["POST"])
def case_decide(cid):
    approve = request.form.get("verdict") == "approve"
    return _act(cid, lambda c, a: wf.decide(c, cid, a, approve, request.form.get("note", "")),
                "Approved. The family has been sent a notice and payment continues during the notice period." if approve else "Proposal sent back to the officer.",
                ("supervisor",))

@app.route("/case/<int:cid>/suspend", methods=["POST"])
def case_suspend(cid):
    return _act(cid, lambda c, a: wf.suspend(c, cid, a, request.form.get("override_reason", "")),
                "Payment suspension recommended to the payment system.", ("supervisor",))

@app.route("/case/<int:cid>/release", methods=["POST"])
def release(cid):
    return _act(cid, lambda c, a: wf.release(c, cid, a, request.form.get("note")),
                lambda arrears: f"Released. A reinstatement request was recorded; arrears due {arrears:,.2f} (the payer confirms payment).",
                ("supervisor",))

@app.route("/case/<int:cid>/dismiss", methods=["POST"])
def dismiss(cid):
    return _act(cid, lambda c, a: wf.dismiss(c, cid, a, request.form.get("note")), "Case dismissed.", ("officer",))

@app.route("/case/<int:cid>/survivor/<int:sid>", methods=["POST"])
def survivor_step(cid, sid):
    f = request.form
    return _act(cid, lambda c, a: wf.complete_survivor_step(c, cid, sid, f.get("done") == "1", f.get("note", "")[:500], a),
                "Step updated.", ("officer",))

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
    c = conn()
    rows = c.execute(
        "SELECT appeals.*, cases.pensioner_id, cases.state AS case_state, pension_master.full_name AS name, "
        "pension_master.state AS juris FROM appeals JOIN cases ON appeals.case_id=cases.id "
        "JOIN pension_master USING(pensioner_id) ORDER BY appeals.id DESC").fetchall()
    rows = [r for r in rows if (r["juris"] or "NA") in me.jurisdictions]
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
    audit.append(c, current_actor().username, "evidence_viewed", e["case_id"], f"evidence{eid}", current_actor().role)
    c.commit(); c.close()
    return send_file(e["stored_path"], mimetype=e["mime"], as_attachment=True, download_name=f"evidence-{eid}." + e["mime"].split("/")[-1].replace("jpeg", "jpg"))

# ---- public family portal ---------------------------------------------------
def _store_evidence(c, appeal_id, f):
    """Validate by content, not by name; keep under a random name."""
    if not f or not f.filename:
        return None
    data = f.stream.read(EVIDENCE_MAX + 1)
    if len(data) > EVIDENCE_MAX:
        raise WorkflowError("The file is larger than 5 MB.")
    kind = next((v for sig, v in EVIDENCE_TYPES.items() if data.startswith(sig)), None)
    if not kind:
        raise WorkflowError("Only PDF, JPG or PNG files are accepted.")
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    path = os.path.join(EVIDENCE_DIR, uuid.uuid4().hex + "." + kind[0])
    with open(path, "wb") as fh:
        fh.write(data)
    c.execute("INSERT INTO appeal_evidence(appeal_id,ts,filename,mime,size,sha256,stored_path) VALUES(?,?,?,?,?,?,?)",
              (appeal_id, wf._now(), "upload." + kind[0], kind[1], len(data), hashlib.sha256(data).hexdigest(), path))

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
    verified = session.get("appeal_ok")
    ctx = dict(L=L, t=lambda k, **kw: i18n.t(k, L, **kw), langs=i18n.LANGS, step="ref", err=None, info=None,
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
                    c.commit()
                    if code and DEMO_SHOW_OTP:
                        ctx["demo_code"] = code
                session["appeal_pending"] = tid
                ctx.update(step="code", info="If that reference is valid, a code has been sent to the contact on record.")
            elif action == "check_code":
                tid = session.get("appeal_pending", "")
                ok = bool(tid) and allow("otp-try", tid, 8, 900) and otp.check(c, tid, request.form.get("code"))
                c.commit()
                if ok:
                    session["appeal_ok"] = tid
                    verified = tid
                else:
                    ctx.update(step="code", err="That code is not valid or has expired.")
            elif action == "appeal" and verified:
                try:
                    cid = wf.file_appeal(c, verified, request.form.get("statement"), request.form.get("contact", ""))
                    aid = c.execute("SELECT id FROM appeals WHERE tracking_id=?", (verified,)).fetchone()["id"]
                    _store_evidence(c, aid, request.files.get("evidence"))
                    c.commit()
                    ctx["submitted"] = True
                except WorkflowError as e:
                    c.rollback()
                    ctx["err"] = str(e)
            elif action == "signout":
                session.pop("appeal_ok", None); session.pop("appeal_pending", None); verified = None
        if verified:
            ctx.update(step="status", found=_portal_ctx(c, verified, L))
            if not ctx["found"]:
                session.pop("appeal_ok", None); ctx.update(step="ref", found=None)
    finally:
        c.close()
    return render_template("appeal.html", **ctx)

@app.route("/queue/export")
def queue_export():
    r = guard("officer", "supervisor", "auditor")
    if r: return r
    import tempfile, os as _os
    from scripts.export_flags import export, SIGNALS
    fd, path = tempfile.mkstemp(suffix=".csv")
    _os.close(fd)
    try:
        export(path)
        with open(path) as fh:
            body = fh.read()
    finally:
        _os.unlink(path)
    rows = list(csv.reader(io.StringIO(body)))
    out = io.StringIO()
    w = csv.writer(out)
    for i, row in enumerate(rows):
        w.writerow(row if i == 0 else [csv_cell(x) for x in row])
    c0 = conn()
    audit.append(c0, current_actor().username, "queue_export", None, "", current_actor().role)
    c0.commit()
    c0.close()
    body = out.getvalue()
    return Response(body, mimetype="text/csv",
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
    return {"request": request}

if __name__ == "__main__":
    app.run(host=os.environ.get("PIM_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
