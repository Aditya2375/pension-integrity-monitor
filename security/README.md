# Security support package

This package does not silently patch the portal. See docs/security/PORTAL_INTEGRATION.md. Review verdict and release gates: docs/security/CRITIC_REVIEW.md. No production approval is implied by these files.

## Repeatable runtime dependency installation

Tested CPython 3.10.12 on Linux. Runtime direct requirements remain in root requirements.txt; security/requirements.lock pins the complete resolved runtime dependency set with artifact SHA-256 hashes. This is reproducible dependency selection, not a claim of byte-identical operating-system/container builds. The lock is platform/interpreter specific until other platforms are tested. Compiler/base OS and private/native detector artifacts need their own pinned digest/provenance.

```
python3.10 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r security/requirements.lock
.venv/bin/python -m pip check
.venv/bin/python security/inventory.py > /tmp/sbom.cdx.json
cmp security/sbom.cdx.json /tmp/sbom.cdx.json
```

Prepare a department-approved offline wheelhouse on the target architecture:

```
.venv/bin/python -m pip download --only-binary=:all: --require-hashes -r security/requirements.lock -d wheelhouse
.venv/bin/python -m pip install --no-index --find-links wheelhouse --require-hashes -r security/requirements.lock
```

Record interpreter/OS/image digest, wheel hashes, source commit, model/evidence manifest and local build command with each release. Do not include private feed/model files in the software archive. Run without network after approved dependencies are imported. Do not call an unpinned Docker tag reproducible.

## Verification commands

Install test/audit tools separately in a development environment; these tools are not production runtime dependencies. Record their versions with each result.

```
python -m pytest -q
python -m pip_audit --disable-pip -r security/requirements.lock --format json
python -m bandit -r app.py pim scripts security
```

The checked-in dependency audit is a time-bound vulnerability-database result for nine runtime components, not a guarantee of no vulnerabilities. Repeat before release. The SBOM excludes experimental detector dependencies and the operating system, which require separate inventories before combined release.

## Operational controls

Deployment must provision TLS, secret custody/rotation, named SSO/MFA, backup encryption, read-only source storage, quotas, audit checkpoint destination, clock sync and on-call reporting. No password/security-setting changes or external notifications are performed by this package. No paid hosting is required by these notes; a free synthetic demo is not a suitable real-data hosting approval.
