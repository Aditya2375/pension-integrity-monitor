"""Apply frozen development-trained classifier to extracted, unlabeled features.
Use only the trusted locally produced model file. Never unpickle an uploaded model.
"""
import csv,json,sys,pickle,os
import numpy as np
import pandas as pd
model_path, dataset = sys.argv[1:3]
model, columns, operating_threshold = pickle.load(open(model_path,'rb'))
threshold=0.5
features=pd.read_csv(os.path.join(dataset,'features.csv'))
raw=model.predict_proba(features[columns])[:,1]
# Monotonic rescaling exposes the precommitted calibrated operating point at0.5.
# These are review-priority scores, not calibrated probabilities of death.
raw=np.clip(raw,1e-9,1-1e-9)
odds=raw/(1-raw);cut_odds=operating_threshold/(1-operating_threshold)
scores=odds/(odds+cut_odds)
# Payment continuation is observed credit, never the pension status string.
scores=np.where(features['still_paid'].to_numpy()==1,scores,scores*0.05)
rows=sorted(zip(features.pensioner_id,scores),key=lambda r:-r[1])
with open(os.path.join(dataset,'flagged_pensioners.csv'),'w',newline='') as f:
 w=csv.writer(f);w.writerow(['pensioner_id','score']);w.writerows((pid,round(float(score),8)) for pid,score in rows)
with open(os.path.join(dataset,'reasoning.txt'),'w') as f:
 f.write('Frozen classifier uses documentary reconciliation, identity match quality, personal activity cessation, household activity, life-certificate history and payment continuation. Scores rank review candidates, never authorize payment cancellation. Operating threshold: 0.5. Development-trained model; independent validation required. Scores are review priorities, not calibrated death probabilities. Fixed raw operating threshold is recorded in the frozen model artifact. No truth file is read by this program.\n')
print(json.dumps({'records':len(rows),'review_candidates':int(sum(s>=threshold for _,s in rows)),'threshold':threshold}))
