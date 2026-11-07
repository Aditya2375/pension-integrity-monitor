"""Review-only data-model inference. Digest supplied by trusted run config."""
import csv,sys,json,os
from pathlib import Path
root=Path(__file__).resolve().parents[2]
if str(root) not in sys.path:sys.path.insert(0,str(root))
from detector.model_json import ReviewModel
model_path,expected_digest,dataset=sys.argv[1:4]
model=ReviewModel.load(model_path,expected_sha256=expected_digest)
rows=[]
with open(Path(dataset)/'features.csv',newline='') as f:
 for r in csv.DictReader(f):
  if not r.get('pensioner_id'):raise ValueError('missing ID')
  rows.append((r['pensioner_id'],model.priority(r)))
if len({r[0] for r in rows})!=len(rows):raise ValueError('duplicate ID')
rows.sort(key=lambda r:(-r[1],r[0]))
with open(Path(dataset)/'flagged_pensioners.csv','w',newline='') as f:
 w=csv.writer(f);w.writerow(['pensioner_id','score']);w.writerows((pid,round(score,8)) for pid,score in rows)
(Path(dataset)/'reasoning.txt').write_text('V5 frozen review ranking. Uses documentary identity/date evidence, personal versus household activity, observed payment continuation and missing-feed adversity. Missing certificates are not proof of death. Fixed raw operating threshold is transformed monotonically to score0.5. Scores are priorities, not calibrated death probabilities. No automatic payment action. Unregistered deaths with no observable evidence remain uncertain. Independent accuracy and scheme coverage are not assured.\n')
print(json.dumps({'rows':len(rows),'review_candidates':sum(s>=.5 for _,s in rows)}))
