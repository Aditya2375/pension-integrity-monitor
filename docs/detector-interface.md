# Detector interface, draft1.0

Status: engineering contract for integration work, not a production integration claim. Frozen V4 remains the independent-validation entry point and must not be changed during its run. All pension schemes are in scope. The legacy29-feed names are not a claim that all schemes provide those feeds.

## Authority and batch envelope

Each batch is limited to one authority and one identity-token key version. A manifest must supply `contract_version`, `batch_id`, `authority_id`, `token_key_version`, `snapshot_date`, `arrival_time` with timezone, source-system labels, source hashes, per-feed coverage intervals and completeness states. Authority and token metadata are not inferred from IDs. Cross-authority matching is prohibited by default. No raw Aadhaar, bank account, PAN or phone number is needed in the detection tier when consistent tokens are provided.

One record's scope is `(authority_id, scheme_code, local_pensioner_id)`. Adapters generate a stable opaque `pensioner_id` for that tuple before the detector, and use the same value in disbursements and certificates. Plain concatenation without escaping is not safe. Keep the reversible local-ID map only in the authorized source system. A person with several entitlements can have several scoped pensioner IDs; do not silently collapse them. Identity tokens may join those entitlements within the authority, not imply duplicate-payment fraud.

Integration's authority-scoped, key-versioned HMAC tokens are compatible with exact-equality joins if a field-domain token is reused consistently across feeds within the authority. Distinct domains for identity, bank, mobile and PAN prevent accidental cross-type equality. Token key version mismatch must fail closed or require an explicit trusted remapping. Do not expose tokens in officer-facing logs. The legacy column names below carry opaque tokens, not raw identifiers, in tokenized deployments.

## Required pension master values

Hard requirements: unique nonblank `pensioner_id`, nonblank `scheme_code`, `full_name` for fuzzy matching, and a declared snapshot in the envelope. The legacy runner currently expects all listed headers even when optional values are blank. `dob`, `gender`, `address`, `district`, `state`, `bank_account`, `mobile`, `aadhaar_number`, `pan`, `ifsc`, `monthly_amount`, `pension_start_date`, `pension_status` may be blank; missing matching keys disable that join rather than match blank keys. Production validation must reject malformed nonblank dates, numeric values, duplicate IDs and conflicting master rows. The frozen implementation does not yet enforce every one of these validations; the production runner must.

An authority without lawfully usable names can use exact token reconciliation, but must not claim the fuzzy-link validation results. District is a blocking aid, not an immutable identity property. Cross-district exceptions need explicit policy and separate validation.

## CSV shapes

UTF-8, header row, comma-separated RFC4180 quoting. Dates `YYYY-MM-DD`, month `YYYY-MM`, timestamps ISO8601 with timezone, amounts decimal currency units. Empty field means unknown, never zero. No magic `NULL`, `N/A`, `0` or1970 default date. Explicit real zero counts/amounts differ from missing.

### `pension_master.csv`

`pensioner_id, full_name, dob, gender, aadhaar_number, pan, bank_account, ifsc, mobile, address, district, state, scheme_code, monthly_amount, pension_start_date, pension_status`

### `pension_disbursements.csv`

`pensioner_id, month, amount, credit_date, bank_account`

### `aadhaar_registry.csv`

`aadhaar_number, name, dob, gender, address, mobile, enrolment_date, last_update_date`

### `death_registry.csv`

`registration_no, deceased_name, dob, gender, date_of_death, registration_date, place_of_death, district, aadhaar_number`

### `birth_register.csv`

`registration_no, child_name, dob, gender, father_name, mother_name, district, registration_date`

### `marriage_register.csv`

`registration_no, spouse1_name, spouse2_name, marriage_date, registration_date, district`

### `vaccination_records.csv`

`aadhaar_number, name, dob, vaccine, dose_no, vaccination_date, centre, district`

### `education_records.csv`

`person_name, dob, qualification, institution, year_of_passing, district`

### `gst_registrations.csv`

`gstin, legal_name, pan, registration_date, status, district`

### `electoral_roll.csv`

`epic_number, name, dob, gender, address, district, status, deletion_date`

### `passport_registry.csv`

`passport_no, name, dob, issue_date, expiry_date, district`

### `driving_licence.csv`

`dl_number, name, dob, issue_date, valid_upto, vehicle_class, district`

### `vehicle_rc.csv`

`registration_no, owner_name, owner_aadhaar, vehicle_class, registration_date, fitness_upto, district`

### `toll_fastag.csv`

`tag_id, vehicle_plate, txn_timestamp, toll_plaza, amount`

### `bank_kyc.csv`

`account_number, name, dob, account_opened, last_kyc_refresh, nominee_registered, account_status`

### `bank_transactions.csv`

`account_number, txn_date, txn_type, amount, channel, narration`

### `tax_pan_activity.csv`

`pan, financial_year, itr_filed, filing_date`

### `epfo_uan.csv`

`uan, name, dob, aadhaar_number, status, last_contribution_month, pension_scheme_linked`

### `nps_accounts.csv`

`pran, name, dob, status, last_contribution_month, tier`

### `lic_insurance.csv`

`policy_no, name, dob, premium_amount, premium_frequency, last_premium_date, status`

### `ration_pds.csv`

`ration_card_no, member_name, member_aadhaar, relationship, month, offtake_kg, district`

### `lpg_refills.csv`

`consumer_id, consumer_name, address, booking_date, delivery_date, subsidy_amount`

### `pmjay_claims.csv`

`pmjay_id, patient_name, dob, gender, hospital_name, admission_date, discharge_date, outcome, claim_amount, district`

### `hospital_records.csv`

`patient_name, dob, gender, admit_date, discharge_date, outcome, hospital_name, district`

### `mgnrega_work.csv`

`job_card_no, name, district, month, workdays, wages_paid, payment_date`

### `municipal_property.csv`

`property_id, owner_name, address, district, annual_tax, last_paid_date, mutation_date`

### `telecom_activity.csv`

`mobile, month, calls_made, sms_sent, data_mb, last_activity_date`

### `utility_bills.csv`

`consumer_id, consumer_name, service_address, month, units_kwh, bill_paid_date`

### `life_certificates.csv`

`pensioner_id, certificate_id, submission_date, channel, status`

## Exact join domains

| Token domain | Legacy columns sharing the token |
|---|---|
| Pension entitlement | pensioner_id in pension_master, pension_disbursements, life_certificates |
| Identity | aadhaar_number in pension_master/aadhaar_registry/death_registry/vaccination_records/epfo_uan; owner_aadhaar in vehicle_rc; member_aadhaar in ration_pds |
| Bank | bank_account in pension_master/pension_disbursements; account_number in bank_kyc/bank_transactions |
| Mobile | mobile in pension_master/aadhaar_registry/telecom_activity |
| PAN | pan in pension_master/tax_pan_activity/gst_registrations |
| Vehicle plate | registration_no in vehicle_rc; vehicle_plate in toll_fastag |

Source-specific record IDs are namespaced by feed and authority. Other references use name/date/address linkage, not arbitrary ID equality. Household ration, LPG and utility activity cannot establish a person's continued life. Bank/SIM/toll/insurance activity may reflect authorized or unauthorized family use, not personal presence. Bank DORMANT status is never death evidence.

## Missing feeds and time

Optional feeds may be absent or headers-only. The production envelope must distinguish `unavailable`, `partial`, `complete_no_records` and `complete`; record an observed coverage interval. Absence of a file is not evidence of no activity. A blank date means unknown, not an old date. Missing feed rows must not be manufactured. A feed that is stale must be marked stale by coverage metadata, not treated as current silence. Existing frozen feature extraction lacks completeness-aware features and must not be advertised as meeting this production contract yet.

`death_date`, `registration_date`, source `arrival_time`, snapshot date and payment-stop date are separate facts. No arrival date is inferred from registration date. Exclude future observations from a snapshot unless labeled as future scheduled events. Employment work month is distinct from delayed wage payment date. Certificate acceptance and expiry are scheme policy inputs, not one universal annual date. Never interpret missing a certificate as proof of death.

## Outputs

Frozen benchmark output remains `flagged_pensioners.csv` with only `pensioner_id,score`, all master IDs exactly once, ranked descending, score finite in[0,1]. V4 scores are review priorities, not calibrated death probabilities. Fixed operating threshold is0.5 after a frozen monotonic transform.

Production output is a separate versioned JSONL/CSV review contract:

- `authority_id`, `scheme_code`, `pensioner_id`, `run_id`, `model_version`, `feature_version`, `snapshot_date`.
- `review_priority` finite in[0,1], `operating_threshold`, `decision=review|no_review|insufficient_evidence`.
- Separate `payment_continuation=observed|not_observed|unknown`, `last_credit_date`; do not use ACTIVE/STOPPED status alone.
- `reason_codes` such as IDENTITY_LINKED_DEATH_RECORD, DOCUMENTARY_DATE_CONFLICT, PERSONAL_ACTIVITY_CESSATION, HOUSEHOLD_ACTIVITY_ONLY, CERTIFICATE_MISSING_NOT_PROOF, FEED_COVERAGE_INCOMPLETE, PAYMENT_CONTINUES_AFTER_DEATH.
- `evidence_refs`: feed, source_record_id/hash, observed event date, source arrival date, linkage method and confidence. No raw identity values or free-text secrets in reasons.
- `coverage_warnings`, `human_review_required=true`, `automatic_payment_action=false`.

These reason codes must be grounded in actual extracted evidence, not inferred from a score. The current experimental runner emits a short batch note and limited top-row free-text diagnostic reasons only. It does not yet produce complete per-row structured reasons or the full production output. Integration can implement the schema now, but must keep it explicitly unavailable until the detector supplies it.

## Operational boundary

Immutable input; bounded-memory batch runner; idempotent run_id and content digest; no network dependence at scoring time. A partial run is not published as final. Atomically publish the validated output plus manifest. Never accept an uploaded executable model or pickle. Production model JSON plus independently provisioned expected digest must be verified from read-once bytes. Frozen experimental pickle scripts are local research only and do not enforce that verification themselves.

Human review, documentary reconciliation, appeal and reinstatement are outside automatic scoring. Missing or contradictory evidence must remain visible. There is no payment-stop endpoint in the detector. Population-scale and cross-scheme accuracy require their own tests.
