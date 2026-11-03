"""Authorization boundary for an upstream authenticated, server-owned principal.

Never construct Principal from forms, cookies, X-User, or other client claims.
The IdP adapter must validate issuer/audience/signature/expiry and map roles and
jurisdictions using department-controlled assignments. Shared officer keys are
synthetic-demo only. This module is not an SSO/MFA implementation.
"""
from dataclasses import dataclass

ROLE_ACTIONS = {
    'reviewer': frozenset({'read_case', 'verify', 'record_outcome', 'propose_decision'}),
    'approver': frozenset({'read_case', 'approve_decision', 'resolve_appeal'}),
    'ingestor': frozenset({'ingest'}),
    'auditor': frozenset({'read_audit'}),
}

@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset
    jurisdictions: frozenset

def authorized(principal, action, jurisdiction):
    return (isinstance(principal, Principal) and bool(principal.subject.strip())
            and jurisdiction in principal.jurisdictions
            and any(action in ROLE_ACTIONS.get(role, ()) for role in principal.roles))

def independent_approval(proposer, approver, jurisdiction):
    return (authorized(proposer, 'propose_decision', jurisdiction)
            and authorized(approver, 'approve_decision', jurisdiction)
            and proposer.subject != approver.subject)
