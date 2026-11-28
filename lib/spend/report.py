"""Spend report for a time window: spend-report.py 'YYYY-MM-DD HH:MM' ['YYYY-MM-DD HH:MM'] (local time).

Dollars are API list prices, used only as weights; the subscription limit's own weights are unknown.
"""
import bisect, glob, json, os, re, sys, time, urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from multiprocessing import Pool

from cache import scan, ROOT

P = {"opus": (4, 20, 0.2), "fable": (8, 40, 0.2), "sonnet": (2, 10, 0.1), "haiku": (0.5, 2.5, 0.05)}


def price(model):
    return P[next((k for k in P if k in model), "opus")]



def ledger_uri():
    """The kit ledger, read-only, found as todo.py finds it: $LEDGER_DB, else $KIT_LEDGER_DB, else $KIT_STATE_DIR/ledger.sqlite3, else
    $XDG_DATA_HOME (default ~/.local/share)/prosper-agentkit/ledger.sqlite3."""
    e = os.environ
    if e.get("LEDGER_DB"):
        p = e["LEDGER_DB"]
    elif e.get("KIT_LEDGER_DB"):
        p = e["KIT_LEDGER_DB"]
    elif e.get("KIT_STATE_DIR"):
        p = os.path.join(e["KIT_STATE_DIR"], "ledger.sqlite3")
    else:
        p = os.path.join(e.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "prosper-agentkit", "ledger.sqlite3")
    return "file:" + urllib.parse.quote(os.path.abspath(p)) + "?mode=ro"


from ccdata import bench_events, usage_rows, pins as ccpins  # noqa: E402


def main():
    start = datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M").timestamp()
    end = datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M").timestamp() if len(sys.argv) > 2 else time.time()
    files = [p for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True) if os.path.getmtime(p) >= start - 3600]
    with Pool(8) as pool:
        data = pool.map(scan, files, chunksize=4)
    ev, allb, qcrej, qcok = bench_events()

    def rotated(a, b):
        i = bisect.bisect_left(ev, a - 60)  # a replayed request can start before the previous call is logged
        return i < len(ev) and ev[i] <= b + 3

    seen, d, n = set(), defaultdict(float), defaultdict(int)
    workers = []
    for path, side, calls in data:
        calls.sort(key=lambda c: c[1])
        prev, wn, wmax, wcost, first = None, 0, 0, 0.0, None
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            total, dup = i + cw + cr, mid in seen
            seen.add(mid)
            s = "side" if (side or sd) else "main"
            pi, po, pr = price(model)
            write = ((cw - cw1) * 1.25 + cw1 * 2) * pi / 1e6
            cost = write + i * pi / 1e6 + cr * pr / 1e6 + out * po / 1e6
            if not dup and start <= t < end:
                first = first or t
                wn, wmax, wcost = wn + 1, max(wmax, total), wcost + cost
                n[s + " calls"] += 1
                d["total"] += cost; d[s] += cost
                d["read"] += cr * pr / 1e6; d["write"] += write; d["out"] += out * po / 1e6
                d["fable"] += cost if "fable" in model else 0
                if prev and total >= 0.6 * prev[1] and prev[1] > 30000 and cr < 0.8 * min(prev[1], total):
                    gap = t - prev[0]
                    # expiry first: a cache that had already timed out was lost with or without a rotation
                    k = ("expiry" if (gap > 3600 or (s == "side" and gap > 300)) else
                         "rotation" if rotated(prev[0], t) else "other miss")
                    d[f"{s} {k}"] += write; n[f"{s} {k}"] += 1
                elif prev and total < 0.6 * prev[1]:
                    d[f"{s} compaction"] += write; n[f"{s} compaction"] += 1
            prev = (t, total)
        if side and wn and first and min(c[1] for c in calls) >= start:
            try:
                tier = json.load(open(path[:-6] + ".meta.json")).get("agentType", "?")
            except (OSError, ValueError):
                tier = "?"
            workers.append((wn, wmax, wcost, next((k for k in P if k in calls[0][7]), 'opus'), tier))

    T = d["total"] or 1
    hours = (end - start) / 3600
    pct = lambda v: f"{100 * v / T:5.1f}%"
    print(f"window {sys.argv[1]} -> {datetime.fromtimestamp(end):%Y-%m-%d %H:%M}  ({hours:.1f}h)")
    print(f"spend ${T:,.0f}  (${T / hours:,.0f}/h)  main {pct(d['main'])} workers {pct(d['side'])} fable {pct(d['fable'])}")
    print(f"split: cache read {pct(d['read'])}  cache write {pct(d['write'])}  output {pct(d['out'])}")
    print(f"calls: main {n['main calls']}  workers {n['side calls']}")
    nb = sum(1 for t in ev if start <= t < end)
    print(f"ccpool: {nb} bench/move events ({nb / hours * 24:.0f}/day), "
          f"{sum(1 for t in allb if start <= t < end)} all-benched/429 rejections to the client, "
          f"{sum(1 for t in qcrej if start <= t < end)} refused startup quota checks "
          f"({sum(1 for t in qcok if start <= t < end)} more rescued by re-placement)")
    print("full rewrites (count, $ share):")
    for k in ("main rotation", "side rotation", "side expiry", "main expiry", "main other miss", "side other miss",
              "main compaction", "side compaction"):
        print(f"  {k:16s} {n[k]:5d}  {pct(d[k])}" + (f"  = {n[k] / nb:.1f} per bench event" if "rotation" in k and nb else ""))
    # The call that writes a compaction summary is not in the transcript, so not in the total above.
    # shortcut: found by shape (long output on a fully cached context), fix if ccpool starts logging the request kind
    cn, cusd, cmax = 0, 0.0, 0
    for o in usage_rows():
        u = o.get("usage") or {}
        if (start <= o.get("t", 0) < end and (u.get("output_tokens") or 0) >= 10000
                and (u.get("cache_read_input_tokens") or 0) >= 100000 and (u.get("cache_creation_input_tokens") or 0) < 5000):
            pi, po, pr = price(o.get("model") or "")
            cn, cusd = cn + 1, cusd + u["output_tokens"] * po / 1e6 + u["cache_read_input_tokens"] * pr / 1e6
            cmax = max(cmax, u["output_tokens"])
    print(f"compaction summary calls (ccpool log, NOT in the total): {cn}  ${cusd:,.1f}  = {100 * cusd / T:.1f}% on top; "
          f"largest such call {cmax // 1000}k output tokens")
    if workers:
        wt = sum(w[2] for w in workers) or 1
        big = [w for w in workers if w[1] >= 200000]
        mid = [w for w in workers if 150000 <= w[1] < 200000]
        calls = sorted(w[0] for w in workers)
        print(f"workers started in window: {len(workers)}, median {calls[len(calls) // 2]} calls, "
              f"p90 {calls[int(len(calls) * 0.9)]} calls")
        print(f"  peak context >=200k: {len(big)} ({100 * len(big) / len(workers):.0f}% of workers, "
              f"{100 * sum(w[2] for w in big) / wt:.0f}% of their spend); 150-200k: {len(mid)} "
              f"({100 * sum(w[2] for w in mid) / wt:.0f}% of spend)")
    # Per model: workers on a cheaper model (Sonnet, Haiku) against Opus.
    # Judge it on $ per worker AND on redo rate; a cheap worker whose entry is redone on Opus is not cheaper.
    for m in P:
        ws = [w for w in workers if w[3] == m]
        if ws:
            c = sorted(w[0] for w in ws)
            print(f"  {m:6s} workers: {len(ws):4d}  ${sum(w[2] for w in ws):7,.0f}  ${sum(w[2] for w in ws) / len(ws):5.2f} each  "
                  f"median {c[len(c) // 2]} calls")
    # Per agent type: the effort tiers differ in cost per worker.
    for t in sorted({w[4] for w in workers}):
        ws = [w for w in workers if w[4] == t]
        c = sorted(w[0] for w in ws)
        print(f"  {t:22s} {len(ws):4d}  ${sum(w[2] for w in ws):7,.0f}  ${sum(w[2] for w in ws) / len(ws):5.2f} each  "
              f"median {c[len(c) // 2]} calls  >=150k: {sum(1 for w in ws if w[1] >= 150000)}")
    try:
        import sqlite3
        iso = datetime.fromtimestamp(start, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M")
        rows = sqlite3.connect(ledger_uri(), uri=True).execute(
            "select project, entry_id, payload from events where action='append:dispatch' and occurred_at>=? order by id",
            (iso,)).fetchall()
        seq = defaultdict(list)
        for proj, eid, payload in rows:
            m = re.search(r"worker-(opus|sonnet|haiku|fable)(?:-(\w+))?", payload)
            if m:
                seq[(proj, eid)].append(m[1] + ("-" + m[2] if m[2] else ""))
        tiers = defaultdict(lambda: [0, 0, 0])   # dispatches, entries, entries later redone on another model
        for tl in seq.values():
            for t in tl:
                tiers[t][0] += 1
            tiers[tl[0]][1] += 1
            tiers[tl[0]][2] += any(t != tl[0] for t in tl[1:])
        print("ledger dispatches in window (first tier of an entry: dispatches, entries, entries later sent to another tier):")
        for t, v in sorted(tiers.items()):
            print(f"  {t:14s} {v[0]:4d} dispatches  {v[1]:4d} entries  {v[2]:3d} later on another tier")
        rank = {"haiku": 0, "sonnet-low": 1, "sonnet-medium": 2, "opus-low": 3, "opus-medium": 4, "opus-high": 5,
                "opus-xhigh": 6, "opus-max": 7}
        up = defaultdict(lambda: [0, 0])   # first tier -> entries, entries escalated to a higher tier (a failed review)
        for tl in seq.values():
            up[tl[0]][0] += 1
            up[tl[0]][1] += any(rank.get(t, -1) > rank.get(tl[0], 99) for t in tl[1:])
        iso_end = datetime.fromtimestamp(end, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M")
        closed = sqlite3.connect(ledger_uri(), uri=True).execute(
            "select count(distinct project||'/'||entry_id) from events where action='status' and payload like '%DONE%' "
            "and occurred_at>=? and occurred_at<?", (iso, iso_end)).fetchone()[0]
        print(f"ledger entries closed in window: {closed}  (${T / closed:.2f} per closed entry)" if closed else "no entries closed")
        print("escalated to a higher tier: " + ", ".join(f"{t} {v[1]}/{v[0]}" for t, v in sorted(up.items())))
    except Exception as e:  # noqa: BLE001
        print("ledger unreadable:", e)
    try:
        pins = ccpins()
        by = defaultdict(set)
        for k, a in pins.items():
            by[a].add(k.split("/")[0])
        print("sessions per account now:", ", ".join(f"{a}={len(v)}" for a, v in sorted(by.items())))
    except Exception as e:  # noqa: BLE001
        print("pins unreadable:", e)


if __name__ == "__main__":
    main()
