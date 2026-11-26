"""Weekly-limit points used per account per local day (--hourly: per hour), measured from the ccpool usage rows (ccdata.py).
Running max of seven_day utilization per reset window; 100 points = one full-size account-week."""
import sys
from collections import defaultdict
from datetime import datetime
from ccdata import NEW, usage_rows, small_accounts

FMT = "%m-%d %a %H" if sys.argv[1:] == ["--hourly"] else "%Y-%m-%d %a"
SMALL = small_accounts()   # smaller plans: left out of the full-size total
obs = defaultdict(list)
for o in usage_rows():
    s = (o.get("limits") or {}).get("seven_day") or {}
    try: u = float(s["utilization"])
    except (KeyError, TypeError, ValueError): continue
    if o.get("acct") is None or o.get("t") is None: continue
    obs[o["acct"]].append((o["t"] - (o.get("ms") or 0) / 1000, u, s.get("reset")))
if not obs:
    sys.exit(f"spend-report points: no ccpool usage rows in {NEW}")
day = defaultdict(lambda: defaultdict(float))
first = min(min(x[0] for x in v) for v in obs.values())
for a, rs in obs.items():
    rs.sort(); win = top = None
    for t, u, r in rs:
        if r != win: win, top = r, u; continue
        if u > top + 1e-9:
            day[datetime.fromtimestamp(t).strftime(FMT)][a] += (u - top) * 100; top = u
print("data since", datetime.fromtimestamp(first))
accts = sorted(obs)
print("day            " + " ".join(f"{a[:10]:>10s}" for a in accts) + "  full-size total")
for d in sorted(day):
    tot = sum(v for a, v in day[d].items() if a not in SMALL)
    print(f"{d}  " + " ".join(f"{day[d].get(a,0):10.0f}" for a in accts) + f"  {tot:6.0f}")
