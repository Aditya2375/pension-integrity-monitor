"""Static accessibility checks on rendered pages (no browser needed)."""
import re
from html.parser import HTMLParser
import pytest
from conftest import Client, as_user
from pim import db


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = []; self.fors = []; self.fields = []; self.labels_wrap = 0
        self.headings = []; self.problems = []; self.in_label = False; self.lang = None; self.title = False
        self.main = 0; self.links = []; self.cur_a = None; self.table_th = 0; self.imgs = []
    def handle_starttag(self, tag, a):
        a = dict(a)
        if "id" in a: self.ids.append(a["id"])
        if tag == "html": self.lang = a.get("lang")
        if tag == "title": self.title = True
        if tag == "main": self.main += 1
        if re.fullmatch(r"h[1-6]", tag): self.headings.append(int(tag[1]))
        if tag == "label":
            self.in_label = True
            if "for" in a: self.fors.append(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            labelled = self.in_label or a.get("aria-label") or a.get("aria-labelledby")
            self.fields.append((a.get("id"), bool(labelled)))
        if tag == "img" and "alt" not in a: self.problems.append("img without alt")
        if tag == "span" and a.get("class") == "sr" and getattr(self, "cur_th", None) is not None: self.th_sr = True
        if tag == "a":
            self.cur_a = ""
            if not a.get("href"): self.problems.append("a without href")
        if tag == "th" and "scope" not in a: self.problems.append("th without scope")
        if tag == "th": self.cur_th = ""
        if "style" in a: self.problems.append("inline style")
        if tag == "form" and a.get("method", "get").lower() == "post" and False: pass
    def handle_endtag(self, tag):
        if tag == "th" and getattr(self, "cur_th", None) is not None and not self.cur_th.strip() and not getattr(self, "th_sr", False): self.problems.append("empty th")
        if tag == "th": self.cur_th = None; self.th_sr = False
        if tag == "label": self.in_label = False
        if tag == "a":
            if self.cur_a is not None and not self.cur_a.strip(): self.problems.append("empty link text")
            self.cur_a = None
    def handle_data(self, d):
        if getattr(self, "cur_th", None) is not None: self.cur_th += d
        if self.cur_a is not None: self.cur_a += d


def audit(html):
    s = Scan(); s.feed(html); p = list(s.problems)
    if not s.lang: p.append("no lang")
    if s.main != 1: p.append(f"main landmarks: {s.main}")
    dup = {i for i in s.ids if s.ids.count(i) > 1}
    if dup: p.append(f"duplicate ids {dup}")
    for fid, ok in s.fields:
        if not ok and fid not in s.fors: p.append(f"unlabelled field {fid}")
    for f in s.fors:
        if f not in s.ids: p.append(f"label for missing id {f}")
    if s.headings.count(1) != 1: p.append(f"h1 count {s.headings.count(1)}")
    for a, b in zip(s.headings, s.headings[1:]):
        if b - a > 1: p.append(f"heading jump h{a}->h{b}")
    return p


def case_id():
    c = db.connect(); r = c.execute("SELECT id FROM cases LIMIT 1").fetchone(); c.close(); return r[0] if r else None


def test_all_pages_pass_static_audit(fresh_db):
    import test_flow as T
    adm = as_user("adm1"); T.load(adm)
    cid = case_id()
    pages = {"anon": ["/login", "/appeal", "/appeal?lang=hi", "/context"],
             "adm1": ["/", "/queue", f"/case/{cid}", "/appeals", "/settings", "/health", "/feedback", "/ingest", "/context"]}
    bad = {}
    for who, paths in pages.items():
        cl = Client() if who == "anon" else adm
        for pth in paths:
            r = cl.get(pth)
            assert r.status_code == 200, (pth, r.status_code)
            p = audit(r.get_data(as_text=True))
            if p: bad[pth] = p
    assert not bad, bad
