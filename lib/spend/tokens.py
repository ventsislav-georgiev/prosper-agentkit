"""Token totals, cache hit and 1h/5m writes for main vs workers, plus the top supervisor sessions: tokens.py START END (local)."""
import glob, os, sys, json
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool
from cache import scan, ROOT
from report import price
def main():
    S, E = (datetime.strptime(a, "%Y-%m-%d %H:%M").timestamp() for a in sys.argv[1:3])
    files = [p for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True) if os.path.getmtime(p) >= S - 3600]
    with Pool(8) as pool: data = pool.map(scan, files, chunksize=4)
    seen = set(); tok = defaultdict(lambda: defaultdict(float)); per = defaultdict(float)
    for path, side, calls in data:
        k = "worker" if side else "main"
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            if mid in seen or not S <= t < E: continue
            seen.add(mid)
            pi, po, pr = price(model)
            c = (((cw - cw1) * 1.25 + cw1 * 2 + i) * pi + cr * pr + out * po) / 1e6
            for f, v in (("in", i), ("cw5", cw - cw1), ("cw1", cw1), ("cr", cr), ("out", out), ("$", c), ("cw1$", cw1*2*pi/1e6), ("cw5$", (cw-cw1)*1.25*pi/1e6)):
                tok[k][f] += v
            if not side: per[path] += c
    for k, d in tok.items():
        ctx = d["in"] + d["cw5"] + d["cw1"] + d["cr"]
        print(f'{k}: ${d["$"]:.0f}  context tokens {ctx/1e9:.2f}B  cache hit {100*d["cr"]/ctx:.1f}%  writes 5m {d["cw5"]/1e6:.0f}M (${d["cw5$"]:.0f})  1h {d["cw1"]/1e6:.0f}M (${d["cw1$"]:.0f})  out {d["out"]/1e6:.1f}M')
    def title(p):
        t = None
        with open(p) as f:
            for line in f:
                if '"custom-title"' in line or '"agentName"' in line:
                    try:
                        o = json.loads(line); t = o.get("customTitle") or o.get("agentName") or t
                    except Exception: pass
        return t
    for p, c in sorted(per.items(), key=lambda x: -x[1])[:16]:
        print(f'{c:7.0f}  {title(p) or "?":24} {os.path.relpath(p, ROOT)[:70]}')
if __name__ == '__main__':
    main()
