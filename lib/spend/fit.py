"""Fit how the five-hour limit weighs token types, from the ccpool usage rows (ccdata.py).

Utilization comes in 0.01 steps and arrives out of order (headers are stamped when a request starts),
so each account's series is turned into a running maximum per five-hour window. The tokens of the
responses that finished between two steps are what moved it. Intervals are merged until each spans at
least MIN_STEP of utilization, so one 0.01 rounding error does not dominate a row.
"""
import itertools, json, os, sys
from collections import defaultdict

MIN_STEP = float(sys.argv[1]) if len(sys.argv) > 1 else 0.03
# API list prices per MTok: input, output, cache read. 5m write = 1.25x input, 1h write = 2x input.
PRICE = {"opus": (4, 20, 0.2), "fable": (8, 40, 0.2), "sonnet": (2, 10, 0.1), "haiku": (0.5, 2.5, 0.05)}
TYPES = ("cache_read", "write_5m", "write_1h", "output")


def fam(model):
    return next((k for k in PRICE if k in (model or "")), None)


def tokens(u):
    cc = u.get("cache_creation") or {}
    w1 = cc.get("ephemeral_1h_input_tokens") or 0
    w5 = (u.get("cache_creation_input_tokens") or 0) - w1
    return {"input": u.get("input_tokens") or 0, "cache_read": u.get("cache_read_input_tokens") or 0,
            "write_5m": w5 + (u.get("input_tokens") or 0), "write_1h": w1, "output": u.get("output_tokens") or 0}


def price_units(f, k):
    """List price of one token of type k on model family f, in units of Opus uncached input."""
    pi, po, pr = PRICE[f]
    return {"cache_read": pr, "write_5m": 1.25 * pi, "write_1h": 2 * pi, "output": po}[k] / 4


def lstsq(X, y):
    """Least squares by normal equations (few columns)."""
    n = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] + [sum(r[i] * v for r, v in zip(X, y))] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-30:
            return None
        A[c], A[p] = A[p], A[c]
        for r in range(n):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [A[i][n] / A[i][i] for i in range(n)]


def nnls(X, y):
    """Exhaustive active-set NNLS: fine for <= 6 columns."""
    n, best = len(X[0]), (float("inf"), [0.0] * len(X[0]))
    for k in range(1, n + 1):
        for cols in itertools.combinations(range(n), k):
            b = lstsq([[r[c] for c in cols] for r in X], y)
            if b is None or min(b) < 0:
                continue
            w = [0.0] * n
            for c, v in zip(cols, b):
                w[c] = v
            sse = sum((v - sum(a * b for a, b in zip(r, w))) ** 2 for r, v in zip(X, y))
            if sse < best[0]:
                best = (sse, w)
    return best


def intervals():
    rows = defaultdict(list)
    from ccdata import usage_rows
    for o in usage_rows():
        lim = (o.get("limits") or {}).get("five_hour") or {}
        u = o.get("usage")
        try:
            util, reset = float(lim["utilization"]), lim.get("reset")
        except (KeyError, TypeError, ValueError):
            util, reset = None, None
        rows[o["acct"]].append((o["t"], o["t"] - (o.get("ms") or 0) / 1000, util, reset, fam(o.get("model")), u))
    out = defaultdict(list)       # acct -> [(delta, {(fam, type): tokens})]
    for acct, rs in rows.items():
        # observations (header time, util, reset) and token events (end time, fam, tokens)
        obs = sorted(((h, util, reset) for t, h, util, reset, f, u in rs if util is not None), key=lambda o: o[0])
        ev = sorted(((t, f, tokens(u)) for t, h, util, reset, f, u in rs if u and f), key=lambda e: e[0])
        steps, top, win = [], None, None
        for h, util, reset in obs:
            if reset != win:
                win, top = reset, util
                steps.append((h, None, win))      # window boundary: never span it
                continue
            if util > top + 1e-9:
                steps.append((h, util - top, win))
                top = util
        acc, dsum, start, i = defaultdict(float), 0.0, None, 0
        for h, d, win in steps:
            # tokens finishing before this observation's header time belong to the open interval
            while i < len(ev) and ev[i][0] <= h:
                if start is not None:
                    for k, v in ev[i][2].items():
                        if k != "input":
                            acc[(ev[i][1], k)] += v
                i += 1
            if d is None:
                acc, dsum, start = defaultdict(float), 0.0, h
                continue
            dsum += d
            if dsum >= MIN_STEP - 1e-9:
                out[acct].append((dsum, dict(acc)))
                acc, dsum = defaultdict(float), 0.0
    return out


def main():
    data = intervals()
    print(f"intervals of >= {MIN_STEP:.2f} utilization: " + ", ".join(f"{a}={len(v)}" for a, v in data.items()))
    # 1. Price-weighted spend per 1% of the five-hour window, per account: shows plan sizes.
    print("\nlist-price $ per 1% of five-hour window (differs by plan size):")
    for a, iv in sorted(data.items()):
        d = sum(x[0] for x in iv)
        usd = sum(v * price_units(f, k) * 4 / 1e6 for _, acc in iv for (f, k), v in acc.items())
        if d:
            print(f"  {a:22s} {d * 100:5.0f} points  ${usd:7.1f}  -> ${usd / d / 100:6.2f} per 1%")
    # 2. Pooled fit over accounts whose $/1% is similar, token types weighted by model price.
    groups = {}
    for a, iv in data.items():
        d = sum(x[0] for x in iv)
        if d >= 0.05:
            usd = sum(v * price_units(f, k) * 4 / 1e6 for _, acc in iv for (f, k), v in acc.items())
            groups[a] = usd / d / 100
    if not groups:
        print("too thin: no account moved 5 points")
        return
    med = sorted(groups.values())[len(groups) // 2]
    pool = [a for a, v in groups.items() if 0.6 * med <= v <= 1.6 * med]
    print(f"\npooled accounts (within 0.6-1.6x of median ${med:.2f}/1%): {pool}")
    X, y = [], []
    for a in pool:
        for d, acc in data[a]:
            # feature per token type, each model's tokens scaled by its price relative to Opus input
            row = [sum(v * PRICE[f][0] / 4 for (f, k), v in acc.items() if k == t) / 1e6 for t in TYPES]
            X.append(row)
            y.append(d * 100)
    sse, w = nnls(X, y)
    n = len(y)
    print(f"{n} intervals; fit: utilization points per M model-scaled tokens")
    base = w[1] or None   # relative to a 5m write, the cleanest-identified term after reads
    for t, v in zip(TYPES, w):
        price = {"cache_read": 0.05, "write_5m": 1.25, "write_1h": 2.0, "output": 5.0}[t]
        rel = f"{v / w[1] * 1.25:6.2f}x input" if base else "   n/a"
        print(f"  {t:10s} {v:8.4f}   = {rel}   (list price {price:.2f}x)")
    tot = sum(y)
    print(f"  residual RMS {((sse / n) ** 0.5):.2f} points per interval, mean interval {tot / n:.1f} points")
    # 3. Share of fitted limit use by token type, vs share of list-price spend.
    fit_share = [sum(r[i] for r in X) * w[i] for i in range(len(TYPES))]
    pr = {"cache_read": 0.05, "write_5m": 1.25, "write_1h": 2.0, "output": 5.0}
    price_share = [sum(r[i] for r in X) * pr[t] for i, t in enumerate(TYPES)]
    fs, ps = sum(fit_share) or 1, sum(price_share) or 1
    print("\nshare of limit use (fitted) vs share of list-price spend:")
    for i, t in enumerate(TYPES):
        print(f"  {t:10s} fitted {100 * fit_share[i] / fs:5.1f}%   price {100 * price_share[i] / ps:5.1f}%")
    # 4. Leave-one-account-out stability.
    if len(pool) > 2:
        print("\nleave one account out (weights relative to 5m write = 1.25):")
        for drop in pool:
            Xs, ys = [], []
            for a in pool:
                if a == drop:
                    continue
                for d, acc in data[a]:
                    Xs.append([sum(v * PRICE[f][0] / 4 for (f, k), v in acc.items() if k == t) / 1e6 for t in TYPES])
                    ys.append(d * 100)
            _, ww = nnls(Xs, ys)
            print(f"  without {drop:20s} " + "  ".join(f"{t}={ww[i] / ww[1] * 1.25 if ww[1] else float('nan'):.2f}"
                                                         for i, t in enumerate(TYPES)))


if __name__ == "__main__":
    main()
