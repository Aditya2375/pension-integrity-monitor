# Frozen validation candidate

This candidate is not the deployed production scorer. It is awaiting independent validation.

- Extracts streaming source summaries and identity-linked evidence from the 29-feed schema.
- Keeps household activity separate from personal activity.
- Uses work month, rather than delayed wage payment date, for employment evidence.
- Constrains utility links by address similarity and rejects tied links.
- Applies district blocking before matching documentary candidates.
- Uses a development-trained classifier. Its private weights and all development datasets are excluded from this repository. No unseen test labels have been used.
- Scores identify review candidates only. They must never automatically stop payments.

The current implementation has measured development runs only. It does not yet establish accuracy or memory bounds at population scale. Do not use an uploaded pickle as a model. Only the locally produced, hash-verified model artifact may be loaded.
