"""Person-relative joint cessation evidence, never a death determination.

An explicit complete-through bound is required per source. Missingness does
not become silence. Days with zero observed events differ from absent days.
"""
from dataclasses import dataclass
from datetime import date,timedelta
from statistics import median
import math

@dataclass(frozen=True)
class SourceHistory:
    events: tuple
    coverage_start: date
    complete_through: date
    complete: bool

def summarize(history,snapshot,window_days=30,baseline_days=120):
    if not isinstance(snapshot,date) or not 1<=window_days<=90 or not window_days<baseline_days<=730:raise ValueError('Invalid observation window')
    if not history.complete:return {'state':'unknown','reason':'coverage_incomplete'}
    if history.coverage_start>snapshot-timedelta(days=baseline_days) or history.complete_through<snapshot:return {'state':'unknown','reason':'coverage_window_insufficient'}
    events=[]
    for d in history.events:
        if not isinstance(d,date):raise ValueError('Invalid event date')
        if history.coverage_start<=d<=snapshot:events.append(d)
    prior=[d for d in events if window_days<=(snapshot-d).days<baseline_days]
    recent=[d for d in events if 0<=(snapshot-d).days<window_days]
    exposure=baseline_days-window_days
    weekly=[]
    for start in range(window_days,baseline_days,7):weekly.append(sum(start<=(snapshot-d).days<min(start+7,baseline_days) for d in prior))
    rate=len(prior)/exposure
    expected=rate*window_days
    silence_surprise=min(expected,20.) if not recent else 0.
    last=max(events) if events else None
    # An offline baseline is not a sudden disappearance.
    established=len(prior)>=4 and sum(x>0 for x in weekly)>=3
    state='cessation' if established and not recent else 'active' if recent else 'chronic_low_activity'
    return {'state':state,'prior_events':len(prior),'recent_events':len(recent),'baseline_rate_per_day':rate,'expected_recent_events':expected,'capped_silence_surprise':silence_surprise,'last_event':last.isoformat() if last else None,'baseline_active_weeks':sum(x>0 for x in weekly)}

def joint(histories,snapshot,window_days=30):
    parts={k:summarize(v,snapshot,window_days) for k,v in histories.items()}
    stops=[p for p in parts.values() if p['state']=='cessation']
    dates=[date.fromisoformat(p['last_event']) for p in stops]
    return {'sources':parts,'cessation_count':len(stops),'unknown_count':sum(p['state']=='unknown' for p in parts.values()),'last_event_spread_days':(max(dates)-min(dates)).days if len(dates)>1 else None,'aligned_joint_cessation':len(stops)>=2 and (max(dates)-min(dates)).days<=14,'death_confirmed':False}
