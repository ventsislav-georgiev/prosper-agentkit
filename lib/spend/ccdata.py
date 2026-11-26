"""ccpool data for the spend scripts, from Prosper's ccpool folder: usage/usage-YYYY-MM-DD.jsonl, events/events-YYYY-MM-DD.jsonl
and state.json, in $PROSPER_CCPOOL_DIR, else ~/Library/Application Support/Prosper/ccpool. Rows come out in one flat
shape (account label, usage, limits). Reads only.
"""
import glob, json, os

NEW = os.path.expanduser(os.environ.get("PROSPER_CCPOOL_DIR", "").strip() or "~/Library/Application Support/Prosper/ccpool")


def small_accounts():
    """Accounts on a smaller plan, left out of the account-week fit and totals: the kit setting spend_small_accounts
    (KIT_SPEND_SMALL_ACCOUNTS, comma-separated labels), empty by default."""
    return {a.strip() for a in os.environ.get("KIT_SPEND_SMALL_ACCOUNTS", "").split(",") if a.strip()}


def labels():
    """Prosper keychain id -> account label."""
    names = {}
    try:
        acc = json.load(open(os.path.join(NEW, "state.json"))).get("accounts", {})
    except (OSError, ValueError):
        return names
    names.update({v.get("id"): k for k, v in acc.items() if isinstance(v, dict)})
    return names


def convert(r, names):
    """One Prosper usage row -> the flat shape (acct label, usage, limits)."""
    o = {"t": r.get("t"), "ms": r.get("ms"), "acct": names.get(r.get("acct"), r.get("acct")),
         "model": r.get("model"), "conv": f"{r['sess']}/{r.get('agent', '')}" if r.get("sess") else None}
    if "out" in r:
        cw5, cw1 = r.get("cw5") or 0, r.get("cw1") or 0
        o["usage"] = {"input_tokens": r.get("in") or 0, "output_tokens": r.get("out") or 0,
                      "cache_read_input_tokens": r.get("cr") or 0, "cache_creation_input_tokens": cw5 + cw1,
                      "cache_creation": {"ephemeral_5m_input_tokens": cw5, "ephemeral_1h_input_tokens": cw1}}
    o["limits"] = {k: {"utilization": v.get("u"), "reset": v.get("r")} for k, v in (r.get("lim") or {}).items()}
    o["mv"] = bool(r.get("mv"))
    o["st"], o["qc"], o["att"] = r.get("st"), bool(r.get("qc")), r.get("att") or 1
    return o


def usage_rows():
    """Every relayed response, oldest first."""
    names = labels()
    for p in sorted(glob.glob(os.path.join(glob.escape(NEW), "usage", "usage-*.jsonl"))):
        for ln in open(p, errors="replace"):
            try:
                yield convert(json.loads(ln), names)
            except (ValueError, KeyError):
                continue


def bench_events():
    """(times of bench/rotate/retire/throttle-move events, times of all-benched rejections, times of refused startup quota checks,
    times of startup quota checks rescued by re-placement)."""
    ev, allb, qc, rescued = [], [], [], []
    # shortcut: Prosper's events file schema is not final; any event naming a rotation, retirement or move counts,
    # and moved conversations (mv) in the usage rows stand in until the events file exists.
    efiles = sorted(glob.glob(os.path.join(glob.escape(NEW), "events", "events-*.jsonl")))
    for p in efiles:
        for ln in open(p, errors="replace"):
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            k = str(e.get("ev", "")).lower()
            if "all" in k and "bench" in k:
                allb.append(e["t"])
            elif any(s in k for s in ("rotat", "retire", "full", "move", "bench")):
                ev.append(e["t"])
    for o in usage_rows():
        if not efiles and o.get("mv"):
            ev.append(o["t"])
        if o.get("st") == 429:   # a 429 that reached the client
            # a refused quota check is Claude Code's startup probe; the conversation goes on under its own id
            (qc if o.get("qc") else allb).append(o["t"])
        elif o.get("qc") and o.get("att", 1) > 1:   # a quota check never retries, so att>1 is a re-placement
            rescued.append(o["t"])
    return sorted(ev), sorted(allb), sorted(qc), sorted(rescued)


def pins():
    """Live session pins: '<sid>/<agent>' -> account label, from Prosper's state."""
    try:
        return json.load(open(os.path.join(NEW, "state.json"))).get("pins", {})
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    r = convert({"t": 1.0, "acct": "X", "sess": "s", "agent": "a", "in": 1, "out": 2, "cr": 3, "cw5": 4, "cw1": 5,
                 "lim": {"seven_day": {"u": 0.07, "r": 9, "s": "a"}}, "mv": True}, {"X": "acct-a"})
    assert r["acct"] == "acct-a" and r["conv"] == "s/a" and r["mv"] and r["st"] is None and not r["qc"] and r["att"] == 1
    assert r["usage"]["cache_creation_input_tokens"] == 9 and r["usage"]["cache_creation"]["ephemeral_1h_input_tokens"] == 5
    assert r["limits"]["seven_day"] == {"utilization": 0.07, "reset": 9}
    os.environ["KIT_SPEND_SMALL_ACCOUNTS"] = " acct-b , ,acct-c"
    assert small_accounts() == {"acct-b", "acct-c"}
    del os.environ["KIT_SPEND_SMALL_ACCOUNTS"]
    assert small_accounts() == set()
    print("ccdata: checks passed")
