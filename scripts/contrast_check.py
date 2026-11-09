"""Check text/background pairs from static/style.css against WCAG 2.1 AA."""
import re, sys
css = open("static/style.css").read()
var = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", css))
def lum(h):
    h = h.lstrip("#"); c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True); return (la + .05) / (lb + .05)
PAIRS = [("ink", "bg", 4.5), ("ink", "card", 4.5), ("muted", "bg", 4.5), ("muted", "card", 4.5),
         ("white", "teal", 4.5), ("nav", "teal", 4.5), ("teal", "card", 4.5), ("ok", "okbg", 4.5),
         ("warn", "warnbg", 4.5), ("grey", "greybg", 4.5), ("pri", "pribg", 4.5), ("white", "warn", 4.5),
         ("foot", "bg", 4.5), ("link", "card", 4.5), ("teal", "bg", 4.5)]
bad = 0
for fg, bg, need in PAIRS:
    r = ratio(var[fg], var[bg]); ok = r >= need; bad += not ok
    print(f"{'ok ' if ok else 'BAD'} {fg} on {bg}: {r:.2f} (need {need})")
sys.exit(1 if bad else 0)
