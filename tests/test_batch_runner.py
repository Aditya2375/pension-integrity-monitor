import unittest,tempfile,csv,json
from pathlib import Path
from detector.run_batch import run,BatchError
class BatchTests(unittest.TestCase):
 def test_empty_optional(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);src=p/'in';src.mkdir()
   data={'pension_master':[['pensioner_id','scheme_code','full_name','aadhaar_number'],['opaque','OPS','Test Person','token']], 'pension_disbursements':[['pensioner_id','amount','credit_date'],['opaque','1000','2026-11-01']], 'death_registry':[['registration_no','aadhaar_number','date_of_death','registration_date'],['R1','token','2026-10-01','2026-10-05']], 'life_certificates':[['pensioner_id','status','submission_date']]}
   for n,r in data.items():
    with (src/(n+'.csv')).open('w',newline='') as f:csv.writer(f).writerows(r)
   m=run(src,p/'out','2026-11-03');self.assertFalse(m['accuracy_claim']);r=json.loads((p/'out/reviews.jsonl').read_text());self.assertEqual(r['decision'],'review');self.assertFalse(r['automatic_payment_action'])
 def test_blank_join_not_matching(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);src=p/'in';src.mkdir()
   for n,t in {'pension_master':'pensioner_id,scheme_code,full_name,aadhaar_number\nX,OPS,Test Person,\n','death_registry':'registration_no,aadhaar_number,date_of_death,registration_date\nR1,,2026-01-01,2026-01-02\n','pension_disbursements':'pensioner_id,amount,credit_date\n','life_certificates':'pensioner_id,status,submission_date\n'}.items():(src/(n+'.csv')).write_text(t)
   run(src,p/'out','2026-11-03');r=json.loads((p/'out/reviews.jsonl').read_text());self.assertEqual(r['decision'],'insufficient_evidence')
if __name__=='__main__':unittest.main()
