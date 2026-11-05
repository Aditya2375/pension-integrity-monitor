# Detection evidence limits

4 November2026. Status: benchmark findings, not a proven mathematical upper bound.

## Observed independent results

| Candidate / fresh round | Precision at frozen operating point | Recall | Average precision |
|---|---:|---:|---:|
| V5 / round6 |96.5%|78.2%|87.4%|
| V6 / round7 |96.9%|76.6%|81.9%|
| V7 / round8 |94.3%|75.0%|81.1%|

The mixes differ, so this is not a controlled same-dataset comparison. None meets98%precision and98%recall. Source feeds were removed after each run. Only aggregate grading, output hashes and frozen software/model provenance are retained.

Visible-registration recall stayed approximately99%. Delayed-registration recall was35-38%, unregistered recall56-57%, recent-death recall48-52%. Fully masked cases were detected about50% in the last two rounds. Personal-baseline refinements improved convergent-silence recall from57%to63% but increased false flags for living people with irregular activity:149 of250 living false flags in round8 were irregular-baseline cases. This is evidence of an unresolved discrimination problem, not evidence that silence establishes death.

Three fresh evaluations show a plateau around75-78%overall recall at these fixed high-precision operating points. They do not establish that every possible model has that ceiling, nor that a national deployment will achieve it. The dataset owner's estimate that some unregistered deaths are fully masked is an aggregate benchmark observation, not a verified national prevalence. Do not multiply it into a national ceiling or promise93-96%recall without measurement.

## Why additional observations matter

If a living person's lawful family-assisted withdrawals, household utility use and delayed reporting produce the same observable record as a deceased person's family account use, no deterministic classifier of that record can separate the two. The evaluation has not measured the frequency of exact indistinguishable pairs, so an empirical irreducible-error percentage is unknown. Missing coverage, status errors, time lag and domain shift can also explain misses. A supervised review workflow must distinguish those explanations rather than call all misses structurally impossible.

## Data additions and safe validation

| Addition | Potential information | Limit / validation required |
|---|---|---|
| Timely civil death registration plus registration/arrival timestamps | Positive documentary death evidence and lag measurement | Identity linkage errors and wrongly reported deaths require appeal; data-sharing authority is required. Measure incremental recall at the same living false-flag budget. |
| Accepted life-certificate receipt plus physical/doorstep alternatives | Strong recent living evidence and protection from lost digital submissions | Validity depends on scheme; no digital certificate is not death. Reconcile receipt and rejection states. |
| Identity-linked bank KYC with method and time | Verified in-person presence may protect living people and help identity linkage | Administrative updates may not require personal presence. Bank activity is not personal life proof. Do not label all KYC refresh as biometric attendance. |
| Purpose-limited health encounter or pharmacy attendance | Recent personal contact may rule out some death hypotheses | A household prescription/refill may not show attendance; health data are sensitive and consent/purpose limited. No national unrestricted health-data access is assumed. |
| Ration/PDS member-authentication versus household offtake | Separates personal attendance from household continuation | Existing aggregate household offtake is weak; exclusion can harm living beneficiaries. Validate service failures and alternate fulfillment. |
| Mobile recharge, subscriber transfer and SIM ownership events | Context for apparent silence or family reuse | Recharge is often done by another person and is not personal presence. Access and retention require a lawful basis; never infer death from recharge gaps alone. |
| Coverage manifests and pipeline watermarks | Distinguish real zero activity from missing/stale feeds | Often more valuable for safety than another noisy behavioural feed. Missing observations must remain unknown. |
| Authorized field verification and appeal outcomes | Direct review evidence for the uncertain band and retraining | Cost, delay and selection bias must be measured. Never treat review-queue labels as a representative population base rate. |

There is no measured uplift percentage for these additions. A prospective shadow-mode evaluation should add each source separately, freeze the model, and measure incremental recall, false flags per100,000living people, linkage errors, coverage by scheme/district, time-to-review and appeal reversals. Cluster/household-separated and temporal holdouts are required; random row splits alone overstate transfer.

## Source-grounded constraints

- RBI, pension FAQ updated1April2025: a surviving spouse may continue the existing joint account for authorized family pension; physical/doorstep life-certificate alternatives and assisted withdrawals exist. Continued account use is not automatically abuse. This FAQ is general guidance, not legal advice: https://www.rbi.org.in/commonman/Upload/English/FAQs/PDFs/FAQPENSION01042024.pdf
- UIDAI circular on reactivation of wrongly reported deceased cases describes validation against death-registration data and a correction path when the holder is alive: https://uidai.gov.in/images/Circular_for_reactivation_of_wrongly_reported_deceased_cases.pdf
- JeevanPramaan onboarding guidelines restrict DLC sharing to the pensioner's sanctioning/disbursing agency as covered by consent: https://jeevanpramaan.gov.in/newassets/docs/Jeevan-Pramaan-Guidelines.pdf
- JeevanPramaan FAQ says certificate validity follows the sanctioning authority's rules and the digital option is additional to existing certificate methods: https://jeevanpramaan.gov.in/v1.0/misc/faq
- ABDM Health Information Exchange Consent Manager overview describes user consent for health-record exchange: https://abdm.gov.in/strapicms/uploads/ABDM_HIE_CM_ea5d4c0559.pdf
- PFMS FAQ describes scheme/agency configuration and controlled external-system integration, not open access to arbitrary beneficiary records: https://pfms.nic.in/SitePages/doc/PFMS_DBT_FAQ.pdf

No claim of legal compliance, government approval or production data access follows from these documents. Scheme-specific rules, current interfaces and data agreements must be checked by the responsible authority.

## Final candidate: V15 (frozen 5 November 2026)

The frozen final candidate is V15, a reliability-gated two-expert blend. Its one blind scoring (round 17, 200,000-row fresh set; candidate, features and thresholds frozen before the feeds existed) measured 99.13% precision and 88.81% recall. This is the best measured operating point of the programme and the reference any future candidate must beat head-to-head on the same held-out data at the same precision.

## Full candidate record

Blind rounds are single scorings of a frozen candidate on a fresh set, graded aggregate-only. Local proxy rows are development scorings on privately generated synthetic fixtures (40,000 rows, fresh seed drawn after the rules were frozen, single look, no tuning); they are not blind evidence.

| Candidate / evaluation | Precision | Recall | Decision |
|---|---:|---:|---|
| V11 / round 12 blind | 96.19% | 82.69% | Below targets; superseded |
| V12 / round 14 blind | 98.99% | 82.37% | Below the 99% precision constraint; superseded |
| V13 / round 15 blind | 99.19% | 88.44% | Superseded by V15's higher recall at comparable precision |
| V14 / round 16 blind | 96.28% | 88.77% | Rejected: failed the precision constraint |
| **V15 / round 17 blind** | **99.13%** | **88.81%** | **Final, frozen** |
| V16 / round 18 blind | 99.70% | 84.85% | Rejected: higher precision but recall regressed |
| V17 / local proxy only | 98.94-99.29% | 84.93-85.34% | Rejected: precision did not hold at or above 99.13% across fresh proxy seeds |
| V18 / local proxy only | 98.87% | 85.54% | Rejected: recall margin +2.2 points over V15, below the agreed +3 bar, at 98.87% precision |

V17 added per-person baseline-normalised silence features (baseline z-scores, quantile exceedance, a joint cross-channel silence index, withdrawal discontinuity and drain velocity) on repaired causal fixtures. It beat V15 on its first local proxy seed at equal precision but dipped to 98.94% precision on the next fresh seed, so it did not uniformly meet the frozen operating constraint and was not taken to a blind round.

V18 kept V17 as the primary and added a gated secondary upweighted on the hardest subgroup (recent deaths within 45 days of the snapshot with no registry edge). On a fresh proxy seed it gained +2.2 recall points over V15, below the +3 bar set for spending a blind round, at 98.87% precision, so it was discarded.

The adoption rule throughout: an idea replaces the frozen best only if it beats it head-to-head on the same held-out data at the same precision; otherwise it is discarded with reasons. Model weights, thresholds and training fixtures stay private; only aggregate scores and provenance hashes are retained.

## Tier 1 headline and time-to-flag (5 November 2026)

The system's headline is tier 1 only: **99.13% precision, 88.81% recall**, blind-verified. Never blend tier-2 numbers into the headline.

Time-to-flag, measured on two synthetic held-out sets (RepairTest, proxyB): 99.7% of tier-1 true flags are documentary (death registry, hospital DIED, electoral deletion). The first documentary signal arrives a median of 19-20 days after death (p90: 44-47 days); that is upstream registration lag in the data, not scoring latency. Under the original monthly batch scoring, flags fired a median of 91-104 days after the signal arrived. Under event-driven scoring with the same frozen rules (rescore the moment a record is ingested), the flag fires within minutes of the first observable signal being ingested; daily batch scoring is the fallback and fires within 1-2 days. Precision and recall are unchanged as eventual metrics, provided the daily run computes identical feature values from identical records: calendar-month aggregate features must treat incomplete months as incomplete (never as completed months with zero activity), rolling windows must use the same day boundaries, and late-arriving or corrected records must be handled the same way. The 1-2 day figure is signal-to-flag after the signal is ingested, not after it occurs upstream. Before claiming equivalence, run a paired replay: score the same historical event stream monthly and daily, compare person-level final classifications, and report precision and recall at fixed observation horizons. The remaining deaths-to-flag wait is the upstream arrival lag, measured by source on the flagged true positives: hospital DIED records are dated the day of death and cover about 42-44% of flagged true positives (a same-day flag is possible for this group when the hospital feed streams daily; the synthetic data does not model hospital feed transport time), death-registry records land a median of 18-19 days after death (fastest decile 5-6 days), electoral deletions a median of 49-50 days. That arrival lag, not scoring, is the floor; no honest scoring design can flag before any signal exists, and the only way to lower the floor is faster upstream notification. Under the 1-2 day signal-to-flag constraint, the maximum achievable recall is 1 minus the share of deaths with no usable signal inside the window; on these sets that share is about 11%, so the ceiling is about 89% recall at high precision, which is where tier 1 already sits.

## Why recall is capped (measured 5 November 2026)

Miss anatomy shows about 91% of all misses are deaths within 45 days of the snapshot, unregistered, pension still paid: the family still uses the account or the silence is days long and indistinguishable from normal irregular activity. A score-curve sweep and an oracle catch-all (flag every still-paid pensioner with any anomaly on any channel) bound what is possible: the catch-all reaches only 92% recall at about 6% precision while reviewing roughly half the roll, so such a broad low-precision band was measured and rejected as operationally useless. 98% recall at high precision is not reachable with these feeds. A conditional-distribution test on the hardest subgroup (recent unregistered deaths with zero thresholded anomaly) found residual predictive signal (4-fold AUC about 0.80) but harvesting it adds only about one recall point before precision collapses.

Independent methods review (two external critics, anonymized synthetic-data brief) agreed: no honest modeling method breaks this ceiling with the same signals; the only real lever is faster upstream signals (timely death registration, hospital feeds, verified family or institutional notification).
