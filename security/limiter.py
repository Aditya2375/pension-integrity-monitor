"""Bounded SQLite fixed-window limiter shared by processes using the SAME database.

Use a separate local limiter DB, never an NFS share. Hash/pseudonymize identifiers
at the caller; do not use Aadhaar, PAN, appeal tokens or raw personal data as keys.
For multi-host deployments replace with a centrally atomic limiter at the edge.
"""
import math
import sqlite3
import time

class Limiter:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, n INTEGER NOT NULL)')

    def allow(self, bucket, limit, window_seconds, now=None):
        if (not isinstance(bucket, str) or not bucket or len(bucket) > 256
                or not isinstance(limit, int) or not isinstance(window_seconds, int)
                or limit < 1 or not 1 <= window_seconds <= 86400):
            raise ValueError('Invalid limiter configuration')
        now = time.time() if now is None else now
        if not math.isfinite(now):
            raise ValueError('Invalid time')
        start = int(now // window_seconds) * window_seconds
        try:
            with sqlite3.connect(self.path, timeout=2) as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute('DELETE FROM rate_limits WHERE window < ?', (int(now) - 86400,))
                row = c.execute('SELECT window,n FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()
                if row is None and c.execute('SELECT COUNT(*) FROM rate_limits').fetchone()[0] >= 10000:
                    return False
                n = row[1] if row and row[0] == start else 0
                if n >= limit:
                    return False
                c.execute('INSERT INTO rate_limits VALUES(?,?,?) ON CONFLICT(bucket) DO UPDATE SET window=excluded.window,n=excluded.n', (bucket, start, n + 1))
                return True
        except sqlite3.Error:
            return False  # no authentication/appeal attempts if limiter is unavailable
