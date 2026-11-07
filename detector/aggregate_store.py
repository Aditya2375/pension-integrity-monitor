"""Local data-only aggregate store. Never deserializes Python objects or code.

SQLite format for independently produced research aggregates. This is not a
source-data authorization mechanism. Treat source uploads separately.
"""
import json,math,sqlite3,os,tempfile
from datetime import date
from pathlib import Path

class StoreError(ValueError):pass

def encode(v,depth=0):
 if depth>32:raise StoreError('Maximum nesting exceeded')
 if v is None or type(v) in (str,bool,int):return v
 if type(v) is float:
  if not math.isfinite(v):raise StoreError('Nonfinite value')
  return v
 if type(v) is date:return {'$date':v.isoformat()}
 if type(v) in (list,tuple,set):return {'$'+type(v).__name__:[encode(x,depth+1) for x in v]}
 if type(v) is dict:return {'$dict':[[encode(k,depth+1),encode(a,depth+1)] for k,a in v.items()]}
 raise StoreError('Unsupported value type')

def decode(v,depth=0):
 if depth>32:raise StoreError('Maximum nesting exceeded')
 if v is None or type(v) in (str,bool,int):return v
 if type(v) is float:
  if not math.isfinite(v):raise StoreError('Nonfinite value')
  return v
 if type(v) is not dict or len(v)!=1:raise StoreError('Invalid value encoding')
 k,a=next(iter(v.items()))
 if k=='$date':
  try:return date.fromisoformat(a)
  except (ValueError,TypeError):raise StoreError('Invalid date') from None
 if k in ('$list','$tuple','$set'):
  if not isinstance(a,list):raise StoreError('Invalid collection')
  result=[decode(x,depth+1) for x in a]
  try:return result if k=='$list' else tuple(result) if k=='$tuple' else set(result)
  except TypeError:raise StoreError('Invalid set entry') from None
 if k=='$dict':
  if not isinstance(a,list):raise StoreError('Invalid dictionary')
  out={}
  for pair in a:
   if not isinstance(pair,list) or len(pair)!=2:raise StoreError('Invalid dictionary pair')
   key=decode(pair[0],depth+1)
   try:
    if key in out:raise StoreError('Duplicate dictionary key')
    out[key]=decode(pair[1],depth+1)
   except TypeError:raise StoreError('Invalid dictionary key') from None
  return out
 raise StoreError('Unknown value encoding')

def dump(aggregates,path):
 path=Path(path)
 if path.exists():raise StoreError('Output exists')
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.aggregates-',dir=path.parent);os.close(fd)
 try:
  c=sqlite3.connect(tmp)
  try:
   c.execute('CREATE TABLE metadata (name TEXT PRIMARY KEY, kind TEXT NOT NULL)')
   c.execute('CREATE TABLE entries (name TEXT NOT NULL, ordinal INTEGER NOT NULL, key_json TEXT, value_json TEXT NOT NULL, PRIMARY KEY(name,ordinal))')
   for name,value in aggregates.items():
    if type(name) is not str:raise StoreError('Invalid aggregate name')
    kind='dict' if type(value) is dict else 'list' if type(value) is list else 'scalar'
    c.execute('INSERT INTO metadata VALUES (?,?)',(name,kind))
    entries=value.items() if kind=='dict' else enumerate(value) if kind=='list' else [(None,value)]
    for i,(key,item) in enumerate(entries):
     c.execute('INSERT INTO entries VALUES (?,?,?,?)',(name,i,json.dumps(encode(key),allow_nan=False),json.dumps(encode(item),allow_nan=False)))
   c.execute('PRAGMA user_version=1');c.commit()
  finally:c.close()
  os.link(tmp,path)
 finally:Path(tmp).unlink(missing_ok=True)

def load(path,*,max_rows=20000000,max_item_bytes=8*1024*1024):
 uri=Path(path).resolve().as_uri()+'?mode=ro&immutable=1';c=sqlite3.connect(uri,uri=True)
 try:
  c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA query_only=ON')
  if c.execute('PRAGMA user_version').fetchone()[0]!=1:raise StoreError('Unsupported aggregate version')
  if c.execute('SELECT count(*) FROM entries').fetchone()[0]>max_rows:raise StoreError('Row cap exceeded')
  out={}
  for name,kind in c.execute('SELECT name,kind FROM metadata'):
   if kind not in ('dict','list','scalar'):raise StoreError('Invalid aggregate kind')
   value={} if kind=='dict' else []
   for key_json,item_json in c.execute('SELECT key_json,value_json FROM entries WHERE name=? ORDER BY ordinal',(name,)):
    if len(item_json)>max_item_bytes or len(key_json)>max_item_bytes:raise StoreError('Item byte cap exceeded')
    try:key=decode(json.loads(key_json));item=decode(json.loads(item_json))
    except (ValueError,TypeError,RecursionError):raise StoreError('Invalid aggregate entry') from None
    if kind=='dict':
     if key in value:raise StoreError('Duplicate aggregate key')
     value[key]=item
    else:value.append(item)
   if kind=='scalar':
    if len(value)!=1:raise StoreError('Invalid scalar')
    value=value[0]
   out[name]=value
  return out
 finally:c.close()
