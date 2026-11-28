"""How many accounts a week of usage needs: fits weekly-limit points to Fable and non-Fable list-price
dollars per account from the ccpool usage rows (ccdata.py), then scales the pool's hourly rate to 168 hours.
shortcut: two-term fit over one row per account, refit by token type once the log holds several weeks."""
import sys
from collections import defaultdict
from report import price
from fit import lstsq
from ccdata import usage_rows, small_accounts

acc = defaultdict(lambda: {"f": 0.0, "n": 0.0, "lo": {}, "hi": {}, "t0": None, "t1": None})
for o in usage_rows():
    a, u, m = acc[o.get("acct")], o.get("usage") or {}, o.get("model") or ""
    pi, po, pr = price(m)
    cw, cw1 = u.get("cache_creation_input_tokens") or 0, (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
    a["f" if "fable" in m else "n"] += (((cw - cw1) * 1.25 + cw1 * 2) * pi + (u.get("input_tokens") or 0) * pi
                                        + (u.get("cache_read_input_tokens") or 0) * pr + (u.get("output_tokens") or 0) * po) / 1e6
    sd = (o.get("limits") or {}).get("seven_day") or {}
    try:
        util, reset = float(sd["utilization"]), int(sd["reset"])
    except (KeyError, ValueError, TypeError):
        continue
    a["lo"][reset], a["hi"][reset] = min(a["lo"].get(reset, 9), util), max(a["hi"].get(reset, 0), util)
    a["t0"], a["t1"] = a["t0"] or o["t"], o["t"]
SMALL = small_accounts()   # a smaller plan: left out of the fit (kit setting spend_small_accounts)
rows = [(k, a["n"], a["f"], sum(a["hi"][r] - a["lo"][r] for r in a["hi"]) * 100) for k, a in acc.items()]
fitr = [r for r in rows if r[0] not in SMALL and r[3] >= 15]
if len(fitr) < 2:
    sys.exit(f"spend-report accounts: need at least 2 accounts with 15+ points (have {len(fitr)})")
h = (max(a["t1"] for a in acc.values() if a["t1"]) - min(a["t0"] for a in acc.values() if a["t0"])) / 3600
if h <= 0:
    sys.exit("spend-report accounts: the usage rows span no time")
if not any(r[2] for r in fitr):   # no Fable spend in the fit: the Fable column is all zero, so fit non-Fable alone
    w0 = lstsq([[r[1]] for r in fitr], [r[3] for r in fitr])
    if not w0 or w0[0] <= 0:
        sys.exit("spend-report accounts: the fit has no positive non-Fable weight")
    N, F = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"log spans {h / 24:.1f} days; fit over {len(fitr)} accounts: they have no Fable spend, so the fit is non-Fable only")
    for k, n, f, p in fitr:
        print(f"  {k:18s} actual {p:4.0f}  fitted {w0[0] * n:4.0f}")
    print(f"one account-week = ${100 / w0[0]:,.0f} non-Fable (list price)")
    print(f"rate: non-Fable ${N / h:.0f}/h -> {w0[0] * N / h * 1.68:.1f} account-weeks per week")
    if F:   # QA r2121 n1: a small or thin account can still spend on Fable; there is no Fable weight to count it with
        print(f"Fable ${F / h:.0f}/h in accounts outside the fit is not counted")
    sys.exit(0)
w = lstsq([[r[1], r[2]] for r in fitr], [r[3] for r in fitr])
if not w or w[0] <= 0 or w[1] <= 0:
    sys.exit("spend-report accounts: the fit has no positive Fable and non-Fable weights; the accounts need a mix of both")
N, F = sum(r[1] for r in rows), sum(r[2] for r in rows)
print(f"log spans {h / 24:.1f} days; fit over {len(fitr)} accounts: a Fable dollar counts {w[1] / w[0]:.1f}x a non-Fable dollar")
for k, n, f, p in fitr:
    print(f"  {k:18s} actual {p:4.0f}  fitted {w[0] * n + w[1] * f:4.0f}  fable {100 * f / (n + f):3.0f}% of $")
print(f"one account-week = ${100 / w[0]:,.0f} non-Fable or ${100 / w[1]:,.0f} Fable (list price)")
print(f"rate: non-Fable ${N / h:.0f}/h, Fable ${F / h:.0f}/h -> {(w[0] * N + w[1] * F) / h * 1.68:.1f} account-weeks per week, "
      f"Fable {w[1] * F / h * 1.68:.1f} of them; without Fable (same tokens on Opus, ~0.63x the dollars) "
      f"{w[0] * (N + 0.63 * F) / h * 1.68:.1f}")
