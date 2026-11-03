# Integration adversarial review: d153094

2026-11-04. 40 existing tests pass; this is not a passing security verdict.

## Reproduced blockers

1. Same identifier, same key, different feed kind generates different HMAC tokens (`pensioner:identity_token` vs `death:identity_token`; analogous bank issue). Exact joins fail. Use stable identifier-domain namespace shared only within an authorised authority, with explicit key/namespace version. Canonicalise identifier formats consistently. Key rotation must reprocess/link snapshots under controlled migration, not silently mix tokens.
2. `SENSITIVE_SOURCE_COLUMNS` is declared but unused. Mapping `full_name` to `aadhaar_number` with no sensitive policy publishes the raw source number. Reproduced with synthetic 123456789012. Enforce raw-source policy regardless of target; do not rely only on column spelling. Prevent mapping/default routes around protected domains and require reviewed signed contracts.
3. `authority_reference='FILL-IN'` passes. A free-text string does not establish approved feed authority. The trusted control plane must bind authenticated machine/agency, source contract, purpose, jurisdiction and allowed fields. Templates may validate as templates but cannot enter real-data mode.
4. Positional `zip` silently ignores extra source columns and may tolerate truncated optional layouts. Exact record width must be checked before mapping/filtering.
5. Bridge writes shared `UNAVAILABLE` in identity, account, mobile and PAN columns. Legacy pipeline treats nonempty Aadhaar as exact ID; shared markers must NEVER become join keys. Missingness belongs in separate metadata/null semantics; consumer must ignore placeholder tokens explicitly. It also defaults missing monthly_amount to zero and pension_status to ACTIVE, neither grounded in source. Preserve unknown as unknown.
6. Canonical output mode is 0600; bridge output was reproduced as 0644 under default umask, widening exposure to local users. Set restrictive mode explicitly and stage publication safely.

## Further defects from source inspection

- No exclusive publication lock: a concurrent normalizer can observe just-linked data without manifest, unlink it as an orphan, then either publish conflicting bytes or leave mismatched data/manifest. Only recover orphans while holding the same lock. Use unique immutable version directories and atomic pointer/commit record; fsync parent directories for crash durability, not just file contents.
- Bridge verifies path/hash, then reopens it later; substitution after verification is possible if directory is writable. Use a verified snapshot/file descriptor and compare hash of bytes actually consumed. Bridge output is not atomic, overwrites existing files and accepts source == output, which can destroy input. Reject alias/symlink/path overlap and use no-clobber restricted immutable publication.
- Canonical manifest is a checksum document, not an authenticity signature. A writer who changes data and manifest can pass verification. Tie it to authenticated trusted intake and signed/allowlisted contract; enforce directory ownership.
- Token key accepts any nonempty string; no minimum strength, key ID, agency namespace or migration. Require centrally provisioned high-entropy key material via protected secret injection, no key in manifests/logs. Do not allow arbitrary remote clients to select key env names.
- `max_rows` counts only included rows. Filtered input can consume CPU/time beyond the configured row ceiling. Bound total physical rows/bytes/field lengths, then separately count accepted rows. Source can grow after initial stat; enforce bytes while reading. CSV parser exceptions must be wrapped in non-personal error codes.
- `include_when.column` is not verified against source header/positional names. Missing filter column silently drops all data. Reject rather than publish empty-success feed unless explicitly approved empty snapshot.
- Shared PPO IDs across schemes/authorities can collide; bridge drops scope metadata. Manifest provenance and source-record identity are not retained by legacy ingest; repeated legacy ingestion duplicates append-only tables.
- Hashing full raw rows in a public-ish manifest/CSV is not anonymisation. Low-entropy inputs can be guessed. Restrict raw-record hashes, and use keyed scoped digest where appropriate.

## Retest gate

Add adversarial tests for all reproduced cases, two concurrent normalizers with interleaved publication, source/path swaps, malformed filters/row widths, wrong-agency manifest, weak/wrong/rotated keys, same ID across legitimate feed kinds, cross-authority unlinkability, unknown identifiers/no phantom exact match, restrictive bridge permissions, atomic no-clobber, no fabricated defaults and replay-through-legacy idempotency. Freeze corrected commit for independent review before merging.
