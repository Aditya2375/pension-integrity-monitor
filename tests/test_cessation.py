import unittest
from datetime import date,timedelta
from detector.cessation import SourceHistory,summarize,joint
class CessationTests(unittest.TestCase):
 def setUp(self):self.s=date(2026,11,3);self.events=tuple(self.s-timedelta(days=d) for d in range(35,120,7))
 def h(self,complete=True,end=None):return SourceHistory(self.events,self.s-timedelta(days=150),end or self.s,complete)
 def test_joint(self):
  a=joint({'bank':self.h(),'telecom':self.h()},self.s);self.assertTrue(a['aligned_joint_cessation']);self.assertFalse(a['death_confirmed'])
 def test_partial_unknown(self):self.assertEqual(summarize(self.h(False),self.s)['state'],'unknown')
 def test_stale_unknown(self):self.assertEqual(summarize(self.h(end=self.s-timedelta(days=1)),self.s)['state'],'unknown')
 def test_chronic_not_death(self):
  a=SourceHistory((),self.s-timedelta(days=150),self.s,True);self.assertEqual(summarize(a,self.s)['state'],'chronic_low_activity')
 def test_recent_active(self):
  a=SourceHistory(self.events+(self.s,),self.s-timedelta(days=150),self.s,True);self.assertEqual(summarize(a,self.s)['state'],'active')
if __name__=='__main__':unittest.main()
