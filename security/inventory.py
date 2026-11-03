"""Generate a deterministic CycloneDX runtime inventory from a CLEAN locked env.

Run: python security/inventory.py > security/sbom.cdx.json
Inventory is a component/relationship inventory, not certification or a CVE scan.
"""
import importlib.metadata as meta
import json
import re

ROOTS = ('flask', 'werkzeug', 'gunicorn')

def main():
    pending, components, depends = list(ROOTS), {}, {}
    while pending:
        name = pending.pop()
        name = re.sub('[-_.]+', '-', name).lower()
        if name in components:
            continue
        dist = meta.distribution(name)
        metadata = dist.metadata
        ref = f'pkg:pypi/{name}@{dist.version}'
        license_id = metadata.get('License-Expression')
        legacy = metadata.get('License')
        # Older distributions declare classifiers instead of an SPDX field.
        # IDs below were also checked against their shipped licence text.
        if not license_id and name in {'blinker', 'itsdangerous', 'jinja2'}:
            license_id = {'blinker': 'MIT', 'itsdangerous': 'BSD-3-Clause', 'jinja2': 'BSD-3-Clause'}[name]
        licenses = ([{'license': {'id': license_id}}] if license_id else
                    [{'license': {'name': legacy}}] if legacy else [])
        components[name] = {'type': 'library', 'bom-ref': ref, 'name': name,
                            'version': dist.version, 'purl': ref}
        if licenses:
            components[name]['licenses'] = licenses
        required = []
        for requirement in dist.requires or []:
            # Resolve markers using packaging, which is gunicorn's runtime dep.
            from packaging.requirements import Requirement
            req = Requirement(requirement)
            if req.marker is None or req.marker.evaluate({'extra': ''}):
                dep = re.sub('[-_.]+', '-', req.name).lower()
                pending.append(dep)
                required.append(dep)
        depends[name] = required
    payload = {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
               'components': [components[k] for k in sorted(components)],
               'dependencies': [{'ref': components[k]['bom-ref'],
                                 'dependsOn': sorted(components[d]['bom-ref'] for d in depends[k])}
                                for k in sorted(components)]}
    print(json.dumps(payload, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
