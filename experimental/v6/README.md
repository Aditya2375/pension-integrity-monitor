# V6 independent-validation candidate

Changes from V5: explicit snapshot date, future-dated observations excluded from personal cessation windows, convergent cessation across bank/telecom/utility, alignment windows, utility consumption/payment history, personal-activity source counts, and higher training cost for false flags of ordinary living people. Source coverage remains a limitation, not proof of death. No blind records or labels are used to train this candidate.

Use PIM_SNAPSHOT_DATE=YYYY-MM-DD when extracting features. Preserve the frozen model's precommitted raw operating point, transformed monotonically to review score0.5. The score is not a calibrated death probability. No automatic cancellation is permitted. Absence of records can reflect incomplete feeds, not death.

Development holdout:97.39% precision and97.32% recall, below98/98. A new blind round is required to measure generalization. JSON inference verifies the independently supplied digest. Intermediate pickle aggregates are still research-only and must never be accepted from an uploader. A data-only aggregate replacement is under separate development.
