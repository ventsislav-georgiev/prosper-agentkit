"""Worker tokens and dollars per ledger entry and tier, plus each main session's share, as JSON (schema 1).

spend-report.py entries --since T [--until T] --json [--out FILE]; T is 'YYYY-MM-DD HH:MM' (local) or 12h / 7d back.
A worker is tied to an entry by exactly one `todo.py set-status <project> <id> ... --fork` claim in its own tool calls,
else by exactly one #id in its meta description (project from "[tier] <project> #<id>", else from the parent
session's own todo.py calls naming that id, else the one project they all name); anything else is unattributed.
"""
import argparse, glob, json, os, re, sqlite3, sys, tempfile, time
from collections import defaultdict
from datetime import datetime
from functools import partial
from multiprocessing import Pool

from cache import scan, ROOT
from report import ledger_uri, price

CLAIM = re.compile(r'todo\.py\s+set-status\s+([\w.-]+)\s+#?(\d+)\b([^"\n]*)')
WORKER = re.compile(r'--worker\s+([\w.-]+/[\w.-]+)')
REF = re.compile(r'todo\.py\s+[\w-]+\s+(\w[\w.-]*)\s+#?(\d+)\b')
DESC = re.compile(r'#(\d{2,5})\b')
LEAD = re.compile(r'^\s*\[([^\]]+)\]\s+([\w.-]+)\s+#(\d+)\b')


def when(s):
    m = re.fullmatch(r"(\d+)([hd])", s)
    if m:
        return time.time() - int(m.group(1)) * (3600 if m.group(2) == "h" else 86400)
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not 'YYYY-MM-DD HH:MM' or <n>h/<n>d: {s}")


def iso(t):
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def one(path, start, end):
    """One transcript: its in-window calls, the claims (worker) or entry references (main) in its tool calls, its name."""
    _, side, calls = scan(path)
    calls = [c for c in calls if start <= c[1] < end]
    found, name = set(), {}
    if calls or not side:   # a main transcript is read even when idle: its workers may need its references
        with open(path, errors="replace") as f:
            for line in f:
                if '"tool_use"' in line:
                    if side:
                        found |= {(m[1], m[2], (WORKER.search(m[3]) or [None, None])[1]) for m in CLAIM.finditer(line) if "--fork" in m[3]}
                    else:
                        found |= {m.groups() for m in REF.finditer(line)}
                elif line.startswith(('{"type":"custom-title"', '{"type":"agent-name"')):
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    name[o["type"]] = o.get("customTitle") or o.get("agentName") or name.get(o["type"])
    return path, side, calls, found, name.get("custom-title") or name.get("agent-name")


def tier_of(claim_tier, meta):
    if claim_tier:
        return claim_tier
    at, desc = meta.get("agentType") or "?", meta.get("description") or ""
    m = re.fullmatch(r"worker-([a-z]+)(?:-([a-z]+))?", at)
    if m:
        return m[1] + ("/" + m[2] if m[2] else "")
    m = re.match(r"\s*\[([\w.-]+/[\w.-]+)\]", desc)
    return m[1] if m else at


def ledger_ids():
    """{(project, id without leading zeros): id as written} from the ledger, or None when it cannot be read."""
    try:
        con = sqlite3.connect(ledger_uri(), uri=True)
        try:
            return {(p, i.lstrip("0")): i for p, i in con.execute("select project, entry_id from entries")}
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"spend-report entries: ledger unreadable ({e}); description ids are not checked against it", file=sys.stderr)
        return None


def attribute(found, meta, parent_refs, known=None):
    """(project, id, tier, source) or None. A description's (project, id) must be a ledger entry when the ledger is known
    (a PR number reads like an id); a claim is a ledger write, so it is taken as is."""
    claims = {(p, i) for p, i, _ in found}
    if len(claims) == 1:
        p, i = next(iter(claims))
        return p, i, tier_of(next((t for _, _, t in found if t), None), meta), "claim"
    if claims:
        return None
    desc = meta.get("description") or ""
    ids = set(DESC.findall(desc))
    if len(ids) != 1:
        return None
    i = next(iter(ids))
    m = LEAD.match(desc)
    projects = {m[2]} if m and m[3] == i else {p for p, r in parent_refs if r.lstrip("0") == i.lstrip("0")}
    if not projects:   # the session's own ledger: the one project its todo.py calls name
        projects = {p for p, _ in parent_refs}
    if len(projects) != 1:
        return None
    p = next(iter(projects))
    if known is not None:
        i = known.get((p, i.lstrip("0")))
        if i is None:
            return None
    return p, i, tier_of(None, meta), "description"


def build(start, end):
    files = sorted(p for p in glob.iglob(ROOT + "/**/*.jsonl", recursive=True) if os.path.getmtime(p) >= start - 3600)
    files += sorted({os.path.dirname(os.path.dirname(p)) + ".jsonl" for p in files if "/subagents/" in p} - set(files))
    files = [p for p in files if os.path.isfile(p)]
    with Pool(8) as pool:
        data = pool.map(partial(one, start=start, end=end), files, chunksize=4)
    seen, mains, workers = set(), {}, []
    for path, side, calls, found, name in data:
        tok, usd = [0] * 5, 0.0
        for mid, t, i, cw, cw1, cr, out, model, sd, tools in calls:
            if mid in seen:   # a resumed or forked session repeats earlier calls
                continue
            seen.add(mid)
            pi, po, pr = price(model)
            usd += (((cw - cw1) * 1.25 + cw1 * 2 + i) * pi + cr * pr + out * po) / 1e6
            for k, v in enumerate((i, cw - cw1, cw1, cr, out)):
                tok[k] += v
        if side:
            workers.append((path, found, tok, usd))
        else:
            mains[path] = (name or os.path.basename(path)[:-6], usd, found)
    known = ledger_ids()
    entries, unatt, split = {}, [0, 0.0], defaultdict(lambda: defaultdict(float))
    for path, found, tok, usd in workers:
        if not usd:
            continue
        try:
            with open(path[:-6] + ".meta.json") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        parent = os.path.dirname(os.path.dirname(path)) + ".jsonl"
        a = attribute(found, meta, mains.get(parent, (None, 0, set()))[2], known)
        if not a:
            unatt[0] += 1
            unatt[1] += usd
            continue
        e = entries.setdefault(a[:3], {"project": a[0], "entry": a[1], "tier": a[2], "workers": 0,
                                       "tokens": dict.fromkeys(("in", "cw5m", "cw1h", "cr", "out"), 0), "usd": 0.0, "source": a[3]})
        e["workers"] += 1
        e["usd"] += usd
        for k, v in zip(e["tokens"], tok):
            e["tokens"][k] += v
        if a[3] == "claim":   # one group can hold workers of both sources; a claim is the firmer one
            e["source"] = "claim"
        split[parent][a[:2]] += usd
    sup = []
    for path, (name, usd, _) in mains.items():
        w = split.get(path, {})
        tot = sum(w.values())
        if usd or w:
            sup.append({"session": name, "usd": round(usd, 4),
                        "split": [{"project": p, "entry": i, "usd": round(usd * v / tot, 4)} for (p, i), v in sorted(w.items())]})
    for e in entries.values():
        e["usd"] = round(e["usd"], 4)
    return {"schema": 1, "generated_at": iso(time.time()), "since": iso(start), "until": iso(end),
            "entries": sorted(entries.values(), key=lambda e: (e["project"], e["entry"], e["tier"])),
            "supervisor": sorted(sup, key=lambda s: -s["usd"]),
            "unattributed": {"workers": unatt[0], "usd": round(unatt[1], 4)}}


def main():
    ap = argparse.ArgumentParser(prog="spend-report.py entries")
    ap.add_argument("--since", type=when, required=True)
    ap.add_argument("--until", type=when, default=None)
    ap.add_argument("--json", action="store_true", required=True)
    # default: the file todo.py stats reads; KIT_STATE_DIR is set only inside the kit runner (an agent's shell lacks it)
    ap.add_argument("--out", help="default $KIT_STATE_DIR/spend/entries.json under the kit runner, else stdout; - for stdout")
    a = ap.parse_args()
    state = os.environ.get("KIT_STATE_DIR")
    out = a.out or (os.path.join(state, "spend", "entries.json") if state else "-")
    text = json.dumps(build(a.since, a.until or time.time()), indent=1) + "\n"
    if out == "-":
        sys.stdout.write(text)
        return
    d = os.path.dirname(os.path.abspath(out))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".entries-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, out)
    except BaseException:
        os.unlink(tmp)
        raise


if __name__ == "__main__":
    main()
