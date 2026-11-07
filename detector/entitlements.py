"""Authority-scoped person groups, separate from pension entitlement IDs.

One person may lawfully receive several pensions. A unique identity-token
match can supply the same death evidence to those entitlements, but cannot
establish duplicate-payment fraud. Conflicting identity facts need review.
"""
from collections import defaultdict

def group_entitlements(rows,*,authority_id,key_version):
 if not authority_id or not key_version:raise ValueError('Authority and key version required')
 groups=defaultdict(list);ids=set()
 for r in rows:
  pid=r.get('pensioner_id');scheme=r.get('scheme_code')
  if not pid or not scheme or pid in ids:raise ValueError('Invalid entitlement scope')
  ids.add(pid);token=r.get('identity_token') or r.get('aadhaar_number') or ''
  key=('identity',authority_id,key_version,token) if token else ('entitlement',authority_id,key_version,pid)
  groups[key].append(r)
 result=[]
 for key,members in sorted(groups.items()):
  dobs={r['dob'] for r in members if r.get('dob')}
  genders={r['gender'].casefold() for r in members if r.get('gender')}
  result.append({'group_key':key,'entitlement_ids':sorted(r['pensioner_id'] for r in members),'schemes':sorted(set(r['scheme_code'] for r in members)),'identity_conflict':len(dobs)>1 or len(genders)>1,'duplicate_payment_finding':False})
 return result
