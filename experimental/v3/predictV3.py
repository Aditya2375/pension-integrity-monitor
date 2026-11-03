"""Apply frozen development-trained classifier to extracted, unlabeled features.
Use only the trusted locally produced model file. Never unpickle an uploaded model.
"""
import csv,json,sys,pickle,os
import pandas as pd
model_path, dataset = sys.argv[1:3]
model, columns, _ = pickle.load(open(model_path,'rb'))
threshold=0.5
features=pd.read_csv(os.path.join(dataset,'features.csv'))
scores=model.predict_proba(features[columns])[:,1]
rows=sorted(zip(features.pensioner_id,scores),key=lambda r:-r[1])
with open(os.path.join(dataset,'flagged_pensioners.csv'),'w',newline='') as f:
 w=csv.writer(f);w.writerow(['pensioner_id','score']);w.writerows((pid,round(float(score),8)) for pid,score in rows)
with open(os.path.join(dataset,'reasoning.txt'),'w') as f:
 f.write('Frozen classifier uses documentary reconciliation, identity match quality, personal activity cessation, household activity, life-certificate history and payment continuation. Scores rank review candidates, never authorize payment cancellation. Operating threshold: 0.5. Development-trained model; independent validation required. No truth file is read by this program.\n')
print(json.dumps({'records':len(rows),'review_candidates':int(sum(s>=threshold for _,s in rows)),'threshold':threshold}))
