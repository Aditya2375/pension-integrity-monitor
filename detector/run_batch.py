"""Coverage-aware reconciliation smoke runner, not the experimental classifier.

python -m detector.run_batch --input DIR --output DIR --snapshot YYYY-MM-DD
No external services, executable artifacts or raw identity logging.
"""
import argparse,csv,hashlib,json,os,tempfile
from pathlib import Path
from datetime import date

class BatchError(ValueError):pass

def records(base,name):
 p=base/(name+'.csv')
 if not p.exists():raise BatchError('Required CSV missing: '+name)
 with p.open(newline='',encoding='utf-8-sig') as f:
  r=csv.DictReader(f)
  if not r.fieldnames or len(r.fieldnames)!=len(set(r.fieldnames)):raise BatchError('Invalid CSV headers: '+name)
  for a in r:
   if None in a or any(v is None for v in a.values()):raise BatchError('Malformed CSV row: '+name)
   yield a

def dte(v):
 if not v:return None
 try:return date.fromisoformat(v)
 except ValueError:raise BatchError('Invalid date') from None

def run(source,target,snapshot):
 source,target=Path(source),Path(target);snap=date.fromisoformat(snapshot)
 if target.exists():raise BatchError('Output path exists; use a new run directory')
 master=list(records(source,'pension_master'));byid={}
 for p in master:
  pid=p.get('pensioner_id','')
  if not pid or pid in byid:raise BatchError('Missing or duplicate pensioner ID')
  if not p.get('scheme_code'):raise BatchError('Missing scheme scope')
  byid[pid]=p
 from decimal import Decimal,InvalidOperation
 credits={}
 for r in records(source,'pension_disbursements'):
  if r['pensioner_id'] not in byid:raise BatchError('Payment entitlement missing from master')
  try:a=Decimal(r['amount'])
  except InvalidOperation:raise BatchError('Invalid payment amount') from None
  if not a.is_finite() or a<0:raise BatchError('Invalid payment amount')
  d=dte(r.get('credit_date'))
  if a>0 and d and d<=snap:credits[r['pensioner_id']]=max(d,credits.get(r['pensioner_id'],d))
 deaths={}
 for r in records(source,'death_registry'):
  token=r.get('aadhaar_number','');dd=dte(r.get('date_of_death'));rd=dte(r.get('registration_date'))
  if dd and rd and rd<dd:raise BatchError('Registration precedes death')
  if not token or not dd or dd>snap or (rd and rd>snap):continue
  deaths.setdefault(token,[]).append((dd,r.get('registration_no','')))
 certs={}
 for r in records(source,'life_certificates'):
  d=dte(r.get('submission_date'))
  if r.get('status','').upper()=='VERIFIED' and d and d<=snap:
   certs[r['pensioner_id']]=max(d,certs.get(r['pensioner_id'],d))
 rows=[]
 for pid,p in byid.items():
  hits=deaths.get(p.get('aadhaar_number',''),[]) if p.get('aadhaar_number') else []
  reasons=[];score=0.;decision='insufficient_evidence';payment='unknown';refs=[]
  credit=credits.get(pid)
  if credit:payment='observed' if (snap-credit).days<=92 else 'not_observed'
  if hits:
   dd,rid=min(hits);refs=[{'feed':'death_registry','source_record_id':rid,'event_date':dd.isoformat(),'linkage':'exact_identity_token'}]
   reasons.append('IDENTITY_LINKED_DEATH_RECORD')
   if certs.get(pid) and certs[pid]>dd:reasons.append('DOCUMENTARY_DATE_CONFLICT');decision='review';score=.5
   elif credit and credit>dd and payment=='observed':reasons.append('PAYMENT_CONTINUES_AFTER_DEATH');decision='review';score=.99
   else:decision='no_review';score=.05
  else:reasons.extend(['FEED_COVERAGE_INCOMPLETE','NO_EXACT_DEATH_RECORD_NOT_PROOF_OF_LIFE'])
  rows.append({'pensioner_id':pid,'scheme_code':p['scheme_code'],'review_priority':score,'decision':decision,'payment_continuation':payment,'last_credit_date':credit.isoformat() if credit else None,'reason_codes':reasons,'evidence_refs':refs,'human_review_required':True,'automatic_payment_action':False,'mode':'exact_reconciliation_smoke','snapshot_date':snapshot})
 rows.sort(key=lambda a:(-a['review_priority'],a['pensioner_id']))
 target.parent.mkdir(parents=True,exist_ok=True)
 temp=Path(tempfile.mkdtemp(prefix='.review-',dir=target.parent))
 try:
  with (temp/'reviews.jsonl').open('w') as f:
   for row in rows:f.write(json.dumps(row,sort_keys=True)+'\n')
  with (temp/'flagged_pensioners.csv').open('w',newline='') as f:
   w=csv.writer(f);w.writerow(['pensioner_id','score']);w.writerows((r['pensioner_id'],r['review_priority']) for r in rows)
  manifest={'mode':'exact_reconciliation_smoke','records':len(rows),'snapshot_date':snapshot,'accuracy_claim':False,'behavioural_detection_enabled':False,'coverage_aware':True,'output_sha256':hashlib.sha256((temp/'reviews.jsonl').read_bytes()).hexdigest()}
  (temp/'run_manifest.json').write_text(json.dumps(manifest,indent=2));os.rename(temp,target)
 finally:
  if temp.exists():
   import shutil;shutil.rmtree(temp)
 return manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--snapshot',required=True);a=p.parse_args();print(json.dumps(run(a.input,a.output,a.snapshot)))
if __name__=='__main__':main()
