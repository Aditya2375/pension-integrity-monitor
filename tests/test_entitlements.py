import unittest
from detector.entitlements import group_entitlements
class EntitlementTests(unittest.TestCase):
 def test_multiple_lawful_pensions(self):
  rows=[{'pensioner_id':'A','scheme_code':'OPS','identity_token':'t','dob':'1950-01-01'},{'pensioner_id':'B','scheme_code':'StateWidow','identity_token':'t','dob':'1950-01-01'}]
  a=group_entitlements(rows,authority_id='auth',key_version='v1');self.assertEqual(len(a),1);self.assertEqual(a[0]['entitlement_ids'],['A','B']);self.assertFalse(a[0]['duplicate_payment_finding'])
 def test_blank_not_grouped(self):
  rows=[{'pensioner_id':'A','scheme_code':'OPS'},{'pensioner_id':'B','scheme_code':'OPS'}];self.assertEqual(len(group_entitlements(rows,authority_id='a',key_version='v')),2)
 def test_conflict(self):
  rows=[{'pensioner_id':'A','scheme_code':'OPS','identity_token':'t','dob':'1950-01-01'},{'pensioner_id':'B','scheme_code':'OPS','identity_token':'t','dob':'1951-01-01'}];self.assertTrue(group_entitlements(rows,authority_id='a',key_version='v')[0]['identity_conflict'])
if __name__=='__main__':unittest.main()
