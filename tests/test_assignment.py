import random,unittest
from detector.assignment import Candidate,assign
class AssignmentTests(unittest.TestCase):
 def test_next_tied(self):
  a=assign(['P1','P2'],[Candidate('P1','R1',1.,0),Candidate('P2','R1',1.,0),Candidate('P2','R2',1.,1)])
  self.assertEqual(a['P1']['record_id'],'R1');self.assertEqual(a['P2']['record_id'],'R2')
 def test_no_drop(self):
  a=assign(['P1','P2','P3'],[Candidate('P1','R1',1.,0),Candidate('P2','R1',.9,0)])
  self.assertEqual(set(a),{'P1','P2','P3'});self.assertEqual(a['P2']['status'],'candidate_conflict_unresolved');self.assertEqual(a['P3']['status'],'unmatched')
 def test_shuffle_invariant(self):
  c=[Candidate('P1','R1',1.,0),Candidate('P2','R1',1.,0),Candidate('P2','R2',1.,1)];a=assign(['P1','P2'],c)
  for i in range(30):random.Random(i).shuffle(c);self.assertEqual(assign(['P2','P1'],c),a)
 def test_exact_priority(self):
  a=assign(['P1','P2'],[Candidate('P1','R1',1.,0),Candidate('P2','R1',1.,0,True)]);self.assertEqual(a['P2']['record_id'],'R1')
 def test_exact_conflict(self):
  a=assign(['P1','P2'],[Candidate('P1','R1',1.,0,True),Candidate('P2','R1',1.,0,True)]);self.assertTrue(all(x['status']=='exact_identity_conflict' for x in a.values()))
if __name__=='__main__':unittest.main()
