import tempfile,unittest
from pathlib import Path
from datetime import date
from detector.aggregate_store import dump,load,StoreError,encode,decode
class StoreTests(unittest.TestCase):
 def test_roundtrip(self):
  a={'dates':{'account':{202611:[(date(2026,11,1),1.5)]}},'set':{1,2},'list':[{'x':None}],'scalar':4}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.db';dump(a,p);self.assertEqual(load(p),a)
 def test_no_replace(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.db';dump({},p)
   with self.assertRaises(StoreError):dump({},p)
 def test_executable_rejected(self):
  with self.assertRaises(StoreError):decode({'$eval':'print(1)'})
 def test_type_rejected(self):
  with self.assertRaises(StoreError):encode(lambda:None)
 def test_nonfinite(self):
  with self.assertRaises(StoreError):encode(float('nan'))
 def test_depth(self):
  a=None
  for _ in range(40):a=[a]
  with self.assertRaises(StoreError):encode(a)
if __name__=='__main__':unittest.main()
