"""Supervisor cache-expiry rewrites by session: expiry.py 'YYYY-MM-DD HH:MM' 'YYYY-MM-DD HH:MM' (local time).

Same rule as report.py's "main expiry": a full rewrite after a gap over an hour. Shows when each idle gap
started and ended, so a natural night idle can be told apart from a session woken by a timer.
"""
import glob, os, sys
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool

from cache import scan, ROOT
from report import price


def main():
    S, E = (datetime.strptime(a, "%Y-%m-%d %H:%M").timestamp() for a in sys.argv[1:3])
    files = [p for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True) if os.path.getmtime(p) >= S - 3600]
    with Pool(8) as pool:
        data = pool.map(scan, files, chunksize=4)
    by = defaultdict(list)
    for path, side, calls in data:
        if side:
            continue
        calls.sort(key=lambda c: c[1])
        prev = None
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            tot = i + cw + cr
            if sd:
                continue
            if (prev and S <= t < E and tot >= 0.6 * prev[1] and prev[1] > 30000
                    and cr < 0.8 * min(prev[1], tot) and t - prev[0] > 3600):
                cost = ((cw - cw1) * 1.25 + cw1 * 2) * price(model)[0] / 1e6
                by[path.split("/")[-2][-24:]].append((prev[0], t, cost, tot))
            prev = (t, tot)
    f = lambda x: datetime.fromtimestamp(x).strftime("%H:%M")
    for k, v in sorted(by.items(), key=lambda x: -sum(r[2] for r in x[1])):
        print(f"{k:26s} n={len(v):2d} ${sum(r[2] for r in v):5.1f}  " +
              ", ".join(f"{f(a)}->{f(b)} {tot // 1000}k" for a, b, c, tot in v[:6]))
    print("total", sum(len(v) for v in by.values()), f"${sum(r[2] for v in by.values() for r in v):.1f}")


if __name__ == "__main__":
    main()
