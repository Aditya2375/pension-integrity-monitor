import csv,sys
from pathlib import Path
p=Path(sys.argv[1]); rows={}; fields=['pensioner_id']
for name in ['m_doc','m_n1','m_mg','m_mu','m_lpg']:
 r=csv.DictReader(open(p/(name+'.csv'))); fields += [x for x in r.fieldnames if x!='pensioner_id']
 for a in r: rows.setdefault(a['pensioner_id'],{}).update(a)
with open(p/'matches_v3.csv','w') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows.values())
