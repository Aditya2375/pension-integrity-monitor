# Pension Integrity Monitor

Ranks pensioners for human review when public-record signals suggest a death may have gone unreported, and manages the full officer review, family appeal and outcome-feedback loop around that ranking.

The system never stops a pension by itself. Flags only order a review queue. A pension is held only by an officer, only after every verification step is complete, and only with written reasons. Families get a tracking ID, a deadline and a public appeal portal. A release pays full arrears for every day held.

## What it does

- **Ingestion adapters**, one per department feed: pension disburser roll, civil death registry, electoral roll, bank inactivity report, life certificate feed. Each adapter validates a CSV against the feed's documented schema, rejects bad rows and records feed health. Nothing is fabricated: only the records you load enter the system.
- **Identity matching** modelled on the UIDAI-style threshold approach: name-match percentage with phonetic tolerance, a hard gender gate, and date-of-birth agreement (exact, year-only, mismatch), combined into a 0-1 identity score with a configurable threshold.
- **Per-signal likelihood-ratio scoring** on a configurable base rate, producing a calibrated probability per pensioner. Signals: death-registry match (scaled by identity-match confidence), electoral deletion, bank inactivity, overdue life certificate, age over 90.
- **Cost-based priority threshold**: p* = C(false hold) / (C(false hold) + C(missed death)). It ranks the queue; it triggers no action.
- **Officer review queue** ordered by calibrated probability, with the full signal breakdown and the matched registry entry on each case.
- **Verification steps** (registrar cross-check, field visit, family contact, bank confirmation) that must all complete before a hold is possible.
- **Hold with mandatory written reasons**, a family tracking ID and an appeal deadline.
- **Family appeal portal** (public, no sign-in): look up a tracking ID, see case status and deadline, submit an appeal. Officers resolve appeals from the appeals page.
- **Release with full arrears**, computed from days held and monthly pension.
- **Outcome feedback**: verified outcomes (confirmed deceased / confirmed alive) recalibrate the signal likelihood ratios and the base rate with Laplace smoothing, once at least 5 cases are resolved.
- **Feed-health monitoring**: each feed is marked ok, stale or never loaded against its expected cadence.

## Feed schemas

Download headers-only templates from the ingestion page (`/templates/<feed>.csv`) or see `pim/ingest.py`. Required columns:

| Feed | Required columns |
| --- | --- |
| pension_disburser | pensioner_id, name, gender, dob, scheme, monthly_amount |
| death_registry | death_id, name, gender, dob, date_of_death |
| electoral_roll | epic, name, gender, dob, status |
| bank_inactivity | account_ref, pensioner_id, months_inactive |
| life_certificates | pensioner_id, cert_date |

Dates accept YYYY-MM-DD or DD-MM-YYYY.

## Running locally

```
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. Officer sign-in key defaults to `officer`; set `PIM_OFFICER_KEY` in production and `PIM_SECRET` for session signing. The family appeal portal at `/appeal` needs no sign-in.

Run the end-to-end test suite (uses its own throwaway fixtures in `tests/fixtures`, never loaded into the app):

```
python tests/test_flow.py
```

## Deployment

Free tier on Render (no card required): create a new Web Service from this repo, build command `pip install -r requirements.txt`, start command `python app.py`, and set the `PIM_OFFICER_KEY` and `PIM_SECRET` environment variables. `render.yaml` is included for one-click setup.

## Public data sources

The Public data context page ships with real, published aggregate figures. These are not pension-roll records, are not loaded into the flagging feeds, and say nothing about the system's accuracy, which is unmeasured. Each row carries its source URL and licence note; the data lives in `data/public_context.csv`.

- The Hindu, reporting CRS 2024 death-registration completeness: https://www.thehindu.com/sci-tech/health/how-india-counts-its-dead/article71188343.ece (press citation of the public CRS report)
- PIB / UIDAI, Aadhaar deactivations after death: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2223050&lang=1&reg=3 (government press release)
- The Hindu, Telangana Cheyutha liveness drive: https://www.thehindu.com/news/national/telangana/liveness-authentication-reveals-major-irregularities-in-cheyutha-pension-scheme/article71133374.ece (press citation)
- The Hindu, Dharwad e-Janma registry match: https://www.thehindu.com/news/national/karnataka/7973-dead-persons-still-got-pension/article33908171.ece (press citation)
- ThePrint, reporting the CAG NSAP audit: https://theprint.in/india/governance/pension-payments-for-over-2000-dead-people-cag-report-flags-lapses-in-govt-welfare-schemes/1706064/ (press citation of a public audit)
- Down To Earth, reporting the CAG NSAP audit: https://www.downtoearth.org.in/governance/rs-79-crore-transferred-to-ineligible-beneficiaries-under-nsap-finds-cag-91122 (press citation of a public audit)
- The New Indian Express, Tamil Nadu verification drive: https://www.newindianexpress.com/states/tamil-nadu/2022/Jun/12/174-lakhdead-pensioners-weeded-out-tamil-nadu-saves-rs-200-crore-2464904.html (press citation)
- The Hindu BusinessLine, reporting the CAG Haryana audit: https://www.thehindubusinessline.com/news/national/haryana-transferred-100-cr-to-ghost-pensioners-in-2017-20/article65751525.ece (press citation of a public audit)
- Jeevan Pramaan portal, cumulative DLCs: https://jeevanpramaan.gov.in/ (government portal figure)
- NewsOnAir, DLC Campaign 4.0: https://newsonair.gov.in/over-1-54-crore-digital-life-certificates-issued-under-dlc-campaign-4-0/ (government broadcaster)
- IANS, DLC Campaign 4.0 face authentication: https://ianslive.in/154-cr-dlcs-processed-over-91-lakh-generated-using-face-authentication-tech-govt--20251201174230 (press citation)
- Open Government Data Platform India, aggregate pension datasets: https://www.data.gov.in/catalog/sampann-pensioner-data (Government Open Data License, NDSAP)
- Election Commission of India, aggregate elector statistics: https://www.eci.gov.in/electoral-roll (public statistical report)

Person-level pension, death-registry, electoral and bank data is personal data and is not publicly available; those feeds ship empty with documented schemas until a real department feed is loaded.

## Accuracy and privacy

No accuracy figure is claimed anywhere in this system: no production data has been scored, and every probability shown is a model output for human review, not a measurement. The design treats the family appeal as a technical requirement, not an afterthought: every hold carries written reasons, a tracking ID, a deadline and a public appeal route, and every release pays full arrears.

## Author

Aditya Kulkarni
