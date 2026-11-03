"""Flag pipeline: blocked identity matching, per-signal likelihood-ratio
scoring with temporal consistency, activity-cliff detection, cost-based
priority. Produces ranked review cases only. No auto-hold."""
import math, difflib
from datetime import datetime, date
from . import db, matching, scoring

VERIFICATION_STEPS = [
    "Cross-check registrar record against the matched death entry",
    "Field verification visit to the pensioner's address",
    "Contact family or nominee on record",
    "Confirm account activity with the pension-paying bank branch",
]

def _pd(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def _norm(x):
    return " ".join((x or "").lower().split())

def _year_of(s):
    d = _pd(s)
    if d:
        return d.year
    s = (s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    if len(s) >= 4 and s[-4:].isdigit():
        return int(s[-4:])
    return None

def cliff_info(month_counts, snap):
    """(cliff_month, months_since) for a sustained stop after regular activity."""
    if not month_counts:
        return None, None
    keys = sorted(month_counts)
    snap_key = snap.year * 100 + snap.month
    active = [k for k in keys if month_counts[k] > 0]
    if not active:
        return None, None
    last_active = active[-1]
    if last_active >= snap_key - 1:
        return None, None
    if len([k for k in active if k < last_active]) < 3:
        return None, None
    cmonth = date(last_active // 100, last_active % 100, 1)
    m_since = (snap.year - cmonth.year) * 12 + (snap.month - cmonth.month) - 1
    return cmonth, m_since

class Feeds:
    def __init__(self, conn, snap):
        self.snap = snap
        q = lambda sql, p=(): conn.execute(sql, p).fetchall()
        self.deaths = q("SELECT * FROM death_registry")
        self.hosp_dead = q("SELECT * FROM hospital_records WHERE UPPER(outcome)='DIED'")
        self.eroll_del = q("SELECT * FROM electoral_roll WHERE UPPER(status)='DELETED'")
        self.pm = q("SELECT * FROM pension_master")
        self.last_credit = self._latest(q("SELECT pensioner_id, credit_date FROM pension_disbursements"),
                                        "pensioner_id", "credit_date")
        self.last_cert = {}
        for r in q("SELECT pensioner_id, submission_date, status FROM life_certificates"):
            if (r["status"] or "").upper() in ("", "VERIFIED", "ACCEPTED", "SUCCESS", "SUBMITTED"):
                self._maxd(self.last_cert, r["pensioner_id"], r["submission_date"])
        self.bank_month, self.last_bank = {}, {}
        for r in q("SELECT account_number, txn_date FROM bank_transactions"):
            d = _pd(r["txn_date"])
            if not d:
                continue
            a = r["account_number"]
            k = d.year * 100 + d.month
            bm = self.bank_month.setdefault(a, {})
            bm[k] = bm.get(k, 0) + 1
            self._maxd(self.last_bank, a, r["txn_date"])
        self.tele_month, self.last_tele = {}, {}
        for r in q("SELECT mobile, month, calls_made, sms_sent, data_mb, last_activity_date FROM telecom_activity"):
            act = sum(float(r[k] or 0) for k in ("calls_made", "sms_sent", "data_mb"))
            m = _pd(r["month"])
            if m:
                tm = self.tele_month.setdefault(r["mobile"], {})
                tm[m.year * 100 + m.month] = act
            if act > 0:
                self._maxd(self.last_tele, r["mobile"], r["last_activity_date"])
        self.pan_filed = {}
        for r in q("SELECT pan, itr_filed, filing_date FROM tax_pan_activity"):
            if (r["itr_filed"] or "").strip().upper() in ("Y", "YES", "1", "TRUE"):
                self._maxd(self.pan_filed, r["pan"], r["filing_date"])
        # utility collapsed to one row per consumer, latest paid date
        cons = {}
        for u in q("SELECT consumer_id, consumer_name, service_address, bill_paid_date FROM utility_bills"):
            d = _pd(u["bill_paid_date"])
            cur = cons.get(u["consumer_id"])
            if cur is None or (d and (cur[2] is None or d > cur[2])):
                cons[u["consumer_id"]] = [u["consumer_name"], _norm(u["service_address"]), d if cur is None else (d or cur[2])]
        self.cons = list(cons.values())
        self.cons_toks = [frozenset(matching.normalize_name(c[0]).split()) for c in self.cons]
        self.util_tok = {}
        for i, tk in enumerate(self.cons_toks):
            for t in tk:
                self.util_tok.setdefault(t, []).append(i)
        self._prepped = {}
        for label, rows, nf in (("death", self.deaths, "deceased_name"),
                                ("hosp", self.hosp_dead, "patient_name"),
                                ("eroll", self.eroll_del, "name")):
            prepped = []
            for r in rows:
                toks = frozenset(matching.normalize_name(r[nf]).split())
                sx = frozenset(matching.soundex(t) for t in toks if len(t) >= 4)
                prepped.append((r, toks, sx, (r["gender"] or "").strip().lower()[:1], _year_of(r["dob"])))
            self._prepped[label] = prepped

    def _maxd(self, d, k, ds):
        dt = _pd(ds)
        if dt and (k not in d or dt > d[k]):
            d[k] = dt

    def _latest(self, rows, kcol, dcol):
        out = {}
        for r in rows:
            self._maxd(out, r[kcol], r[dcol])
        return out

    def months(self, d):
        return (self.snap - d).days / 30.44 if d else None

    def scan(self, p, label, namefield, addrfield=None):
        ptoks = frozenset(matching.normalize_name(p["full_name"]).split())
        psx = frozenset(matching.soundex(t) for t in ptoks if len(t) >= 4)
        pg = (p["gender"] or "").strip().lower()[:1]
        py = _year_of(p["dob"])
        best, best_r = 0.0, None
        pa = {"name": p["full_name"], "gender": p["gender"], "dob": p["dob"]}
        for r, toks, sx, g, y in self._prepped[label]:
            if g != pg:
                continue
            inter = len(ptoks & toks)
            if inter == 0 and not (psx & sx):
                continue
            if py and y and abs(py - y) > 2 and inter < len(ptoks):
                continue
            s, nm, gok, dobm = matching.match_score(pa, {
                "name": r[namefield], "gender": r["gender"], "dob": r["dob"]})
            if addrfield and s > 0:
                ar = difflib.SequenceMatcher(None, _norm(p["address"]), _norm(r[addrfield])).ratio()
                s = round(0.8 * s + 0.2 * ar, 4)
            if s > best:
                best, best_r = s, r
        return best, best_r

def run_pipeline(conn, today=None, snapshot=None):
    snap = snapshot or today or date.today()
    base_rate = float(db.get_setting(conn, "base_rate"))
    p_star = scoring.cost_threshold(float(db.get_setting(conn, "cost_false_hold")),
                                    float(db.get_setting(conn, "cost_missed_death")))
    match_t = float(db.get_setting(conn, "match_threshold"))
    w = {r["signal"]: (r["lr_plus"], r["lr_minus"]) for r in conn.execute("SELECT * FROM weights")}
    F = Feeds(conn, snap)

    # one-to-one death-registry assignment: aadhaar links win, fuzzy by confidence
    pm_aad = {(p["aadhaar_number"] or "").strip(): p["pensioner_id"] for p in F.pm if (p["aadhaar_number"] or "").strip()}
    reg_owner = {}
    for d in F.deaths:
        da = (d["aadhaar_number"] or "").strip()
        if da and da in pm_aad:
            reg_owner[d["registration_no"]] = pm_aad[da]
    cands = []
    for p in F.pm:
        conf, dm = F.scan(p, "death", "deceased_name")
        if dm and conf >= match_t:
            cands.append((conf, p["pensioner_id"], dm["registration_no"], dm["date_of_death"]))
    cands.sort(reverse=True)
    assigned = {}
    for conf, pid, reg, dod in cands:
        if reg in reg_owner or pid in assigned:
            continue
        reg_owner[reg] = pid
        assigned[pid] = (conf, reg, dod)

    made = 0
    for p in F.pm:
        pid = p["pensioner_id"]
        lo = scoring.logit(base_rate)
        contrib = []
        death_dates = []

        if pid in assigned:
            conf, reg, dod = assigned[pid]
            lp, lm = w["death_registry_match"]
            contrib.append(("death_registry_match", 1, round(math.log(lm ** (1 - conf) * lp ** conf), 4)))
            dd = _pd(dod)
            if dd:
                death_dates.append(dd)

        hs, hr = F.scan(p, "hosp", "patient_name")
        if hs >= match_t:
            lp, lm = w["hospital_died_match"]
            contrib.append(("hospital_died_match", 1, round(math.log(lm ** (1 - hs) * lp ** hs), 4)))
            hd = _pd(hr["discharge_date"]) or _pd(hr["admit_date"])
            if hd:
                death_dates.append(hd)

        es, er = F.scan(p, "eroll", "name", addrfield="address")
        if es >= match_t:
            lp, lm = w["electoral_deletion"]
            contrib.append(("electoral_deletion", 1, round(math.log(lm ** (1 - es) * lp ** es), 4)))
            ed = _pd(er["deletion_date"])
            if ed:
                death_dates.append(ed)

        bc, bc_m = cliff_info(F.bank_month.get(p["bank_account"], {}), snap)
        tc, tc_m = cliff_info(F.tele_month.get(p["mobile"], {}), snap)
        if bc_m is not None:
            contrib.append(("bank_cliff", 1, round(math.log(4.5 if bc_m <= 3 else 2.2), 4)))
        if tc_m is not None:
            contrib.append(("telecom_cliff", 1, round(math.log(4.0 if tc_m <= 3 else 2.0), 4)))
        if bc and tc and abs((bc.year * 12 + bc.month) - (tc.year * 12 + tc.month)) <= 1:
            contrib.append(("aligned_cliff", 1, round(math.log(2.5), 4)))
        if (bc or tc) and not death_dates:
            death_dates = [max(c for c in (bc, tc) if c)]

        ddate = min(death_dates) if death_dates else None
        def after(d):
            return ddate is None or (d is not None and d > ddate)

        lc_d = F.last_cert.get(pid)
        m_cert = F.months(lc_d)
        if ddate and lc_d and lc_d > ddate:
            contrib.append(("life_cert_overdue", 0, round(math.log(0.1), 4)))
        elif m_cert is None or m_cert > 12:
            contrib.append(("life_cert_overdue", 1, round(math.log(w["life_cert_overdue"][0]), 4)))
        elif not ddate:
            contrib.append(("life_cert_overdue", 0, round(math.log(w["life_cert_overdue"][1]), 4)))

        bk = F.last_bank.get(p["bank_account"])
        m_bank = F.months(bk)
        if m_bank is None or m_bank >= 6:
            contrib.append(("bank_inactivity", 1, round(math.log(w["bank_inactivity"][0]), 4)))
        elif after(bk):
            contrib.append(("bank_inactivity", 0, round(math.log(0.85 if ddate and bc is None else w["bank_inactivity"][1]), 4)))

        tl = F.last_tele.get(p["mobile"])
        m_tel = F.months(tl)
        if m_tel is None or m_tel >= 3:
            contrib.append(("telecom_quiet", 1, round(math.log(w["telecom_quiet"][0]), 4)))
        elif after(tl):
            contrib.append(("telecom_quiet", 0, round(math.log(0.9 if ddate and tc is None else w["telecom_quiet"][1]), 4)))

        pf = F.pan_filed.get(p["pan"])
        if pf and F.months(pf) <= 24 and after(pf):
            contrib.append(("alive_itr", 0, round(math.log(0.6 if ddate else w["alive_itr"][1]), 4)))

        if not ddate:
            ptoks = frozenset(matching.normalize_name(p["full_name"]).split())
            hits = {}
            for t in ptoks:
                for ci in F.util_tok.get(t, ()):
                    hits[ci] = hits.get(ci, 0) + 1
            paddr = _norm(p["address"])
            for ci, ov in hits.items():
                if ov < min(len(ptoks), len(F.cons_toks[ci])):
                    continue
                cname, caddr, cpaid = F.cons[ci]
                if matching.name_match_pct(p["full_name"], cname) >= 0.8 and \
                   difflib.SequenceMatcher(None, paddr, caddr).ratio() >= 0.6 and \
                   cpaid and F.months(cpaid) <= 3:
                    contrib.append(("alive_utility", 0, round(math.log(w["alive_utility"][1]), 4)))
                    break

        if not contrib or not any(c[1] for c in contrib):
            continue
        for _, _, d in contrib:
            lo += d
        prob = round(scoring.sigmoid(lo), 4)
        credit = F.last_credit.get(pid)
        still_paid = credit is not None and F.months(credit) <= 3
        score = prob if still_paid else round(prob * 0.05, 6)
        priority = 1 if score >= p_star else 0
        reg = assigned.get(pid, (None, None, None))[1]

        existing = conn.execute(
            "SELECT id FROM cases WHERE pensioner_id=? AND state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION','HELD')",
            (pid,)).fetchone()
        if existing:
            cid = existing["id"]
            conn.execute("UPDATE cases SET base_rate=?, log_odds=?, probability=?, priority=?, matched_death_id=? WHERE id=?",
                         (base_rate, round(lo, 4), score, priority, reg, cid))
            conn.execute("DELETE FROM signals WHERE case_id=?", (cid,))
        else:
            cur = conn.execute(
                "INSERT INTO cases(pensioner_id,created_at,base_rate,log_odds,probability,priority,state,matched_death_id) "
                "VALUES(?,?,?,?,?,?,'FLAGGED',?)",
                (pid, datetime.utcnow().isoformat(timespec="seconds") + "Z",
                 base_rate, round(lo, 4), score, priority, reg))
            cid = cur.lastrowid
            for step in VERIFICATION_STEPS:
                conn.execute("INSERT INTO verifications(case_id,step) VALUES(?,?)", (cid, step))
            made += 1
        for name, present, d in contrib:
            lp, lm = w.get(name, (1.0, 1.0))
            conn.execute("INSERT INTO signals(case_id,signal,present,value,lr_plus,lr_minus) VALUES(?,?,?,?,?,?)",
                         (cid, name, present, str(d), lp, lm))
    conn.commit()
    db.log(conn, "pipeline", "flag_run", f"new_cases={made} threshold={p_star:.3f}")
    return made, p_star
