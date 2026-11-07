"""Unicode-preserving identity normalization. Not an authentication algorithm.

No transliteration or cross-script equivalence is inferred. Romanized and
native-script variants need authorized aliases or exact identity tokens.
"""
import unicodedata
from difflib import SequenceMatcher
STOPWORDS={'sri','smt','shri','mr','mrs','kumari','dr'}

def normalize_name(value):
 if not isinstance(value,str):return ''
 out=[]
 for c in unicodedata.normalize('NFKC',value).casefold():
  category=unicodedata.category(c)
  if category[0] in ('L','M'):out.append(c)
  else:out.append(' ')
 return ' '.join(t for t in ''.join(out).split() if t not in STOPWORDS)

def scripts(value):
 found=set()
 for c in normalize_name(value):
  if not unicodedata.category(c).startswith('L'):continue
  name=unicodedata.name(c,'')
  found.add(next((s for s in ('LATIN','DEVANAGARI','ARABIC','BENGALI','GUJARATI','GURMUKHI','TAMIL','TELUGU','KANNADA','MALAYALAM','ORIYA','SINHALA','CYRILLIC','GREEK') if s in name),'OTHER'))
 return found

def similarity(a,b):
 a,b=normalize_name(a),normalize_name(b)
 if not a or not b:return 0.
 # Shared romanized surname cannot erase unequal native-script first names.
 if scripts(a)!=scripts(b):return 0.
 ta,tb=a.split(),b.split()
 if sorted(ta)==sorted(tb):return 1.
 used=set();hits=0.
 for x in ta:
  candidates=[(SequenceMatcher(None,x,y).ratio(),j) for j,y in enumerate(tb) if j not in used]
  if not candidates:continue
  score,j=max(candidates);used.add(j);hits+=score
 return .6*hits/max(len(ta),len(tb))+.4*SequenceMatcher(None,' '.join(sorted(ta)),' '.join(sorted(tb))).ratio()
