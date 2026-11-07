import hashlib,json,tempfile,unittest
from pathlib import Path
from detector.model_json import ReviewModel,ModelError
class ModelTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.p=Path(self.t.name)/'model.json'
  self.data={'format':'pension-review-gbt-v1','features':['x'],'baseline':0.,'operating_threshold':.5,'trees':[[{'value':0.,'feature_idx':0,'num_threshold':1.,'missing_go_to_left':1,'left':1,'right':2,'is_leaf':0,'is_categorical':0},{'value':-2.,'feature_idx':0,'num_threshold':0.,'missing_go_to_left':0,'left':0,'right':0,'is_leaf':1,'is_categorical':0},{'value':2.,'feature_idx':0,'num_threshold':0.,'missing_go_to_left':0,'left':0,'right':0,'is_leaf':1,'is_categorical':0}]]}
 def load(self):
  b=json.dumps(self.data).encode();self.p.write_bytes(b);return ReviewModel.load(self.p,expected_sha256=hashlib.sha256(b).hexdigest())
 def test_path(self):
  m=self.load();self.assertLess(m.probability({'x':1}),.5);self.assertGreater(m.probability({'x':2}),.5)
 def test_digest(self):
  self.p.write_text('not code')
  with self.assertRaises(ModelError):ReviewModel.load(self.p,expected_sha256='0'*64)
 def test_cycle(self):
  self.data['trees'][0][0]['left']=0
  with self.assertRaises(ModelError):self.load()
 def test_nan(self):
  m=self.load()
  with self.assertRaises(ModelError):m.probability({'x':float('nan')})
 def test_missing_feature(self):
  with self.assertRaises(ModelError):self.load().probability({})
 def test_missing_route(self):self.assertLess(self.load().probability({'x':None}),.5)
 def test_payment_gate(self):
  m=self.load();self.assertAlmostEqual(m.priority({'x':2,'still_paid':0}),m.priority({'x':2,'still_paid':1})*.05)
 def test_categorical_reject(self):
  self.data['trees'][0][0]['is_categorical']=1
  with self.assertRaises(ModelError):self.load()
 def test_duplicate_key(self):
  b=b'{"format":"x","format":"y"}';self.p.write_bytes(b)
  with self.assertRaises(ModelError):ReviewModel.load(self.p,expected_sha256=hashlib.sha256(b).hexdigest())
if __name__=='__main__':unittest.main()
