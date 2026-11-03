import unittest
from detector.identity import normalize_name,similarity
class IdentityTests(unittest.TestCase):
 def test_devanagari(self):self.assertEqual(similarity('राम पाटिल','राम पाटिल'),1.)
 def test_arabic(self):self.assertEqual(similarity('محمد علی','محمد علی'),1.)
 def test_mixed(self):self.assertLess(similarity('राम Patil','श्याम Patil'),.8)
 def test_transliteration_no_guess(self):self.assertEqual(similarity('राम पाटिल','Ram Patil'),0.)
 def test_blank(self):self.assertEqual(similarity('',''),0.)
 def test_honorific(self):self.assertEqual(normalize_name('Shri Ramesh Patil'),'ramesh patil')
 def test_order(self):self.assertEqual(similarity('Patil Ramesh','Ramesh Patil'),1.)
 def test_fullwidth(self):self.assertEqual(normalize_name('ＲＡＭ'),'ram')
if __name__=='__main__':unittest.main()
