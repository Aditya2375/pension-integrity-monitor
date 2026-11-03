"""Flag pipeline: identity matching, signal assembly, LR scoring,
cost-based priority. Produces ranked review cases only. No auto-hold."""
from datetime import datetime, date
from . import db, matching, scoring

VERIFICATION_STEPS = [
    "Cross-check registrar record against the matched death entry",
    "Field verification visit to the pensioner's address",
    "Contact family or nominee on record",
    "Confirm account activity with the pension-paying bank branch",
]

def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            pass
    return None

def run_matching(conn):
    threshold = float(db.get_setting(conn, "match_threshold"))
    deaths = conn.execute("SELECT * FROM death_records").fetchall()
    pensioners = conn.execute("SELECT * FROM pensioners WHERE status='active'").fetchall()
    n = 0
    for d in deaths:
        for p in pensioners:
            score, nm, gok, dobm = matching.match_score(p, d)
            if score >= threshold:
                conn.execute(
                    "INSERT INTO matches(death_id,pensioner_id,name_pct,gender_ok,dob_match,score) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(death_id,pensioner_id) DO UPDATE SET "
                    "name_pct=excluded.name_pct, gender_ok=excluded.gender_ok, "
                    "dob_match=excluded.dob_match, score=excluded.score",
                    (d["death_id"], p["pensioner_id"], nm, int(gok), dobm, score))
                n += 1
    db.log(conn, "pipeline", "matching", f"matches_at_or_above_threshold={n}")
    return n

def _signals_for(conn, p, weights, today):
    bank_months = float(db.get_setting(conn, "bank_inactivity_months"))
    overdue_days = int(db.get_setting(conn, "life_cert_overdue_days"))
    old_age = int(db.get_setting(conn, "old_age_years"))
    sigs = {}

    m = conn.execute(
        "SELECT * FROM matches WHERE pensioner_id=? ORDER BY score DESC LIMIT 1",
        (p["pensioner_id"],)).fetchone()
    sigs["death_registry_match"] = (m is not None, m["score"] if m else None, m)

    e = conn.execute(
        "SELECT * FROM electoral WHERE status='deleted'").fetchall()
    deleted = any(matching.match_score(p, r)[0] >= 0.8 for r in e)
    sigs["electoral_deletion"] = (deleted, None, None)

    b = conn.execute(
        "SELECT * FROM bank_activity WHERE pensioner_id=?", (p["pensioner_id"],)).fetchone()
    sigs["bank_inactivity"] = (bool(b and float(b["months_inactive"] or 0) >= bank_months),
                               b["months_inactive"] if b else None, None)

    lc = conn.execute(
        "SELECT MAX(cert_date) AS last FROM life_certs WHERE pensioner_id=?",
        (p["pensioner_id"],)).fetchone()
    last_cert = _parse_date(lc["last"]) if lc and lc["last"] else _parse_date(p["last_life_cert_date"])
    overdue = (today - last_cert).days > overdue_days if last_cert else True
    sigs["life_cert_overdue"] = (overdue, (today - last_cert).days if last_cert else None, None)

    dob = _parse_date(p["dob"])
    age = (today - dob).days / 365.25 if dob else 0
    sigs["age_over_90"] = (age >= old_age, round(age, 1) if dob else None, None)

    return sigs, m

def run_pipeline(conn, today=None):
    today = today or date.today()
    base_rate = float(db.get_setting(conn, "base_rate"))
    c_fh = float(db.get_setting(conn, "cost_false_hold"))
    c_md = float(db.get_setting(conn, "cost_missed_death"))
    p_star = scoring.cost_threshold(c_fh, c_md)
    wrows = {w["signal"]: (w["lr_plus"], w["lr_minus"]) for w in conn.execute("SELECT * FROM weights")}

    active = conn.execute("SELECT * FROM pensioners WHERE status='active'").fetchall()
    made = 0
    for p in active:
        sigs, match = _signals_for(conn, p, wrows, today)
        if not any(v[0] for v in sigs.values()):
            continue
        existing = conn.execute(
            "SELECT id, state FROM cases WHERE pensioner_id=? AND state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION','HELD')",
            (p["pensioner_id"],)).fetchone()
        flat, conf = [], None
        for name, (present, value, m) in sigs.items():
            lp, lm = wrows[name]
            flat.append((name, present, lp, lm))
            if name == "death_registry_match" and present:
                conf = value
        lo, prob, contrib = scoring.score_case(base_rate, flat, conf)
        priority = 1 if prob >= p_star else 0
        if existing:
            # Rescore open cases on every run so rankings reflect the latest
            # feeds; held cases keep their state but still get fresh scores.
            cid = existing["id"]
            conn.execute(
                "UPDATE cases SET base_rate=?, log_odds=?, probability=?, priority=?, matched_death_id=? WHERE id=?",
                (base_rate, lo, prob, priority, match["death_id"] if match else None, cid))
            conn.execute("DELETE FROM signals WHERE case_id=?", (cid,))
            for (name, present, d) in contrib:
                lp, lm = wrows[name]
                conn.execute("INSERT INTO signals(case_id,signal,present,value,lr_plus,lr_minus) VALUES(?,?,?,?,?,?)",
                             (cid, name, int(present), str(d), lp, lm))
            continue
        cur = conn.execute(
            "INSERT INTO cases(pensioner_id,created_at,base_rate,log_odds,probability,priority,state,matched_death_id) "
            "VALUES(?,?,?,?,?,?, 'FLAGGED', ?)",
            (p["pensioner_id"], datetime.utcnow().isoformat(timespec="seconds") + "Z",
             base_rate, lo, prob, priority, match["death_id"] if match else None))
        cid = cur.lastrowid
        for (name, present, d) in contrib:
            lp, lm = wrows[name]
            conn.execute("INSERT INTO signals(case_id,signal,present,value,lr_plus,lr_minus) VALUES(?,?,?,?,?,?)",
                         (cid, name, int(present), str(d), lp, lm))
        for step in VERIFICATION_STEPS:
            conn.execute("INSERT INTO verifications(case_id,step) VALUES(?,?)", (cid, step))
        made += 1
    conn.commit()
    db.log(conn, "pipeline", "flag_run", f"new_cases={made} threshold={p_star:.3f}")
    return made, p_star
