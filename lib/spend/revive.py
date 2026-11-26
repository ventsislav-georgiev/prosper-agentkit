"""Double cache writes after a session restart: revive.py 'YYYY-MM-DD HH:MM' ['YYYY-MM-DD HH:MM'] (local).

A restart point is a main-session call after a gap of more than 5 minutes. It is a double write when
both that call and the next one, within 60 seconds, write most of the context instead of reading it.
"""
import glob, os, sys
from datetime import datetime
from cache import scan, ROOT

start = datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M").timestamp()
end = datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M").timestamp() if len(sys.argv) > 2 else 4e9
n = dbl = 0
for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True):
    if "/subagents/" in p or os.path.getmtime(p) < start:
        continue
    calls = sorted((c for c in scan(p)[2] if not c[8]), key=lambda c: c[1])
    for a, b, c in zip(calls, calls[1:], calls[2:]):
        if not (start <= b[1] < end and b[1] - a[1] > 300):
            continue
        tot = lambda x: x[2] + x[3] + x[5]
        full = lambda x: tot(x) > 30000 and x[3] > 0.6 * tot(x)
        if not full(b):
            continue
        n += 1
        twice = full(c) and c[1] - b[1] < 60
        dbl += twice
        print(f"{datetime.fromtimestamp(b[1]):%m-%d %H:%M:%S} {p.split('/')[-2][-22:]}/{os.path.basename(p)[:8]}  "
              f"write {b[3] // 1000}k" + (f", again {c[3] // 1000}k after {c[1] - b[1]:.0f}s  DOUBLE" if twice else ""))
print(f"restarts with a full write: {n}, double writes: {dbl}")
