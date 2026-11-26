"""Spend by project directory (main + its workers): byproject.py 'YYYY-MM-DD HH:MM' 'YYYY-MM-DD HH:MM' (local)."""
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
    seen, d = set(), defaultdict(float)
    for path, side, calls in data:
        proj = os.path.relpath(path, ROOT).split(os.sep)[0]
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            if mid in seen or not S <= t < E:
                continue
            seen.add(mid)
            pi, po, pr = price(model)
            d[proj] += (((cw - cw1) * 1.25 + cw1 * 2 + i) * pi + cr * pr + out * po) / 1e6
    T = sum(d.values())
    for k, v in sorted(d.items(), key=lambda x: -x[1]):
        print(f"{v:8.0f}  {100 * v / T:5.1f}%  {k}")
    print(f"{T:8.0f}  total")


if __name__ == "__main__":
    main()
