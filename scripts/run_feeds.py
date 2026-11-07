"""Headless feed runner: ingest a directory of feed CSVs, run the pipeline,
export ranked flags. Usage:
  python scripts/run_feeds.py --dir incoming/ --out flags.csv
Files must be named <feed_id>.csv (e.g. death_registry.csv)."""
import argparse, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pim import db, ingest, pipeline
from scripts.export_flags import export

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="flags.csv")
    a = ap.parse_args()
    conn = db.init_db()
    for fid in ingest.FEED_SCHEMAS:
        p = pathlib.Path(a.dir) / f"{fid}.csv"
        if p.exists():
            with p.open("r", encoding="utf-8-sig", newline="") as fh:
                loaded, rejected = ingest.ingest_csv_stream(conn, fid, fh)
            print(f"{fid}: loaded={loaded} rejected={rejected}")
    conn.commit()
    made, p_star, breaker, watch = pipeline.run_pipeline(conn)
    conn.commit()
    conn.close()
    n = export(a.out)
    print(f"pipeline: {made} new cases, p*={p_star:.3f}; exported {n} ranked flags to {a.out}")
    if breaker:
        print("CIRCUIT BREAKER TRIPPED: case creation stopped at the configured cap. "
              "Investigate feed integrity before rerunning.")
    elif watch:
        print("FLOOD WATCH: cumulative new-case volume over recent runs exceeds 3x the per-run cap.")

if __name__ == "__main__":
    main()
