"""Supervisor spend by context size per call: ctxsize.py START END (local)."""
import glob, os, sys
from datetime import datetime
from multiprocessing import Pool
from cache import scan, ROOT
from report import price
def main():
    S, E = (datetime.strptime(a, "%Y-%m-%d %H:%M").timestamp() for a in sys.argv[1:3])
    files = [p for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True) if os.path.getmtime(p) >= S - 3600]
    with Pool(8) as pool: data = pool.map(scan, files, chunksize=4)
    seen=set(); b={}; models={}
    for path, side, calls in data:
        if side: continue
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            if mid in seen or not S <= t < E: continue
            seen.add(mid); ctx=i+cw+cr
            k = "<100k" if ctx<1e5 else "100-200k" if ctx<2e5 else "200-300k" if ctx<3e5 else "300-500k" if ctx<5e5 else ">=500k"
            pi,po,pr=price(model); c=(((cw-cw1)*1.25+cw1*2+i)*pi+cr*pr+out*po)/1e6
            n,d=b.get(k,(0,0)); b[k]=(n+1,d+c); models[model]=models.get(model,0)+1
    T=sum(d for n,d in b.values())
    if not T: return print("spend-report ctxsize: no main-session calls in the window")
    for k in ["<100k","100-200k","200-300k","300-500k",">=500k"]:
        n,d=b.get(k,(0,0)); print(f"{k:9} calls {n:6}  ${d:6.0f}  {100*d/T:4.1f}%")
    print(models)
if __name__=="__main__": main()
