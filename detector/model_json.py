"""Data-only tree inference with read-once digest verification. Standard library.

Expected digest comes from independently provisioned release configuration,
never from a companion digest submitted by an untrusted uploader.
"""
import hashlib,hmac,json,math,re
from pathlib import Path

MAX_BYTES=16*1024*1024
class ModelError(ValueError):pass

class ReviewModel:
    def __init__(self,data):
        if not isinstance(data,dict) or data.get('format')!='pension-review-gbt-v1':raise ModelError('Unsupported model')
        features=data.get('features');trees=data.get('trees')
        if not isinstance(features,list) or not 1<=len(features)<=512 or len(set(features))!=len(features) or not all(isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}',x) for x in features):raise ModelError('Invalid features')
        if not isinstance(trees,list) or not 1<=len(trees)<=2000:raise ModelError('Invalid tree count')
        self.baseline=self._number(data.get('baseline'))
        self.threshold=self._number(data.get('operating_threshold'))
        if not 0<self.threshold<1:raise ModelError('Invalid threshold')
        self.features=tuple(features);self.trees=[]
        for tree in trees:
            if not isinstance(tree,list) or not 1<=len(tree)<=4095:raise ModelError('Invalid nodes')
            checked=[]
            for i,n in enumerate(tree):
                if not isinstance(n,dict):raise ModelError('Invalid node')
                value=self._number(n.get('value'));threshold=self._number(n.get('num_threshold'))
                for k in ('feature_idx','left','right','missing_go_to_left','is_leaf','is_categorical'):
                    if type(n.get(k)) is not int:raise ModelError('Invalid integer field')
                if n['is_categorical']!=0 or n['is_leaf'] not in (0,1) or n['missing_go_to_left'] not in (0,1):raise ModelError('Unsupported split')
                if not n['is_leaf']:
                    if not 0<=n['feature_idx']<len(features):raise ModelError('Feature out of range')
                    if not i<n['left']<len(tree) or not i<n['right']<len(tree) or n['left']==n['right']:raise ModelError('Invalid tree edges')
                checked.append((value,n['feature_idx'],threshold,n['missing_go_to_left'],n['left'],n['right'],n['is_leaf']))
            reached=set();stack=[0]
            while stack:
                i=stack.pop()
                if i in reached:raise ModelError('Node has multiple parents')
                reached.add(i);n=checked[i]
                if not n[6]:stack.extend([n[4],n[5]])
            if len(reached)!=len(checked):raise ModelError('Unreachable node')
            self.trees.append(tuple(checked))
        self.trees=tuple(self.trees)
    @staticmethod
    def _number(v):
        if type(v) not in (int,float) or not math.isfinite(v):raise ModelError('Invalid numeric value')
        return float(v)
    @classmethod
    def load(cls,path,*,expected_sha256):
        if not isinstance(expected_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):raise ModelError('Trusted digest required')
        with Path(path).open('rb') as f:payload=f.read(MAX_BYTES+1)
        if len(payload)>MAX_BYTES:raise ModelError('Model exceeds byte cap')
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(),expected_sha256):raise ModelError('Model integrity mismatch')
        def pairs(items):
            out={}
            for k,v in items:
                if k in out:raise ModelError('Duplicate JSON key')
                out[k]=v
            return out
        try:data=json.loads(payload,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ModelError('Nonfinite JSON number')))
        except (UnicodeDecodeError,json.JSONDecodeError,RecursionError) as e:raise ModelError('Invalid model JSON') from None
        return cls(data)
    def probability(self,row):
        values=[]
        for name in self.features:
            if name not in row:raise ModelError('Missing feature')
            v=row[name]
            if v is None or v=='':values.append(None);continue
            try:v=float(v)
            except (TypeError,ValueError):raise ModelError('Invalid feature value') from None
            if not math.isfinite(v):raise ModelError('Nonfinite feature value')
            values.append(v)
        total=self.baseline
        for tree in self.trees:
            idx=0
            while True:
                v,feature,threshold,miss,left,right,leaf=tree[idx]
                if leaf:total+=v;break
                x=values[feature];idx=(left if miss else right) if x is None else (left if x<=threshold else right)
        if total>=0:return 1/(1+math.exp(-total))
        e=math.exp(total);return e/(1+e)
    def priority(self,row):
        p=self.probability(row);p=min(1-1e-12,max(1e-12,p));odds=p/(1-p);cut=self.threshold/(1-self.threshold)
        score=odds/(odds+cut)
        if row.get('still_paid') not in (1,1.0,'1'):score*=.05
        return score
