"""Flag pipeline: blocked identity matching (inverted index over exact and
soundex name tokens, typo-tolerant DoB), one-to-one record assignment on every
documentary feed, per-signal likelihood-ratio scoring with temporal
consistency, activity-cessation detection, hardship caps, cost-based priority.
Produces ranked review cases only. No auto-hold."""
import math, difflib
from datetime import datetime, date
from . import db, matching, scoring

VERIFICATION_STEPS = [
    "Cross-check registrar record against the matched death entry",
    "Field verification visit to the pensioner's address",
    "Contact family or nominee on record",
    "Confirm account activity with the pension-paying bank branch",
]

# Likelihood-ratio constants (judgment-calibrated; see README methodology).
LR_REG_STRONG_HI, LR_REG_STRONG_LO = 40.0, 0.5
LR_REG_EXACT = 60.0
LR_REG_WEAK = 2.5
LR_HOSP_HI, LR_HOSP_LO = 30.0, 0.6
LR_HOSP_WEAK = 2.0
LR_EROLL_HI, LR_EROLL_LO = 5.0, 0.7
LR_CLIFF_RECENT, LR_CLIFF_MID, LR_CLIFF_OLD = 25.0, 15.0, 8.0
LR_CLIFF_WEAK = 5.0
LR_PARTIAL_QUIET_BANK, LR_PARTIAL_QUIET_TELE = 1.1, 2.0
LR_ALIGNED = 1.8
LR_CHRONIC_BANK, LR_CHRONIC_TELE = 1.15, 1.1
LR_DLC_MISSING, LR_DLC_MISSING_CESSATION = 5.0, 3.0
LR_DLC_AFTER_DEATH = 0.12
LR_DLC_PRESENT = 0.55
LR_REUSE_BANK, LR_REUSE_SIM, LR_LEAKAGE_CREDIT = 1.4, 1.3, 1.6
LR_DOUBT_BANK, LR_DOUBT_SIM, LR_DOUBT_BOTH, LR_DOUBT_CREDIT = 0.85, 0.9, 0.6, 1.15
LR_ALIVE_BANK, LR_ALIVE_TELE, LR_ALIVE_PAN, LR_ALIVE_UTIL = 0.5, 0.55, 0.6, 0.75
LR_PAN_AFTER_DEATH = 0.8
LR_RESUME = 0.8
CAP_SILENCE, CAP_WEAK, CAP_WEAK_ALIGNED = 0.45, 0.55, 0.70
STRONG_T, WEAK_T = 0.9, 0.8

def _pd(s):
    s = (s or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        except ValueError:
            return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def _norm(x):
    return " ".join((x or "").lower().split())

def _ymd(s):
    d = _pd(s)
    return (d.year, d.month, d.day) if d else None

def _dob_pts(a, b):
    """Typo-tolerant DoB agreement in [0,1]: exact 1.0, day typo or day/month
    swap 0.85, year off by one 0.75, one year-digit edit 0.6, same year 0.5."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ya, ma, da = a; yb, mb, db = b
    if ya == yb and ma == mb:
        return 0.85
    if ya == yb and da == mb and ma == db:
        return 0.85
    if ma == mb and da == db and abs(ya - yb) <= 1:
        return 0.75
    if ma == mb and da == db and sum(1 for x, y in zip(str(ya), str(yb)) if x != y) == 1:
        return 0.6
    if ya == yb:
        return 0.5
    return 0.0

def cessation(month_counts, snap):
    """Classify a monthly activity series.
    Returns (kind, cessation_month, months_since, prior_active_months) with
    kind in active|partial_quiet|stop|stop_weak|quiet|chronic."""
    snap_key = snap.year * 100 + snap.month
    active = sorted(k for k, v in (month_counts or {}).items() if v > 0)
    if not active:
        return ("chronic", None, None, 0)
    last = active[-1]
    if last >= snap_key:
        return ("active", None, None, len(active) - 1)
    prior = len([k for k in active if k < last])
    y, m = last // 100, last % 100
    cmonth = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    m_since = (snap.year - y) * 12 + (snap.month - m) - 1
    if m_since <= 0 and snap.day <= 7 and prior >= 1:
        return ("partial_quiet", cmonth, 1, prior)
    if prior >= 2 and m_since <= 12:
        return ("stop", cmonth, m_since, prior)
    if prior >= 1 and m_since <= 3:
        return ("stop_weak", cmonth, m_since, prior)
    if m_since > 12:
        return ("chronic", None, None, 0)
    return ("quiet", None, m_since, prior)

class Feeds:
    """Aggregates every feed to per-key structures plus blocked match indexes.
    Pensioner rows are paged from SQLite; aggregate maps are per-key and small."""
    CHUNK = 20000

    def __init__(self, conn, snap):
        self.conn = conn
        self.snap = snap
        q = lambda sql, p=(): conn.execute(sql, p).fetchall()
        self.deaths = q("SELECT rowid AS _rid, * FROM death_registry")
        self.hosp_dead = q("SELECT rowid AS _hid, * FROM hospital_records WHERE UPPER(outcome)='DIED'")
        self.eroll_del = q("SELECT * FROM electoral_roll WHERE UPPER(status)='DELETED'")
        self.pm_count = conn.execute("SELECT COUNT(*) n FROM pension_master").fetchone()["n"]

        self.last_credit = self._latest(q("SELECT pensioner_id, credit_date FROM pension_disbursements"),
                                        "pensioner_id", "credit_date")
        self.disb_months = {}
        for r in q("SELECT pensioner_id, month FROM pension_disbursements"):
            m = (r["month"] or "").strip()
            if len(m) >= 7 and m[:4].isdigit():
                self.disb_months.setdefault(r["pensioner_id"], set()).add(int(m[:4]) * 100 + int(m[5:7]))
        self.last_cert = {}
        for r in q("SELECT pensioner_id, submission_date, status FROM life_certificates"):
            if (r["status"] or "").upper() in ("", "VERIFIED", "ACCEPTED", "SUCCESS", "SUBMITTED"):
                self._maxd(self.last_cert, r["pensioner_id"], r["submission_date"])
        self.bank_month, self.bank_dates, self.last_bank = {}, {}, {}
        for r in q("SELECT account_number, txn_date FROM bank_transactions"):
            d = _pd(r["txn_date"])
            if not d:
                continue
            a = r["account_number"]
            k = d.year * 100 + d.month
            bm = self.bank_month.setdefault(a, {})
            bm[k] = bm.get(k, 0) + 1
            bd = self.bank_dates.setdefault(a, [])
            if len(bd) < 400:
                bd.append(d)
            self._maxd(self.last_bank, a, r["txn_date"])
        self.tele_month, self.last_tele = {}, {}
        for r in q("SELECT mobile, month, calls_made, sms_sent, data_mb, last_activity_date FROM telecom_activity"):
            act = sum(float(r[k] or 0) for k in ("calls_made", "sms_sent", "data_mb"))
            m = (r["month"] or "").strip()
            if len(m) >= 7 and m[:4].isdigit():
                self.tele_month.setdefault(r["mobile"], {})[int(m[:4]) * 100 + int(m[5:7])] = act
            if act > 0:
                self._maxd(self.last_tele, r["mobile"], r["last_activity_date"])
        self.pan_filed = {}
        for r in q("SELECT pan, itr_filed, filing_date FROM tax_pan_activity"):
            if (r["itr_filed"] or "").strip().upper() in ("Y", "YES", "1", "TRUE"):
                self._maxd(self.pan_filed, r["pan"], r["filing_date"])
        cons = {}
        for u in q("SELECT consumer_id, consumer_name, service_address, bill_paid_date FROM utility_bills"):
            d = _pd(u["bill_paid_date"])
            cur = cons.get(u["consumer_id"])
            if cur is None or (d and (cur[2] is None or d > cur[2])):
                cons[u["consumer_id"]] = [u["consumer_name"], _norm(u["service_address"]),
                                          d if cur is None else (d or cur[2])]
        self.cons = list(cons.values())
        self.cons_toks = [frozenset(matching.normalize_name(c[0]).split()) for c in self.cons]
        self.util_tok = {}
        for i, tk in enumerate(self.cons_toks):
            for t in tk:
                self.util_tok.setdefault(t, []).append(i)
        self._prepped, self._index = {}, {}
        for label, rows, nf in (("death", self.deaths, "deceased_name"),
                                ("hosp", self.hosp_dead, "patient_name"),
                                ("eroll", self.eroll_del, "name")):
            prepped = []
            for i, r in enumerate(rows):
                toks = frozenset(matching.normalize_name(r[nf]).split())
                sx = frozenset(matching.soundex(t) for t in toks if len(t) >= 4)
                prepped.append((i, r, toks, sx, (r["gender"] or "").strip().lower()[:1], _ymd(r["dob"])))
            self._prepped[label] = prepped
            idx = {}
            for i, r, toks, sx, g, dob in prepped:
                for t in toks:
                    idx.setdefault(("t", t), []).append(i)
                for s in sx:
                    idx.setdefault(("s", s), []).append(i)
            self._index[label] = idx

    def pm_page(self, offset):
        return self.conn.execute("SELECT * FROM pension_master ORDER BY pensioner_id LIMIT ? OFFSET ?",
                                 (self.CHUNK, offset)).fetchall()

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
        """Best candidate via inverted index (exact + soundex token union),
        DoB-first rejection, 0.62*name + 0.38*DoB score."""
        ptoks = frozenset(matching.normalize_name(p["full_name"]).split())
        psx = frozenset(matching.soundex(t) for t in ptoks if len(t) >= 4)
        pg = (p["gender"] or "").strip().lower()[:1]
        pdob = _ymd(p["dob"])
        cand = set()
        idx = self._index[label]
        for t in ptoks:
            cand.update(idx.get(("t", t), ()))
        for s in psx:
            cand.update(idx.get(("s", s), ()))
        best, best_r = 0.0, None
        paddr = _norm(p["address"])
        for i in cand:
            _, r, toks, sx, g, rdob = self._prepped[label][i]
            if g != pg:
                continue
            if not (ptoks & toks) and not (psx & sx):
                continue
            dp = _dob_pts(pdob, rdob)
            if dp == 0.0:
                continue
            nm = matching.name_match_pct(p["full_name"], r[namefield])
            if nm < 0.55:
                continue
            s = 0.62 * nm + 0.38 * dp
            if addrfield and s > 0:
                ar = difflib.SequenceMatcher(None, paddr, _norm(r[addrfield])).ratio()
                s = 0.8 * s + 0.2 * ar
            if s > best:
                best, best_r = round(s, 4), r
        return best, best_r

def _lr_interp(conf, lo_lr, hi_lr):
    return lo_lr ** (1 - conf) * hi_lr ** conf

def _assign(pm_rows, scan_args, id_of, aadhaar_rows=None, aadhaar_key=None, min_conf=WEAK_T):
    """One-to-one assignment: aadhaar links pre-claim, then fuzzy by confidence."""
    owner = {}
    if aadhaar_rows is not None:
        pm_aad = {(p["aadhaar_number"] or "").strip(): p["pensioner_id"]
                  for p in pm_rows if (p["aadhaar_number"] or "").strip()}
        for d in aadhaar_rows:
            da = (d["aadhaar_number"] or "").strip()
            if da and da in pm_aad:
                owner[d[aadhaar_key]] = ("exact", pm_aad[da], 1.0)
    cands = []
    for p in pm_rows:
        conf, row = scan_args(p)
        if row is not None and conf >= min_conf:
            cands.append((conf, p["pensioner_id"], id_of(row)))
    cands.sort(reverse=True)
    claimed_pids = {v[1] for v in owner.values()}
    for conf, pid, rid in cands:
        if rid in owner or pid in claimed_pids:
            continue
        owner[rid] = ("strong" if conf >= STRONG_T else "weak", pid, conf)
        claimed_pids.add(pid)
    by_pid = {}
    for rid, (g, pid, conf) in owner.items():
        by_pid[pid] = (g, conf, rid)
    return by_pid

def run_pipeline(conn, today=None, snapshot=None, rng=None):
    import random
    rng = rng or random.SystemRandom()
    snap = snapshot or today or date.today()
    base_rate = float(db.get_setting(conn, "base_rate"))
    p_star = scoring.cost_threshold(float(db.get_setting(conn, "cost_false_hold")),
                                    float(db.get_setting(conn, "cost_missed_death")))
    w = {r["signal"]: (r["lr_plus"], r["lr_minus"]) for r in conn.execute("SELECT * FROM weights")}
    F = Feeds(conn, snap)

    # scan every pensioner once per feed, paged; then one-to-one assignment
    death_scan, hosp_scan, eroll_scan = {}, {}, {}
    all_pm = []
    off = 0
    while True:
        page = F.pm_page(off)
        if not page:
            break
        all_pm.extend(page)
        for p in page:
            death_scan[p["pensioner_id"]] = F.scan(p, "death", "deceased_name")
            hosp_scan[p["pensioner_id"]] = F.scan(p, "hosp", "patient_name")
            eroll_scan[p["pensioner_id"]] = F.scan(p, "eroll", "name", addrfield="address")
        off += F.CHUNK

    reg_by_pid = _assign(all_pm, lambda p: death_scan[p["pensioner_id"]],
                         lambda r: r["registration_no"],
                         aadhaar_rows=F.deaths, aadhaar_key="registration_no")
    hosp_by_pid = _assign(all_pm, lambda p: hosp_scan[p["pensioner_id"]], lambda r: r["_hid"])
    eroll_by_pid = _assign(all_pm, lambda p: eroll_scan[p["pensioner_id"]],
                           lambda r: r["epic_number"], min_conf=STRONG_T)
    reg_rows = {r["registration_no"]: r for r in F.deaths}
    hosp_rows = {r["_hid"]: r for r in F.hosp_dead}
    eroll_rows = {r["epic_number"]: r for r in F.eroll_del}

    made = 0
    case_cap = int(db.get_setting(conn, "max_new_cases_per_run") or 500)
    breaker = False
    flagged_pids = set()
    for p in all_pm:
        pid = p["pensioner_id"]
        lo = scoring.logit(base_rate)
        contrib = []
        death_dates = []   # (date, grade)
        doc_grades = []

        if pid in reg_by_pid:
            g, conf, rid = reg_by_pid[pid]
            if g == "exact":
                contrib.append(("death_registry_match", 1, round(math.log(LR_REG_EXACT), 4)))
            elif g == "strong":
                contrib.append(("death_registry_match", 1,
                                round(math.log(_lr_interp(conf, LR_REG_STRONG_LO, LR_REG_STRONG_HI)), 4)))
            else:
                contrib.append(("weak_lead_registry", 1, round(math.log(LR_REG_WEAK), 4)))
            doc_grades.append(g)
            dd = _pd(reg_rows[rid]["date_of_death"])
            if dd:
                death_dates.append((dd, g))
        if pid in hosp_by_pid:
            g, conf, hid = hosp_by_pid[pid]
            hr = hosp_rows[hid]
            if g == "strong":
                contrib.append(("hospital_died_match", 1,
                                round(math.log(_lr_interp(conf, LR_HOSP_LO, LR_HOSP_HI)), 4)))
            else:
                contrib.append(("weak_lead_hospital", 1, round(math.log(LR_HOSP_WEAK), 4)))
            doc_grades.append(g)
            hd = _pd(hr["discharge_date"]) or _pd(hr["admit_date"])
            if hd:
                death_dates.append((hd, g))
        if pid in eroll_by_pid:
            g, conf, eid = eroll_by_pid[pid]
            ed = _pd(eroll_rows[eid]["deletion_date"])
            if ed is None or ed <= snap:
                contrib.append(("electoral_deletion", 1,
                                round(math.log(_lr_interp(conf, LR_EROLL_LO, LR_EROLL_HI)), 4)))
                doc_grades.append("strong")
                if ed:
                    death_dates.append((ed, "strong"))

        # cessation analysis per feed
        bk, bk_cm, bk_ms, _ = cessation(F.bank_month.get(p["bank_account"], {}), snap)
        tk, tk_cm, tk_ms, _ = cessation(F.tele_month.get(p["mobile"], {}), snap)
        bank_stop = tele_stop = None
        if bk == "stop":
            bank_stop = bk_cm
            lr = LR_CLIFF_RECENT if bk_ms <= 3 else (LR_CLIFF_MID if bk_ms <= 6 else LR_CLIFF_OLD)
            contrib.append(("bank_cliff", 1, round(math.log(lr), 4)))
        elif bk == "stop_weak":
            bank_stop = bk_cm
            contrib.append(("bank_cliff", 1, round(math.log(LR_CLIFF_WEAK), 4)))
        elif bk == "partial_quiet":
            contrib.append(("bank_inactivity", 1, round(math.log(LR_PARTIAL_QUIET_BANK), 4)))
        elif bk == "chronic":
            contrib.append(("bank_inactivity", 1, round(math.log(LR_CHRONIC_BANK), 4)))
        if tk == "stop":
            tele_stop = tk_cm
            lr = LR_CLIFF_RECENT if tk_ms <= 3 else (LR_CLIFF_MID if tk_ms <= 6 else LR_CLIFF_OLD)
            contrib.append(("telecom_cliff", 1, round(math.log(lr), 4)))
        elif tk == "stop_weak":
            tele_stop = tk_cm
            contrib.append(("telecom_cliff", 1, round(math.log(LR_CLIFF_WEAK), 4)))
        elif tk == "partial_quiet":
            contrib.append(("telecom_quiet", 1, round(math.log(LR_PARTIAL_QUIET_TELE), 4)))
        elif tk == "chronic":
            contrib.append(("telecom_quiet", 1, round(math.log(LR_CHRONIC_TELE), 4)))
        if bank_stop and tele_stop and abs((bank_stop.year * 12 + bank_stop.month)
                                           - (tele_stop.year * 12 + tele_stop.month)) <= 1:
            contrib.append(("aligned_cliff", 1, round(math.log(LR_ALIGNED), 4)))

        dd_pool = [d for d, g in death_dates]
        for c in (bank_stop, tele_stop):
            if c:
                dd_pool.append(c)
        ddate = min(dd_pool) if dd_pool else None
        exact_death = any(g == "exact" for _, g in death_dates)

        # life certificate
        lc_d = F.last_cert.get(pid)
        if lc_d and ddate and lc_d > ddate:
            contrib.append(("dlc_after_death", 0, round(math.log(LR_DLC_AFTER_DEATH), 4)))
        elif lc_d is None:
            contrib.append(("life_cert_overdue", 1, round(math.log(
                LR_DLC_MISSING_CESSATION if (bank_stop or tele_stop) else LR_DLC_MISSING), 4)))
        elif F.months(lc_d) > 12:
            contrib.append(("life_cert_overdue", 1, round(math.log(
                LR_DLC_MISSING_CESSATION if (bank_stop or tele_stop) else LR_DLC_MISSING), 4)))
        elif not ddate:
            contrib.append(("life_cert_overdue", 0, round(math.log(LR_DLC_PRESENT), 4)))

        # post-death-date activity: corroboration when the death is aadhaar-exact
        # (family reuse), doubt when the match is fuzzy
        bdates = F.bank_dates.get(p["bank_account"], [])
        bank_after = bool(ddate) and any(d > ddate for d in bdates)
        tl = F.last_tele.get(p["mobile"])
        tele_after = bool(ddate and tl and tl > ddate)
        if ddate:
            if exact_death:
                if bank_after:
                    contrib.append(("family_reuse_bank", 1, round(math.log(LR_REUSE_BANK), 4)))
                if tele_after:
                    contrib.append(("family_reuse_sim", 1, round(math.log(LR_REUSE_SIM), 4)))
            else:
                if bank_after and tele_after:
                    contrib.append(("family_reuse_bank", 0, round(math.log(LR_DOUBT_BOTH), 4)))
                elif bank_after:
                    contrib.append(("family_reuse_bank", 0, round(math.log(LR_DOUBT_BANK), 4)))
                elif tele_after:
                    contrib.append(("family_reuse_sim", 0, round(math.log(LR_DOUBT_SIM), 4)))
            dm = F.disb_months.get(pid, set())
            dkey = ddate.year * 100 + ddate.month
            if any(k > dkey for k in dm):
                contrib.append(("leakage_credit", 1, round(math.log(
                    LR_LEAKAGE_CREDIT if exact_death else LR_DOUBT_CREDIT), 4)))
            pf = F.pan_filed.get(p["pan"])
            if pf and pf > ddate:
                contrib.append(("alive_itr", 0, round(math.log(LR_PAN_AFTER_DEATH), 4)))
        else:
            bk_d = F.last_bank.get(p["bank_account"])
            if bk_d and F.months(bk_d) <= 2:
                contrib.append(("bank_inactivity", 0, round(math.log(LR_ALIVE_BANK), 4)))
            if tl and F.months(tl) <= 1.2:
                contrib.append(("telecom_quiet", 0, round(math.log(LR_ALIVE_TELE), 4)))
            pf = F.pan_filed.get(p["pan"])
            if pf and F.months(pf) <= 24:
                contrib.append(("alive_itr", 0, round(math.log(LR_ALIVE_PAN), 4)))
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
                if (matching.name_match_pct(p["full_name"], cname) >= 0.8
                        and difflib.SequenceMatcher(None, paddr, caddr).ratio() >= 0.6
                        and cpaid and F.months(cpaid) <= 2):
                    contrib.append(("alive_utility", 0, round(math.log(LR_ALIVE_UTIL), 4)))
                    break

        if not contrib or not any(c[1] for c in contrib):
            continue
        flagged_pids.add(pid)
        for _, _, d in contrib:
            lo += d
        prob = scoring.sigmoid(lo)

        # conviction guards: silence alone, or weak documentary leads alone, cap out
        has_cessation = bank_stop is not None or tele_stop is not None
        if not doc_grades and not has_cessation and prob > CAP_SILENCE:
            prob = CAP_SILENCE
            contrib.append(("silence_cap", 1, "cap: no documentary evidence, no cessation"))
        elif doc_grades and all(g == "weak" for g in doc_grades):
            aligned_to_weak = has_cessation and any(
                abs((min(c for c in (bank_stop, tele_stop) if c).year * 12
                     + min(c for c in (bank_stop, tele_stop) if c).month)
                    - (d.year * 12 + d.month)) <= 1 for d, g in death_dates if g == "weak")
            cap = CAP_WEAK_ALIGNED if aligned_to_weak else CAP_WEAK
            if prob > cap:
                prob = cap
                contrib.append(("weak_lead_cap", 1, f"cap {cap}: weak documentary lead only"))
        prob = round(prob, 4)

        credit = F.last_credit.get(pid)
        still_paid = credit is not None and F.months(credit) <= 3
        score = prob if still_paid else round(prob * 0.05, 6)
        priority = 1 if score >= p_star else 0
        reg = reg_by_pid.get(pid, (None, None, None))[2]

        existing = conn.execute(
            "SELECT id FROM cases WHERE pensioner_id=? AND state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION','HELD','HOLD_PENDING')",
            (pid,)).fetchone()
        if existing:
            cid = existing["id"]
            conn.execute("UPDATE cases SET base_rate=?, log_odds=?, probability=?, priority=?, matched_death_id=? WHERE id=?",
                         (base_rate, round(lo, 4), score, priority, reg, cid))
            conn.execute("DELETE FROM signals WHERE case_id=?", (cid,))
        else:
            if made >= case_cap:
                breaker = True
                continue
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
    # randomized audit sampling: a small random share of still-paid pensioners
    # with no flags goes into the queue as audit-sample cases. Their outcomes are
    # a random selection stream, still subject to adjudication bias; flagged-case resolutions are
    # selection-biased and must not calibrate the model alone.
    rate = float(db.get_setting(conn, "audit_sample_rate") or 0.0)
    sampled = 0
    if rate > 0:
        for p in all_pm:
            pid = p["pensioner_id"]
            if pid in flagged_pids:
                continue
            credit = F.last_credit.get(pid)
            if not (credit is not None and F.months(credit) <= 3):
                continue
            existing = conn.execute(
                "SELECT id FROM cases WHERE pensioner_id=? AND state IN "
                "('FLAGGED','UNDER_REVIEW','VERIFICATION','HELD','HOLD_PENDING')", (pid,)).fetchone()
            if existing:
                continue
            if rng.random() < rate:
                if made + sampled >= case_cap:
                    breaker = True
                    continue
                cur = conn.execute(
                    "INSERT INTO cases(pensioner_id,created_at,base_rate,log_odds,probability,priority,state,matched_death_id) "
                    "VALUES(?,?,?,?,?,0,'FLAGGED',NULL)",
                    (pid, datetime.utcnow().isoformat(timespec="seconds") + "Z",
                     base_rate, round(scoring.logit(base_rate), 4), round(base_rate, 4)))
                acid = cur.lastrowid
                conn.execute("INSERT INTO audit_samples(case_id,selected_at,inclusion_probability) VALUES(?,?,?)",
                             (acid, datetime.utcnow().isoformat(timespec="seconds") + "Z", rate))
                conn.execute("INSERT INTO signals(case_id,signal,present,value,lr_plus,lr_minus) VALUES(?,?,?,?,?,?)",
                             (acid, "audit_sample", 1, "random integrity audit sample", 1.0, 1.0))
                for step in VERIFICATION_STEPS:
                    conn.execute("INSERT INTO verifications(case_id,step) VALUES(?,?)", (acid, step))
                sampled += 1
    if breaker:
        db.log(conn, "pipeline", "circuit_breaker",
               f"case creation halted at cap={case_cap}; possible feed flooding - investigate before rerun")
    # drip-flood watch: a per-run cap alone misses slow flooding that stays
    # under the cap every run. Sum recent runs and warn on anomalous volume.
    import re
    watch = False
    recent = conn.execute(
        "SELECT detail FROM audit WHERE action='flag_run' ORDER BY id DESC LIMIT 10").fetchall()
    counts = [int(m.group(1)) for r in recent
              if (m := re.search(r"new_cases=(\d+)", r["detail"]))]
    window_total = made + sum(counts)
    if counts and window_total > 3 * case_cap:
        watch = True
        db.log(conn, "pipeline", "flood_watch",
               f"cumulative new-case volume {window_total} over last {len(counts)+1} runs exceeds 3x cap={case_cap}; possible drip flooding - investigate feed integrity")
    db.log(conn, "pipeline", "flag_run", f"new_cases={made} audit_samples={sampled} threshold={p_star:.3f} breaker={breaker}")
    return made, p_star, breaker, watch
