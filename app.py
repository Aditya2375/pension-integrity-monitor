import os, secrets, string
from datetime import datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, abort, Response)
from pim import db, ingest, pipeline, feedback, health, scoring

app = Flask(__name__)
app.secret_key = os.environ.get("PIM_SECRET", "dev-secret-change-me")
OFFICER_KEY = os.environ.get("PIM_OFFICER_KEY", "officer")

with app.app_context():
    db.init_db()

def conn():
    return db.connect()

def officer_required():
    if not session.get("officer"):
        return redirect(url_for("login", next=request.path))
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        if request.form.get("key") == OFFICER_KEY:
            session["officer"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        err = "Wrong key."
    return render_template("login.html", err=err)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard"))

@app.route("/")
def dashboard():
    c = conn()
    counts = {r["state"]: r["n"] for r in
              c.execute("SELECT state, COUNT(*) n FROM cases GROUP BY state")}
    top = c.execute(
        "SELECT cases.*, pensioners.name, pensioners.scheme FROM cases "
        "JOIN pensioners USING(pensioner_id) WHERE state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') "
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
    r = officer_required()
    if r: return r
    if feed_id not in ingest.FEED_SCHEMAS:
        abort(404)
    f = request.files.get("file")
    if not f:
        return redirect(url_for("ingest_page"))
    c = conn()
    try:
        loaded, rejected = ingest.ingest_csv(c, feed_id, f.read().decode("utf-8-sig"))
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
    r = officer_required()
    if r: return r
    c = conn()
    pipeline.run_matching(c)
    made, p_star = pipeline.run_pipeline(c)
    c.commit()
    c.close()
    return redirect(url_for("queue", msg=f"Pipeline complete: {made} new cases. Priority threshold p*={p_star:.2f}."))

@app.route("/queue")
def queue():
    r = officer_required()
    if r: return r
    c = conn()
    rows = c.execute(
        "SELECT cases.*, pensioners.name, pensioners.scheme, pensioners.monthly_amount FROM cases "
        "JOIN pensioners USING(pensioner_id) "
        "WHERE state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') "
        "ORDER BY priority DESC, probability DESC").fetchall()
    p_star = scoring.cost_threshold(float(db.get_setting(c, "cost_false_hold")),
                                    float(db.get_setting(c, "cost_missed_death")))
    c.close()
    return render_template("queue.html", rows=rows, p_star=p_star)

def _case_or_404(c, cid):
    case = c.execute(
        "SELECT cases.*, pensioners.name, pensioners.gender, pensioners.dob, pensioners.address, "
        "pensioners.scheme, pensioners.monthly_amount, pensioners.last_life_cert_date "
        "FROM cases JOIN pensioners USING(pensioner_id) WHERE cases.id=?", (cid,)).fetchone()
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
            "SELECT matches.*, death_records.name AS dname, death_records.date_of_death, "
            "death_records.registrar FROM matches JOIN death_records USING(death_id) "
            "WHERE pensioner_id=? AND death_id=?",
            (case["pensioner_id"], case["matched_death_id"])).fetchone()
    appeal = c.execute("SELECT * FROM appeals WHERE case_id=? ORDER BY id DESC", (cid,)).fetchall()
    window = int(db.get_setting(c, "appeal_window_days"))
    deadline = None
    if case["held_at"]:
        deadline = (datetime.fromisoformat(case["held_at"].replace("Z", "")) + timedelta(days=window)).date().isoformat()
    c.close()
    return render_template("case.html", case=case, sigs=sigs, ver=ver, match=match,
                           appeals=appeal, deadline=deadline)

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
    db.log(c, "officer", "verify_step", f"case={cid} step={vid} done={done}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid))

def _tracking_id():
    return "APL-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

@app.route("/case/<int:cid>/hold", methods=["POST"])
def hold(cid):
    r = officer_required()
    if r: return r
    reasons = (request.form.get("reasons") or "").strip()
    c = conn()
    ver = c.execute("SELECT COUNT(*) total, SUM(done) done FROM verifications WHERE case_id=?", (cid,)).fetchone()
    if not reasons:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="Written reasons are required to hold a pension."))
    if ver["total"] and ver["done"] < ver["total"]:
        c.close()
        return redirect(url_for("case_detail", cid=cid, err="All verification steps must be completed before a hold."))
    now = datetime.utcnow()
    c.execute("UPDATE cases SET state='HELD', hold_reasons=?, held_at=? WHERE id=?",
              (reasons, now.isoformat(timespec="seconds") + "Z", cid))
    case = c.execute("SELECT pensioner_id FROM cases WHERE id=?", (cid,)).fetchone()
    c.execute("UPDATE pensioners SET status='held' WHERE pensioner_id=?", (case["pensioner_id"],))
    tid = _tracking_id()
    window = int(db.get_setting(c, "appeal_window_days"))
    c.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?,?)",
              (tid, cid, now.isoformat(timespec="seconds") + "Z",
               "Hold notice issued. Family may appeal by " + (now + timedelta(days=window)).date().isoformat() + ".",
               "NOTICE"))
    db.log(c, "officer", "hold", f"case={cid} tracking={tid}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg=f"Pension held. Family appeal tracking ID: {tid}"))

@app.route("/case/<int:cid>/release", methods=["POST"])
def release(cid):
    r = officer_required()
    if r: return r
    c = conn()
    case = _case_or_404(c, cid)
    arrears = 0.0
    if case["held_at"]:
        held = datetime.fromisoformat(case["held_at"].replace("Z", ""))
        days = (datetime.utcnow() - held).days
        months = max(days / 30.44, 1 / 30.44)
        arrears = round(months * float(case["monthly_amount"] or 0), 2)
    c.execute("UPDATE cases SET state='RELEASED', released_at=?, arrears=? WHERE id=?",
              (datetime.utcnow().isoformat(timespec="seconds") + "Z", arrears, cid))
    c.execute("UPDATE pensioners SET status='active' WHERE pensioner_id=?", (case["pensioner_id"],))
    db.log(c, "officer", "release", f"case={cid} arrears={arrears}")
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid, msg=f"Released with full arrears of {arrears:,.2f}."))

@app.route("/case/<int:cid>/dismiss", methods=["POST"])
def dismiss(cid):
    r = officer_required()
    if r: return r
    note = (request.form.get("note") or "").strip()
    c = conn()
    c.execute("UPDATE cases SET state='DISMISSED', outcome_note=? WHERE id=?", (note, cid))
    db.log(c, "officer", "dismiss", f"case={cid} note={note[:80]}")
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
    feedback.record_outcome(c, cid, o, request.form.get("note", ""))
    if o == "confirmed_deceased":
        case = c.execute("SELECT pensioner_id FROM cases WHERE id=?", (cid,)).fetchone()
        c.execute("UPDATE pensioners SET status='deceased' WHERE pensioner_id=?", (case["pensioner_id"],))
        c.execute("UPDATE cases SET state='CLOSED_CONFIRMED' WHERE id=? AND state!='RELEASED'", (cid,))
    c.commit()
    c.close()
    return redirect(url_for("case_detail", cid=cid))

@app.route("/queue/export")
def queue_export():
    r = officer_required()
    if r: return r
    import io, tempfile
    from scripts.export_flags import export, SIGNALS
    path = tempfile.mktemp(suffix=".csv")
    export(path)
    return Response(open(path).read(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=ranked_flags.csv"})

@app.route("/appeals")
def appeals():
    r = officer_required()
    if r: return r
    c = conn()
    rows = c.execute(
        "SELECT appeals.*, cases.pensioner_id, pensioners.name FROM appeals "
        "JOIN cases ON appeals.case_id=cases.id JOIN pensioners USING(pensioner_id) "
        "ORDER BY appeals.id DESC").fetchall()
    c.close()
    return render_template("appeals.html", rows=rows)

@app.route("/appeals/<int:aid>/resolve", methods=["POST"])
def appeal_resolve(aid):
    r = officer_required()
    if r: return r
    decision = (request.form.get("decision") or "").strip()
    status = request.form.get("status")
    if status not in ("UPHELD", "RELEASED"):
        abort(400)
    c = conn()
    c.execute("UPDATE appeals SET status=?, decision=?, resolved_at=? WHERE id=?",
              (status, decision, datetime.utcnow().isoformat(timespec="seconds") + "Z", aid))
    db.log(c, "officer", "appeal_resolve", f"appeal={aid} status={status}")
    c.commit()
    c.close()
    return redirect(url_for("appeals"))

@app.route("/appeal", methods=["GET", "POST"])
def appeal_portal():
    c = conn()
    found, err = None, None
    if request.method == "POST":
        tid = (request.form.get("tracking_id") or "").strip().upper()
        row = c.execute(
            "SELECT appeals.*, cases.held_at, cases.state, pensioners.scheme FROM appeals "
            "JOIN cases ON appeals.case_id=cases.id JOIN pensioners USING(pensioner_id) "
            "WHERE tracking_id=?", (tid,)).fetchone()
        if not row:
            err = "No case found for that tracking ID."
        elif request.form.get("statement"):
            window = int(db.get_setting(c, "appeal_window_days"))
            held = datetime.fromisoformat(row["held_at"].replace("Z", "")) if row["held_at"] else None
            if held and datetime.utcnow() > held + timedelta(days=window) and row["status"] in ("NOTICE",):
                err = "The appeal window for this case has closed."
            else:
                c.execute(
                    "INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,contact,status) "
                    "VALUES(?,?,?,?,?, 'OPEN')",
                    (_tracking_id(), row["case_id"], datetime.utcnow().isoformat(timespec="seconds") + "Z",
                     request.form["statement"].strip(), request.form.get("contact", ""),))
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
    r = officer_required()
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
    w = c.execute("SELECT * FROM weights").fetchall()
    c.close()
    return render_template("feedback.html", stats=st, weights=w)

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
