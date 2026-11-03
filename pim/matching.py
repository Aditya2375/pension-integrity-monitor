"""Identity matching modelled on the UIDAI-style threshold approach:
name-match percentage, gender match, and date-of-birth agreement.
"""
import re, difflib

STOPWORDS = {"sri", "smt", "shri", "mr", "mrs", "kumari", "dr"}

def normalize_name(name):
    if not name:
        return ""
    n = re.sub(r"[^a-z ]", " ", name.lower())
    tokens = [t for t in n.split() if t and t not in STOPWORDS]
    return " ".join(tokens)

def soundex(name):
    """Classic Soundex, useful for Indian-name spelling variation."""
    name = re.sub(r"[^a-z]", "", name.lower())
    if not name:
        return ""
    codes = {"bfpv": "1", "cgjkqsxz": "2", "dt": "3", "l": "4", "mn": "5", "r": "6"}
    def code(ch):
        for k, v in codes.items():
            if ch in k:
                return v
        return ""
    first = name[0].upper()
    tail = [code(c) for c in name[1:]]
    out, prev = [], code(name[0])
    for c in tail:
        if c and c != prev:
            out.append(c)
        prev = c
    return (first + "".join(out) + "000")[:4]

def name_match_pct(a, b):
    """Token-level similarity in [0,1]: best-pair alignment plus sequence ratio."""
    ta, tb = normalize_name(a).split(), normalize_name(b).split()
    if not ta or not tb:
        return 0.0
    if set(ta) == set(tb):
        return 1.0
    # phonetic rescue: tokens that sound alike count as equal
    def teq(x, y):
        return x == y or (soundex(x) == soundex(y) and soundex(x) != "")
    used = set()
    hits = 0.0
    for x in ta:
        best, bestj = 0.0, -1
        for j, y in enumerate(tb):
            if j in used:
                continue
            if teq(x, y):
                s = 1.0
            else:
                s = difflib.SequenceMatcher(None, x, y).ratio()
            if s > best:
                best, bestj = s, j
        if bestj >= 0:
            used.add(bestj)
            hits += best
    token_score = hits / max(len(ta), len(tb))
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return 0.6 * token_score + 0.4 * seq

def dob_agreement(d1, d2):
    """exact | year | mismatch, tolerant of YYYY-MM-DD and DD-MM-YYYY."""
    def parts(d):
        if not d:
            return None
        d = d.strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", d)
        if m:
            return m.group(1), m.group(2), m.group(3)
        m = re.match(r"^(\d{2})[-/](\d{2})[-/](\d{4})$", d)
        if m:
            return m.group(3), m.group(2), m.group(1)
        m = re.match(r"^(\d{4})$", d)
        if m:
            return (m.group(1), None, None)
        return None
    p1, p2 = parts(d1), parts(d2)
    if not p1 or not p2:
        return "mismatch"
    if p1 == p2 and p1[1] is not None:
        return "exact"
    if p1[0] == p2[0]:
        return "year"
    return "mismatch"

def match_score(pensioner, candidate, gender_required=True):
    """Weighted identity score in [0,1]. Gender is a hard gate by default,
    mirroring the UIDAI-style rule that gender must match."""
    nm = name_match_pct(pensioner["name"], candidate["name"])
    g1 = (pensioner["gender"] or "").strip().lower()[:1]
    g2 = (candidate["gender"] or "").strip().lower()[:1]
    gender_ok = (g1 == g2) if (g1 and g2) else False
    dob = dob_agreement(pensioner["dob"], candidate["dob"])
    if gender_required and not gender_ok:
        return 0.0, nm, gender_ok, dob
    dob_pts = {"exact": 1.0, "year": 0.6, "mismatch": 0.0}[dob]
    score = 0.65 * nm + 0.35 * dob_pts
    return round(score, 4), round(nm, 4), gender_ok, dob
