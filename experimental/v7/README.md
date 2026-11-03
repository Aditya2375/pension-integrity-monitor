# V7 independent-validation candidate

Changes: person-specific activity baseline and variation; joint cessation timing; silence surprise compared with observed personal frequency; household master-member continuation; district observed registration lag summaries; all tied documentary alternatives retained with deterministic global assignment and explicit unresolved conflicts. A separate held-out isotonic calibration was evaluated without changing the precommitted operating decisions.

Development holdout:98.06% precision and97.27% recall, below98/98. Held-out calibration improved Brier loss from0.001197 to0.001090 in a separate development set; this is not proof of calibration on government data. Household members outside the pension master are not yet represented well in development fixtures, so household generalization is unverified. Registration lag summaries describe observed registered deaths and are selection-biased, not an estimate of unregistered-death completeness.

Review priority is not a calibrated death probability. The frozen review operating point maps monotonically to0.5. The calibration experiment is a separate evaluation and is not used to claim the ranking passes. No automatic payment action is permitted. No blind records or labels were used for development.

Use an explicit snapshot date. Experimental local intermediate aggregates remain trusted-local pickle files, not uploadable artifacts. JSON model inference verifies an independently supplied expected digest. The separate safe aggregate replacement is not silently substituted during validation.
