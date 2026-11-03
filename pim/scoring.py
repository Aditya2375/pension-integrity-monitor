"""Per-signal likelihood-ratio scoring on a configurable base rate,
a calibrated posterior probability, and a cost-based priority threshold.
Flags rank the review queue only; nothing here ever holds a pension.
"""
import math

def logit(p):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))

def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))

def cost_threshold(cost_false_hold, cost_missed_death):
    """Probability above which a case is priority review, from relative costs:
    p* = C(false hold) / (C(false hold) + C(missed death))."""
    ch, cm = float(cost_false_hold), float(cost_missed_death)
    if ch + cm <= 0:
        return 0.5
    return ch / (ch + cm)

def score_case(base_rate, signals, death_match_confidence=None):
    """signals: list of (name, present, lr_plus, lr_minus).
    The death-registry match LR is scaled by identity-match confidence.
    Returns (log_odds, probability, per_signal_contrib)."""
    lo = logit(base_rate)
    contrib = []
    for name, present, lp, lm in signals:
        lp, lm = max(float(lp), 1e-6), max(float(lm), 1e-6)
        if name == "death_registry_match" and present and death_match_confidence is not None:
            c = min(max(death_match_confidence, 0.0), 1.0)
            lr = lm ** (1 - c) * lp ** c
        else:
            lr = lp if present else lm
        d = math.log(lr)
        lo += d
        contrib.append((name, present, round(d, 4)))
    return round(lo, 4), round(sigmoid(lo), 4), contrib
