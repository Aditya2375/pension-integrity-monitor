"""Feed-health monitoring: freshness against each feed's expected cadence."""
from datetime import datetime
from . import db

def feed_health(conn):
    now = datetime.utcnow()
    out = []
    for f in conn.execute("SELECT * FROM feeds ORDER BY feed_id").fetchall():
        last = f["last_ingest_at"]
        state, age_days = "never_loaded", None
        if last:
            dt = datetime.fromisoformat(last.replace("Z", ""))
            age_days = (now - dt).days
            state = "ok" if age_days <= f["expected_cadence_days"] else "stale"
        out.append({
            "feed_id": f["feed_id"], "name": f["name"], "state": state,
            "last_ingest_at": last, "age_days": age_days,
            "cadence_days": f["expected_cadence_days"],
            "rows_loaded": f["rows_loaded"], "rows_rejected": f["rows_rejected"],
        })
    return out
