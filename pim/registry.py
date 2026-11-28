"""Civil death registry reconciliation.

A registered death certificate is the strongest single document a pension
system can get, so this module does two things with it and nothing else:

  * reconcile(): how many registrations were loaded, how many line up with a
    pensioner, how many of those lined-up cases are still unpaid-for-review,
    and how much was paid after the registered date of death.
  * draft_reasons(): turns a registry match into plain written reasons that an
    officer can edit and propose. This is the ONLY way registry data reaches a
    hold: the existing safe-hold path still applies (all four verification
    checks, a different supervisor approves, notice period, appeal window).

Nothing here changes a pension, freezes an account or writes to the audit
log. A registry match is a lead on a person, not proof of who that person is.
"""
from datetime import date, datetime
from statistics import median


def _d(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _paid_after(conn, pid, dod):
    """(count, total) of disbursements credited strictly after the registered date of death."""
    n = 0
    tot = 0.0
    for r in conn.execute("SELECT amount, credit_date FROM pension_disbursements WHERE pensioner_id=?", (pid,)):
        cd = _d(r["credit_date"])
        if cd and dod and cd > dod:
            n += 1
            tot += float(r["amount"] or 0)
    return n, round(tot, 2)


def reconcile(conn):
    regs = conn.execute("SELECT * FROM death_registry").fetchall()
    lags = []
    for r in regs:
        a, b = _d(r["date_of_death"]), _d(r["registration_date"])
        if a and b and b >= a:
            lags.append((b - a).days)
    matched = conn.execute(
        "SELECT c.id, c.pensioner_id, c.state, c.matched_death_id, r.date_of_death, r.registration_no, r.registration_date "
        "FROM cases c JOIN death_registry r ON r.registration_no=c.matched_death_id").fetchall()
    by_state = {}
    exposure_cases = 0
    exposure_total = 0.0
    late_regs = 0
    rows = []
    for m in matched:
        by_state[m["state"]] = by_state.get(m["state"], 0) + 1
        dod = _d(m["date_of_death"])
        n, tot = _paid_after(conn, m["pensioner_id"], dod)
        if n:
            exposure_cases += 1
            exposure_total += tot
        rows.append({"case_id": m["id"], "pensioner_id": m["pensioner_id"], "state": m["state"],
                     "registration_no": m["registration_no"], "date_of_death": m["date_of_death"],
                     "paid_after_n": n, "paid_after_total": tot})
    rows.sort(key=lambda x: (-x["paid_after_total"], x["case_id"]))
    matched_regs = {m["registration_no"] for m in matched}
    return {
        "registrations": len(regs),
        "matched_registrations": len(matched_regs),
        "unmatched_registrations": len(regs) - len(matched_regs),
        "median_lag_days": median(lags) if lags else None,
        "late_over_21_days": sum(1 for x in lags if x > 21),
        "lag_known": len(lags),
        "cases_by_state": by_state,
        "exposure_cases": exposure_cases,
        "exposure_total": round(exposure_total, 2),
        "rows": rows[:50],
    }


def draft_reasons(conn, cid):
    """Plain-language draft for the officer to edit. None when the case has no registry match."""
    c = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    if not c or not c["matched_death_id"]:
        return None
    r = conn.execute("SELECT * FROM death_registry WHERE registration_no=?", (c["matched_death_id"],)).fetchone()
    if not r:
        return None
    dod = _d(r["date_of_death"])
    n, tot = _paid_after(conn, c["pensioner_id"], dod)
    lines = [f"A civil death registration (no. {r['registration_no']}, {r['district'] or 'district not recorded'}) "
             f"records a death on {r['date_of_death']}, registered {r['registration_date'] or 'on an unrecorded date'}.",
             "The registry entry was linked to this pensioner by identity matching. A link is a lead, not proof of identity."]
    if n:
        lines.append(f"{n} pension credit(s) totalling {tot:.2f} were paid after that date.")
    else:
        lines.append("No pension credit after that date appears in the disbursement feed.")
    lines.append("Before any hold: confirm the certificate with the registrar, confirm it is this person "
                 "(not a namesake), and give the family notice and the right to appeal.")
    return " ".join(lines)
