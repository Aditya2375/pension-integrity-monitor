"""Deterministic global documentary assignment with explicit unresolved results.

Keep all tied/alternative candidates from linkage. A claimant that loses its
first candidate remains eligible for the next candidate. No record vanishes.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Candidate:
    pensioner_id: str
    record_id: str
    confidence: float
    source_sequence: int
    exact: bool = False

def assign(pensioner_ids, candidates):
    ids=list(pensioner_ids)
    if len(set(ids))!=len(ids):raise ValueError('Duplicate pensioner ID')
    known=set(ids);edges=[];seen=set()
    for c in candidates:
        if c.pensioner_id not in known or not c.record_id:raise ValueError('Unknown assignment endpoint')
        if not math.isfinite(c.confidence) or not 0<=c.confidence<=1:raise ValueError('Invalid confidence')
        if type(c.source_sequence) is not int or c.source_sequence<0:raise ValueError('Invalid source sequence')
        key=(c.pensioner_id,c.record_id)
        if key in seen:raise ValueError('Duplicate candidate edge')
        seen.add(key);edges.append(c)
    # Exact-ID conflicts are not silently resolved by arbitrary record order.
    exact_owners={}
    for c in edges:
        if c.exact:exact_owners.setdefault(c.record_id,set()).add(c.pensioner_id)
    conflict_ids={p for owners in exact_owners.values() if len(owners)>1 for p in owners}
    conflict_records={r for r,owners in exact_owners.items() if len(owners)>1}
    edges.sort(key=lambda c:(not c.exact,-c.confidence,c.source_sequence,c.pensioner_id,c.record_id))
    result={pid:{'status':'unmatched','record_id':None,'confidence':None} for pid in ids};used=set()
    for pid in conflict_ids:result[pid]['status']='exact_identity_conflict'
    for c in edges:
        if c.record_id in conflict_records or c.pensioner_id in conflict_ids:continue
        if result[c.pensioner_id]['record_id'] is not None or c.record_id in used:continue
        result[c.pensioner_id]={'status':'exact' if c.exact else 'matched','record_id':c.record_id,'confidence':c.confidence}
        used.add(c.record_id)
    candidate_ids={c.pensioner_id for c in edges}
    for pid in candidate_ids:
        if result[pid]['status']=='unmatched':result[pid]['status']='candidate_conflict_unresolved'
    return result
