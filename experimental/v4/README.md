# V4 validation candidate

Experimental, not deployed. Government handover scope covers all pension schemes, with scheme-specific validation required. No government API access is implied.

Compared with V3: trained against independently missing feeds, living people missing certificates, historical certificates for deceased people, account reuse, and stopped payments. Target is review for death with continuing payments, not death alone. Training uses no blind labels or records. Personal activity, household activity, documentary dates and payment continuation remain separate features. Exact registry dates come from the identity-linked registration rather than a competing fuzzy match.

The model artifact stays private and is hash-verified before use. Do not load externally uploaded pickle files. The score is a review priority, not a calibrated death probability. A precommitted operating point is mapped monotonically to 0.5. Records without a recent observed credit receive a lower review priority. Missing certificates never directly authorize a death finding. Officers must reconcile documentary evidence, hear appeals and record reinstatement; no automatic cancellation is permitted.

Development performance is not a claim of population-scale accuracy, regulatory compliance or government acceptance. Integration, security and scale validation remain separate gates.
