# Pension Integrity Benchmark (Synthetic)

**All data in this repository is synthetic. Every record was written by a seeded generator. No real pensioner, bank account, Aadhaar number, PAN, phone number or any other real person's data appears anywhere in this dataset.**

The benchmark holds 200,000 synthetic pensioners across 29 administrative feeds and three months of activity, with fully labelled ground truth. It is the frozen blind test set (round 17) used to measure the V15 deceased-detection candidate in [pension-integrity-monitor](https://github.com/Aditya2375/pension-integrity-monitor).

## Headline blind result

V15 was frozen on 2026-11-04 16:28:52 IST, before this dataset existed. The set was generated independently, and the frozen candidate was scored against it exactly once, at threshold 0.5. No tuning happened on this set.

| Metric | Value |
| --- | --- |
| Precision | 99.13% |
| Recall | 88.81% |
| F1 | 0.9368 |
| Average precision | 0.9386 |
| Flagged | 6,786 |
| True positives | 6,727 |
| False positives (living pensioners) | 59 |
| False negatives (missed targets) | 848 |
| True negatives (living) | 191,541 |
| Already-stopped decoys flagged | 0 of 825 |

## Composition

| Class | Count |
| --- | --- |
| Living pensioners | 191,600 |
| Deceased, pension still paid (detection targets) | 7,575 |
| Deceased, pension already stopped (decoys) | 825 |
| Total | 200,000 |

Hard subgroups inside the 7,575 targets: 1,496 died within 45 days of the snapshot, 1,903 have no registered death record, and 385 are both. V15 caught 147 of those 385.

## How the blind set was made

1. The mix declaration was committed before any generation: `declaration/frozen_mix_r17.json`, sha256 `96ce39bbcbac8029bd3b350b312988b2c2e845844d3384e2b924e4781a041860`.
2. The generator ran once with that declaration: `generator/generate_v31.py`, sha256 `b4c52282e26e834e10399a5218b9f58d5c5750aa6ff2e27e8507705b114479e1`, seed `2026110417`, n=200000, offset 0, 3 months of activity ending at snapshot date 2026-11-03.
3. The feeds were zipped and hashed before the scorer ever saw them: zip sha256 `01b79c97b5ec83445ab1102bf43bfade1e8d85033cb0ebd7afa6afa626cd2edf`, per-file manifest in `round17_frozen_feeds.MANIFEST.sha256` (self-hash `174c6904b85336f330d154f5d1fc5333f88d6436b7cf109e252aadc23bf5fbfb`).
4. The frozen candidate's flag list (sha256 `e890c4eabe8584c1d6617469bb4f124d1fc3ff3b9bc6abeb6a5c5105e2fdb8c9`) was scored against the held ground truth.

Mix knobs (from the declaration): dead_frac 0.042, fraud_frac 0.65, misscert_frac 0.05, recent_frac 0.12, lowreg_boost 1.0, lowvol_frac 0.10, rural_lag_mean 20.0, decoy_frac 0.05, masked_frac 0.05, irreg_frac 0.10, famutil_frac 0.55, bursty_frac 0.12. Death registration rates vary by district (0.52 to 0.97); the full list is in the declaration file.

## Repository contents

| Path | What it is |
| --- | --- |
| `generator/generate_v31.py` | The exact generator, byte-identical to the one that produced this set |
| `declaration/frozen_mix_r17.json` | The pre-generation committed mix declaration |
| `round17_frozen_feeds.MANIFEST.sha256` | Per-file sha256 of all 29 feed CSVs |
| `labels.csv.gz` | Ground truth for all 200,000 pensioners (see below) |
| `meta.json` | Run metadata emitted by the generator |
| Release asset `round17_frozen_feeds.zip` (66 MB) | The 29 feed CSVs, byte-identical to the scored artifact |

## The 29 feeds

Pension master and disbursements, life certificates, death registry, birth and marriage registers, hospital records, PM-JAY claims, Aadhaar registry, bank KYC, bank transactions, electoral roll, EPFO/UAN, NPS accounts, LIC insurance, ration/PDS, LPG refills, telecom activity, utility bills, MGNREGA work, tax/PAN activity, GST registrations, passport registry, driving licences, vehicle RC, toll/FASTag, vaccination records and education records. Identifiers are deliberately impossible values (Aadhaar numbers start `9999`, PANs start `FAKE`, IFSC codes contain `DEMO`, phone numbers start `1000`), so the set can never be mistaken for real records.

## Labels format

`labels.csv.gz` has one row per pensioner: `pensioner_id`, `alive`, `death_date`, `registered`, `pension_still_paid`, plus the scenario flags the generator used (for example `fully_masked`, `family_withdraws`, `bursty_dead`, `low_volume_living`, `offline_but_alive`). A row is a detection target when `alive` is false and `pension_still_paid` is true. Scoring convention: flagging a living pensioner or an already-stopped decoy counts as a false positive.

## Reproduce and verify

```bash
sha256sum round17_frozen_feeds.zip   # 01b79c97b5ec83445ab1102bf43bfade1e8d85033cb0ebd7afa6afa626cd2edf
unzip round17_frozen_feeds.zip
(cd feeds && find . -type f -name '*.csv' | sort | xargs sha256sum)   # compare with round17_frozen_feeds.MANIFEST.sha256
python3 generator/generate_v31.py --n 200000 --seed 2026110417 --offset 0 --months 3 --out round17_frozen \
  --dead-frac 0.042 --fraud-frac 0.65 --misscert-frac 0.05 --recent-frac 0.12 --lowreg-boost 1.0 \
  --lowvol-frac 0.10 --rural-lag-mean 20.0 --decoy-frac 0.05 --masked-frac 0.05 --irreg-frac 0.10 \
  --famutil-frac 0.55 --bursty-frac 0.12
```

The regenerated feeds match the published manifest file for file, byte for byte.

## Limits

This is a synthetically generated benchmark. The generator is calibrated to public aggregates (death registration rates, telecom and banking patterns of elderly citizens), not to data from any real pension system. Scores here measure detection on this generator's distribution; they are not evidence of field performance on real data, and no production or population-scale claim is made.
