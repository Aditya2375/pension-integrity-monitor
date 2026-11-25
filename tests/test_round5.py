import hashlib, sqlite3
from pim import otp, pipeline, db


def test_default_weights_reproduce_constants():
    w = {k: v for k, v in db.DEFAULT_WEIGHTS.items()}
    L = pipeline.effective_lrs(w)
    for k, v in L.items():
        if k.startswith("LR_"):
            assert v == getattr(pipeline, k), k
    assert L["BANK_CLIFF_RECENT"] == 25.0 and L["TELE_CLIFF_OLD"] == 8.0


def test_editing_a_weight_changes_scoring_inputs():
    w = dict(db.DEFAULT_WEIGHTS)
    w["death_registry_match"] = (80.0, 0.25)
    w["bank_cliff"] = (50.0, 1.0)
    L = pipeline.effective_lrs(w)
    assert abs(L["LR_REG_STRONG_HI"] - 80.0) < 1e-9 and abs(L["LR_REG_STRONG_LO"] - 0.25) < 1e-9
    assert abs(L["BANK_CLIFF_RECENT"] - 50.0) < 1e-9
    assert L["BANK_CLIFF_MID"] > 15.0 and L["TELE_CLIFF_RECENT"] == 25.0


def test_otp_hash_is_keyed():
    h = otp._h("123456", "T1")
    assert h != hashlib.sha256(b"T1:123456").hexdigest()
    assert h == otp._h("123456", "T1") and h != otp._h("123457", "T1")


def test_removed_settings_are_gone():
    for k in ("match_threshold", "bank_inactivity_months", "life_cert_overdue_days", "old_age_years"):
        assert k not in db.DEFAULT_SETTINGS
