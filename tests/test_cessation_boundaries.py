import unittest
from datetime import date,timedelta
from detector.cessation import summarize,SourceHistory
class Boundaries(unittest.TestCase):
 def test_window_boundary_is_not_lost(self):
  s=date(2026,11,3);events=tuple(s-timedelta(days=d) for d in [30,40,50,60,70,80,90])
  a=summarize(SourceHistory(events,s-timedelta(days=150),s,True),s)
  self.assertEqual(a['prior_events']+a['recent_events'],len(events))
if __name__=='__main__':unittest.main()
