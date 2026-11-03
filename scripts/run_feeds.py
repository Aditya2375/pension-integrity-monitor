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
            loaded, rejected = ingest.ingest_csv(conn, fid, p.read_text())
            print(f"{fid}: loaded={loaded} rejected={rejected}")
    conn.commit()
    made, p_star = pipeline.run_pipeline(conn)
    conn.commit()
    conn.close()
    n = export(a.out)
    print(f"pipeline: {made} new cases, p*={p_star:.3f}; exported {n} ranked flags to {a.out}")

if __name__ == "__main__":
    main()
