"""Verify private artifact bytes against an independently provisioned allowlist.

A digest supplied alongside an untrusted file authenticates nothing. Only use a
trusted, read-only release allowlist provisioned outside uploaded payloads.
Verification does NOT make pickle safe: unpickling still executes code. Prefer
non-executable data formats. Private pickle use requires trusted provenance,
isolated offline execution and an approved exact artifact digest.
"""
import hashlib
import hmac
import re


def verified_bytes(path, expected_sha256, max_bytes):
    """Read once and verify those exact bytes; caller must not reopen path to load."""
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Missing trusted artifact digest')
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError('Invalid artifact size limit')
    with open(path, 'rb') as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Artifact exceeds size limit')
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_sha256):
        raise ValueError('Artifact digest mismatch')
    return data
