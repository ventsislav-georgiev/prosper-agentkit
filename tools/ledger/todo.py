#!/bin/sh
''''exec "${0%"${0##*/}"}../../lib/python3" "$0" "$@" # ''' # sh runs this line (lib/python3 picks the interpreter); Python reads a string
__doc__ = """Transactional CLI for the todo ledgers — one SQLite DB, every project.

Replaces a markdown `todos.md` per project. The markdown prose survives as the
`body` column: an entry is still a heading plus appended rounds and status
lines, so nothing of the old record is flattened into fields, and `export-md`
regenerates the markdown file for diffing. The FIELDS (status, lane, forkable,
blockers) are derived from that body, so there is one parser.

Database: $LEDGER_DB if set, else $KIT_STATE_DIR/ledger.sqlite3 (set by the kit
runner), else ${XDG_DATA_HOME:-~/.local/share}/prosper-agentkit/ledger.sqlite3.

Reorder: todo.py move <project> <id> (--before <id> | --after <id> | --top | --bottom)
--note '<why>' --expect-version <v> [--actor <name>]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

def db_path(env=os.environ):
    if env.get("LEDGER_DB"):
        return Path(env["LEDGER_DB"])
    if env.get("KIT_LEDGER_DB"):
        return Path(env["KIT_LEDGER_DB"])
    if env.get("KIT_STATE_DIR"):
        return Path(env["KIT_STATE_DIR"]) / "ledger.sqlite3"
    data = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "prosper-agentkit" / "ledger.sqlite3"


DB = db_path()
STATUSES = ("OPEN", "IN PROGRESS", "DONE", "DROPPED", "PARKED")

# --- the entry-format contract, as regexes (every quirk below is a real ledger line, not a guess).

# CLAUDE.md writes `### #NNN — title`, but real ledgers also use `##`.
HEADING = re.compile(r"^#{2,4}\s+#(\d+)\b(.*)$")
# One entry often covers several ids (`### #319–#329 — Run-view UX`). Strip only a
# run of id-ish characters that ENDS at a dash, so a title carrying its own dash
# later ("designed 2026-08-14") is left alone.
ID_PREFIX = re.compile(r"^[#\d,/\s—–-]*[—–-]\s*")
# A status line is prose, not a field: `**Status:** superseded by the close recorded
# further down this entry — CLOSED`. Find the first status WORD anywhere in it.
STATUS_LINE = re.compile(r"^\s*[-*]?\s*\*\*Status:\*\*\s*(.*)$")
WORD = re.compile(r"\b(in progress|open|dropped|parked|merged|closed|done|held|retracted)\b", re.I)
# Matched whole, not by \b: without the label nothing distinguishes a status from
# a `**Not done yet**` aside.
BARE_STATUS = re.compile(r"^\s*\*\*(in progress|open|dropped|parked|merged|closed|done)\s*[.:]?\*\*", re.I)
LANE = re.compile(r"\((fork|main)\)", re.I)
# Parenthesized only: a bare "high" or "opus" in prose must not read as a tier.
WORKER_TIER = re.compile(r"\((fable|opus|sonnet|haiku)[^)]*?\b(low|medium|high|xhigh|max)\b[^)]*\)", re.I)
TIER = re.compile(r"^(main|haiku|(sonnet|opus|fable)/(low|medium|high|xhigh|max))$")
DISPATCH_TIER = re.compile(r"worker-(opus|sonnet|haiku|fable)(?:-(\w+))?")
PR = re.compile(r"https?://[^\s/]+/[^\s/]+/[^\s/]+/(?:pull|-/merge_requests)/\d+")
COMMIT = re.compile(r"https?://[^\s/]+/[^\s/]+/[^\s/]+/commit/([0-9a-fA-F]{7,40})(?![0-9A-Za-z_])")
PR_ARG = re.compile(r"^https:[/][/][^\s/]+/[^\s/]+/[^\s/]+/(pull|-/merge_requests)/\d+$")
PARALLEL = re.compile(r"^\s*\*\*Parallel:\*\*\s*(.*)$")
# re.M so the next round number can be counted over a whole body, not just line by line.
ROUND = re.compile(r"^\s*\*\*Round\s+(\d+),\s*(\d{4}-\d{2}-\d{2})", re.M)
# Bookkeeping headings are not titles — a session appending an update as a fresh
# `### #597 — status` block must not rename the entry.
BOOKKEEPING = re.compile(r"^(status|status correction|correction|update|round \d+|note|notes)\b", re.I)

# MERGED/CLOSED are how a finished entry is actually spelled when a PR carried it.
# HELD is a park with a reason, RETRACTED a drop with one.
CANON = {
    "in progress": "IN PROGRESS", "open": "OPEN", "parked": "PARKED", "done": "DONE",
    "merged": "DONE", "closed": "DONE", "dropped": "DROPPED", "held": "PARKED",
    "retracted": "DROPPED",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  name TEXT PRIMARY KEY,
  alias_of TEXT,               -- a second name for one queue
  paths TEXT NOT NULL DEFAULT '',   -- cwd substrings this project claims, one per line
  trailer TEXT NOT NULL DEFAULT '', -- a ledger with no entries at all is all trailer
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
  project TEXT NOT NULL REFERENCES projects(name),
  entry_id TEXT NOT NULL,      -- as written: `001` and `1` are different ledgers' ids
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPEN','IN PROGRESS','DONE','DROPPED','PARKED')),
  lane TEXT NOT NULL DEFAULT 'main' CHECK(lane IN ('main','fork')),
  worker TEXT,
  parallel TEXT NOT NULL DEFAULT '',
  forkable INTEGER NOT NULL DEFAULT 0,
  blocked_by TEXT NOT NULL DEFAULT '',
  last_round TEXT,
  lead TEXT NOT NULL DEFAULT '',   -- section heading / prose above the entry, kept for export
  heading TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  ord INTEGER NOT NULL,        -- order is the work order
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  PRIMARY KEY (project, entry_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  occurred_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  project TEXT NOT NULL,
  qid TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  ruling TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('OPEN','ANSWERED','DROPPED','NOTE')),
  asked_at TEXT NOT NULL,
  answered_at TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  updated_by TEXT NOT NULL,
  PRIMARY KEY (project, qid)
);
CREATE INDEX IF NOT EXISTS entries_status ON entries(project, status);
CREATE INDEX IF NOT EXISTS events_entry ON events(project, entry_id, id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = Path(path or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def actor(args):
    # LEDGER_ACTOR names the writer; inside a named terminal session (DCH_SESSION) its name is used.
    value = (getattr(args, "actor", None) or os.environ.get("LEDGER_ACTOR")
             or os.environ.get("DCH_SESSION"))
    if not value:
        raise SystemExit("error: --actor or LEDGER_ACTOR is required")
    return value


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def derive(body):
    """Every queryable field of an entry, read off its prose. Last status wins."""
    out = {"status": "OPEN", "lane": "main", "worker": None, "parallel": "", "forkable": 0,
           "blocked_by": "", "last_round": None, "has_status": 0}
    for line in body.split("\n"):
        r = ROUND.match(line)
        # Max, not last: a late correction to an older round must not make the entry look stale.
        if r and (out["last_round"] is None or r.group(2) > out["last_round"]):
            out["last_round"] = r.group(2)
        p = PARALLEL.match(line)
        if p:
            out["parallel"] = p.group(1).strip()
            out["forkable"] = int(bool(re.match(r"\s*FORKABLE", out["parallel"], re.I)))
            # Ids before the em dash only — prose after it cites ids as context.
            out["blocked_by"] = ",".join(re.findall(r"#(\d+)", re.split(r"[—–]", out["parallel"])[0]))
            continue
        b = BARE_STATUS.match(line)
        if b:
            out["status"] = CANON[b.group(1).lower()]
            out["has_status"] = 1
            continue
        s = STATUS_LINE.match(line)
        if not s:
            continue
        w = WORD.search(s.group(1))
        if w:
            out["status"] = CANON[w.group(1).lower()]
            out["has_status"] = 1
            lane = LANE.search(s.group(1))
            out["lane"] = lane.group(1).lower() if lane else "main"
            tier = WORKER_TIER.search(s.group(1))
            out["worker"] = f"{tier.group(1).lower()}·{tier.group(2).lower()}" if tier else None
    return out


def parse_md(text):
    """Legacy ledger file -> (entries in file order, trailing text).

    Blocks sharing an id are merged, because CLAUDE.md's `one heading per id,
    ever` was routinely broken by sessions appending updates as fresh headings.
    The later block is kept verbatim inside the merged body — nothing is dropped,
    only moved next to the entry it always belonged to.
    """
    blocks, lead, cur = [], [], None
    for line in text.splitlines(keepends=True):
        m = HEADING.match(line)
        if m:
            cur = {"id": m.group(1), "title": ID_PREFIX.sub("", m.group(2)).strip(),
                   "heading": line, "lead": "".join(lead), "body": []}
            blocks.append(cur)
            lead = []
            continue
        (lead if cur is None else cur["body"]).append(line)

    merged = {}
    for b in blocks:
        b["body"] = "".join(b["body"])
        prev = merged.get(b["id"])
        if prev is None:
            merged[b["id"]] = b
            continue
        if BOOKKEEPING.match(prev["title"] or "") and not BOOKKEEPING.match(b["title"] or ""):
            prev["title"] = b["title"]
        prev["body"] += b["lead"] + b["heading"] + b["body"]
    return list(merged.values()), "".join(lead)


def upsert_project(db, name, **cols):
    db.execute("INSERT OR IGNORE INTO projects(name, created_at) VALUES(?,?)", (name, now()))
    for k, v in cols.items():
        if v is not None:
            db.execute(f"UPDATE projects SET {k}=? WHERE name=?", (v, name))


def resolve(db, name):
    row = db.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
    if not row:
        raise SystemExit(f"error: no project {name!r}")
    return row["alias_of"] or row["name"]


def cmd_init(args):
    connect()
    emit({"database": str(DB), "status": "ready"})


def cmd_import_md(args):
    who = actor(args)
    text = Path(args.file).read_text()
    entries, trailer = parse_md(text)
    stamp = now()
    db = connect()
    db.execute("BEGIN IMMEDIATE")
    try:
        upsert_project(db, args.project, alias_of=args.alias_of, trailer=trailer,
                       paths=Path(args.paths_file).read_text() if args.paths_file else None)
        if db.execute("SELECT COUNT(*) FROM entries WHERE project=?", (args.project,)).fetchone()[0]:
            raise SystemExit(f"error: project {args.project!r} already has entries")
        unparsed = []
        for i, e in enumerate(entries):
            d = derive(e["body"])
            title = e["title"] or f"#{e['id']}"
            if not d["has_status"] or not e["title"]:
                unparsed.append({"id": e["id"], "title": title,
                                 "why": "no Status line" if not d["has_status"] else "heading carries no title"})
            db.execute(
                """INSERT INTO entries(project,entry_id,title,status,lane,worker,parallel,forkable,
                     blocked_by,last_round,lead,heading,body,ord,version,updated_at,updated_by)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (args.project, e["id"], title, d["status"], d["lane"], d["worker"], d["parallel"],
                 d["forkable"], d["blocked_by"], d["last_round"], e["lead"], e["heading"], e["body"],
                 i, stamp, who))
            db.execute("INSERT INTO events(project,entry_id,version,occurred_at,actor,action,payload) VALUES(?,?,?,?,?,?,?)",
                       (args.project, e["id"], 1, stamp, who, "import",
                        json.dumps({"source": args.file, "status": d["status"]}, ensure_ascii=False)))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    emit({"project": args.project, "imported": len(entries), "unparsed": unparsed})


def cmd_export_md(args):
    db = connect()
    name = resolve(db, args.project)
    project = db.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
    rows = db.execute("SELECT lead,heading,body FROM entries WHERE project=? ORDER BY ord", (name,))
    text = "".join(r["lead"] + r["heading"] + r["body"] for r in rows) + project["trailer"]
    if args.out:
        Path(args.out).write_text(text)
        emit({"project": name, "out": args.out, "bytes": len(text.encode())})
    else:
        sys.stdout.write(text)


def row_out(r, body=False):
    out = {k: r[k] for k in ("entry_id", "title", "status", "lane", "worker", "parallel",
                             "forkable", "blocked_by", "last_round", "version", "ord")}
    out["blocked_by"] = [x for x in r["blocked_by"].split(",") if x]
    if body:
        out["body"] = r["body"]
        out["heading"] = r["heading"]
    return out


def cmd_list(args):
    db = connect()
    name = resolve(db, args.project)
    sql = "SELECT * FROM entries WHERE project=?"
    params = [name]
    if args.status:
        sql += " AND status=?"
        params.append(args.status)
    elif not args.all:
        sql += " AND status NOT IN ('DONE','DROPPED')"
    emit([row_out(r) for r in db.execute(sql + " ORDER BY ord", params)])


def cmd_plan(args):
    """Everything not closed, one line each, in work order: what a status answer is built from.
    Flags: IDLE (IN PROGRESS, no write for --idle-days), UNBLOCKED (every blocker is closed),
    and each PARKED entry carries its park line, so a condition that has passed is readable."""
    db = connect()
    name = resolve(db, args.project)
    closed = {r["entry_id"] for r in db.execute(
        "SELECT entry_id FROM entries WHERE project=? AND status IN ('DONE','DROPPED')", (name,))}
    closed |= {r["qid"] for r in db.execute(
        "SELECT qid FROM questions WHERE project=? AND status IN ('ANSWERED','DROPPED')", (name,))}
    today = datetime.now(timezone.utc)

    def days(stamp):
        try:
            then = datetime.fromisoformat(stamp)
        except ValueError:
            return 0
        return (today - (then if then.tzinfo else then.replace(tzinfo=timezone.utc))).days

    def last_status(body):
        lines = [l for l in body.splitlines() if l.startswith("**Status:**")]
        return lines[-1][len("**Status:**"):].strip()[:160] if lines else ""

    for r in db.execute("SELECT * FROM entries WHERE project=? AND status NOT IN ('DONE','DROPPED') ORDER BY ord", (name,)):
        blockers = [b for b in r["blocked_by"].split(",") if b]
        waiting = [b for b in blockers if b not in closed]
        idle = days(r["updated_at"])
        flags = []
        if r["status"] == "IN PROGRESS" and idle >= args.idle_days:
            flags.append("IDLE")
        if blockers and not waiting:
            flags.append("UNBLOCKED")
        line = f"#{r['entry_id']} {r['status']} idle {idle}d"
        if waiting:
            line += " waits on " + ",".join(waiting)
        if flags:
            line += " [" + " ".join(flags) + "]"
        line += " | " + r["title"]
        if r["status"] == "PARKED":
            line += " | " + last_status(r["body"])
        print(line)
    print(f"-- removed in the last {args.removed_days} days (DROPPED), each needs the operator's word in its line:")
    for r in db.execute("SELECT * FROM entries WHERE project=? AND status='DROPPED' ORDER BY ord", (name,)):
        if days(r["updated_at"]) <= args.removed_days:
            print(f"#{r['entry_id']} DROPPED | {r['title']} | {last_status(r['body'])}")
    print("-- sweep: [UNBLOCKED] dispatch it or correct its blockers. [IDLE] no worker or review is live: "
          "dispatch it, or set it OPEN with what is built and what is left. PARKED: if the condition in its "
          "line has passed, set it OPEN. A phase that exists only inside another entry's text gets its own "
          "entry (create --after <parent>). Work the list top down; say so when you take a later entry first.")


def get_entry(db, project, entry_id):
    row = db.execute("SELECT * FROM entries WHERE project=? AND entry_id=?", (project, entry_id)).fetchone()
    if not row:
        raise SystemExit(f"error: {project} has no entry #{entry_id}")
    return row


def cmd_get(args):
    db = connect()
    name = resolve(db, args.project)
    out = row_out(get_entry(db, name, args.id), body=True)
    if args.events:
        out["events"] = [dict(e) for e in db.execute(
            "SELECT * FROM events WHERE project=? AND entry_id=? ORDER BY id", (name, args.id))]
    emit(out)


def cmd_create(args):
    who = actor(args)
    stamp = now()
    db = connect()
    name = resolve(db, args.project)
    db.execute("BEGIN IMMEDIATE")
    try:
        ids = [r["entry_id"] for r in db.execute("SELECT entry_id FROM entries WHERE project=?", (name,))]
        nxt = max((int(i) for i in ids), default=0) + 1
        width = max((len(i) for i in ids if i.startswith("0")), default=0)
        entry_id = str(nxt).zfill(width)
        body = f"**Parallel:** {args.parallel}\n**Status:** OPEN {date.today()} — {args.note or 'queued.'}\n"
        d = derive(body)
        ord_ = (db.execute("SELECT COALESCE(MAX(ord),-1)+1 FROM entries WHERE project=?", (name,)).fetchone()[0])
        if args.after:
            # A phase split out of an entry sits right after it, so it keeps the parent's priority.
            parent = get_entry(db, name, args.after.lstrip("#"))
            ord_ = parent["ord"] + 1
            db.execute("UPDATE entries SET ord=ord+1 WHERE project=? AND ord>=?", (name, ord_))
        db.execute(
            """INSERT INTO entries(project,entry_id,title,status,lane,worker,parallel,forkable,
                 blocked_by,last_round,lead,heading,body,ord,version,updated_at,updated_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,'',?,?,?,1,?,?)""",
            (name, entry_id, args.title, d["status"], d["lane"], d["worker"], d["parallel"],
             d["forkable"], d["blocked_by"], d["last_round"],
             f"\n### #{entry_id} — {args.title}\n", body, ord_, stamp, who))
        db.execute("INSERT INTO events(project,entry_id,version,occurred_at,actor,action,payload) VALUES(?,?,?,?,?,?,?)",
                   (name, entry_id, 1, stamp, who, "create", json.dumps({"title": args.title}, ensure_ascii=False)))
        row = get_entry(db, name, entry_id)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    emit(row_out(row, body=True))


def rewrite(db, project, entry_id, expect_version, who, action, new_body, payload, also=None):
    """Every write is the same write: replace the body, re-derive every field from it."""
    stamp = now()
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = get_entry(db, project, entry_id)
        if cur["version"] != expect_version:
            print(json.dumps({"error": "version_conflict", "current": row_out(cur, body=True)},
                             ensure_ascii=False, sort_keys=True), file=sys.stderr)
            raise SystemExit(3)
        if also:
            also(db)  # extra writes in the same transaction, after the version check
        d = derive(new_body)
        version = cur["version"] + 1
        db.execute(
            """UPDATE entries SET body=?, status=?, lane=?, worker=?, parallel=?, forkable=?,
                 blocked_by=?, last_round=?, version=?, updated_at=?, updated_by=?
               WHERE project=? AND entry_id=? AND version=?""",
            (new_body, d["status"], d["lane"], d["worker"], d["parallel"], d["forkable"],
             d["blocked_by"], d["last_round"], version, stamp, who, project, entry_id, expect_version))
        db.execute("INSERT INTO events(project,entry_id,version,occurred_at,actor,action,payload) VALUES(?,?,?,?,?,?,?)",
                   (project, entry_id, version, stamp, who, action, json.dumps(payload, ensure_ascii=False)))
        row = get_entry(db, project, entry_id)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    return row


def cmd_set_status(args):
    who = actor(args)
    db = connect()
    name = resolve(db, args.project)
    cur = get_entry(db, name, args.id)
    if args.status == "DROPPED" and not (args.operator or "").strip():
        # Nothing leaves the list on an agent's own decision: a drop carries the operator's words.
        raise SystemExit('error: DROPPED needs --operator "<the operator\'s own words>"; '
                         "without them keep the entry OPEN and ask with `todo.py ask`")
    for u in args.pr:
        if not PR_ARG.match(u):
            usage_error(f"--pr must match {PR_ARG.pattern}: {u}")
    in_note = [m.group(0) for m in PR.finditer(args.note)]
    prs = list(dict.fromkeys(in_note + args.pr))
    extra = "".join(f" PR: {u}" for u in dict.fromkeys(args.pr) if u not in in_note)
    tag = " (fork)" if args.fork else ""
    tier = f" ({args.worker.replace('/', ', ')} effort)" if args.worker else ""
    said = f' Operator: "{args.operator.strip()}"' if args.operator else ""
    line = f"**Status:** {args.status}{tag} {date.today()} — {args.note}{said}{tier}{extra}\n"
    body = cur["body"].rstrip("\n") + "\n" + line
    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "status", body,
                         {"status": args.status, "lane": "fork" if args.fork else "main", "note": args.note,
                          **({"prs": prs} if prs else {}), **({"worker": args.worker} if args.worker else {})})))


def usage_error(msg):
    print("error: " + msg, file=sys.stderr)
    raise SystemExit(2)


def review_tier(db, project, entry_id):
    """Default tier: the latest dispatch note's worker-<model>-<effort>, else the latest status payload worker."""
    for (pl,) in db.execute("SELECT payload FROM events WHERE project=? AND entry_id=? AND action='append:dispatch' ORDER BY id DESC",
                            (project, entry_id)):
        m = DISPATCH_TIER.search(json.loads(pl).get("text", ""))
        if m:
            return m.group(1) if m.group(1) == "haiku" else f"{m.group(1)}/{m.group(2)}"
        break  # the latest dispatch decides; an unreadable one falls through to the claim's worker
    for (pl,) in db.execute("SELECT payload FROM events WHERE project=? AND entry_id=? AND action='status' ORDER BY id DESC",
                            (project, entry_id)):
        if json.loads(pl).get("worker"):
            return json.loads(pl)["worker"]
    usage_error("no tier to default to (no dispatch note, no claimed worker): give --tier <model>/<effort> or --tier main")


def cmd_append(args):
    who = actor(args)
    db = connect()
    name = resolve(db, args.project)
    cur = get_entry(db, name, args.id)
    text = args.text
    extra = {}
    if (args.kind == "review") != bool(args.verdict):
        usage_error("--verdict is required with --kind review and refused with any other kind")
    if args.tier and args.kind != "review":
        usage_error("--tier only goes with --kind review")
    if args.kind == "review":
        if not args.text.strip():
            usage_error("a review needs non-empty findings text")
        verdict = args.verdict
        tier = args.tier or review_tier(db, name, args.id)
        if not TIER.match(tier):
            usage_error(f"--tier must match {TIER.pattern}")
        n = db.execute("SELECT COUNT(*) FROM events WHERE project=? AND entry_id=? AND action='append:review'",
                       (name, args.id)).fetchone()[0] + 1
        text = f"**Review r{n}, {date.today()}: {verdict.upper()} ({tier})** — {args.text}"
        extra = {"verdict": verdict, "tier": tier, "review_round": n}
    elif args.kind == "round":
        n = max((int(m.group(1)) for m in ROUND.finditer(cur["body"])), default=0) + 1
        text = f"**Round {n}, {date.today()}** — {text}"
    elif args.kind == "dispatch":
        text = f"**Dispatch note, {date.today()}** — {text}"
    body = cur["body"].rstrip("\n") + "\n\n" + text + "\n"
    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "append:" + args.kind, body,
                         {"kind": args.kind, "text": args.text, **extra})))


def cmd_set_parallel(args):
    who = actor(args)
    db = connect()
    name = resolve(db, args.project)
    cur = get_entry(db, name, args.id)
    line = f"**Parallel:** {args.text}"
    lines = cur["body"].split("\n")
    for i, ln in enumerate(lines):
        if PARALLEL.match(ln):
            lines[i] = line
            break
    else:
        lines.insert(0, line)
    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "parallel", "\n".join(lines),
                         {"parallel": args.text})))


def cmd_move(args):
    who = actor(args)
    opts = [o for o in (args.before, args.after, args.top, args.bottom) if o]
    if len(opts) != 1:
        raise SystemExit("error: move needs exactly one of --before, --after, --top, --bottom")
    if not args.note.strip():
        raise SystemExit("error: move needs a non-empty --note (the reason)")
    db = connect()
    name = resolve(db, args.project)
    cur = get_entry(db, name, args.id)
    other = (args.before or args.after or "").lstrip("#")
    if other:
        if other == args.id:
            raise SystemExit(f"error: cannot move #{args.id} relative to itself")
        get_entry(db, name, other)
    what = (f"before #{other}" if args.before else f"after #{other}" if args.after
            else "to the top" if args.top else "to the bottom")
    # Single line starting "**Move," so no status/parallel/round regex can match it.
    note = " ".join(args.note.split())
    body = cur["body"].rstrip("\n") + f"\n\n**Move, {date.today()}** — Moved {what}: {note}\n"

    def reorder(db):
        ids = [r["entry_id"] for r in db.execute(
            "SELECT entry_id FROM entries WHERE project=? ORDER BY ord, entry_id", (name,))]
        old = {r["entry_id"]: r["ord"] for r in db.execute("SELECT entry_id, ord FROM entries WHERE project=?", (name,))}
        ids.remove(args.id)
        i = 0 if args.top else len(ids) if args.bottom else ids.index(other) + (1 if args.after else 0)
        ids.insert(i, args.id)
        for n, e in enumerate(ids):  # dense 0..n-1; only rows whose ord changes are written, no version bump
            if old[e] != n:
                db.execute("UPDATE entries SET ord=? WHERE project=? AND entry_id=?", (n, name, e))

    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "move", body,
                         {"position": what, "note": args.note}, also=reorder)))


def cmd_import_questions(args):
    """The operator-questions file: one `## ` block per row, rulings folded into their question.

    Ids run `## 1.` … `## 9.` then `## OQ-10` …, and a block that names an existing
    id (an addendum, a correction, a RULING) belongs to that row rather than to a
    new one. Everything else is kept as a NOTE row — a block is never dropped.
    """
    who = actor(args)
    stamp = now()
    db = connect()
    upsert_project(db, args.project)
    notes = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for block in re.split(r"^(?=## )", Path(args.file).read_text(), flags=re.M):
            if not block.strip():
                continue
            head, _, body = block.partition("\n")
            title = head[3:].strip() if head.startswith("## ") else "(preamble)"
            ruling = title.upper().startswith("RULING")
            m = (re.search(r"\bO?Q-?(\d+[a-z]?)\b", title) if ruling
                 else re.match(r"(?:OQ-|)(\d+[a-z]?)[.\s]", title))
            if m:
                qid = f"OQ-{m.group(1)}"
            else:
                notes += 1
                qid = f"NOTE-{notes}"
            row = db.execute("SELECT * FROM questions WHERE project=? AND qid=?", (args.project, qid)).fetchone()
            if row is None:
                db.execute("""INSERT INTO questions(project,qid,title,body,ruling,status,asked_at,answered_at,updated_by)
                              VALUES(?,?,?,?,?,?,?,?,?)""",
                           (args.project, qid, title, body, block if ruling else "",
                            "ANSWERED" if ruling else ("NOTE" if qid.startswith("NOTE") else "OPEN"),
                            stamp, stamp if ruling else None, who))
            elif ruling:
                db.execute("""UPDATE questions SET ruling=ruling||?, status='ANSWERED', answered_at=?,
                              version=version+1, updated_by=? WHERE project=? AND qid=?""",
                           ("\n\n" + block, stamp, who, args.project, qid))
            else:
                db.execute("""UPDATE questions SET body=body||?, version=version+1, updated_by=?
                              WHERE project=? AND qid=?""", ("\n\n" + block, who, args.project, qid))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    emit({"project": args.project, "questions": db.execute(
        "SELECT COUNT(*) FROM questions WHERE project=?", (args.project,)).fetchone()[0]})


OPTIONS_MAX, OPTION_LEN = 8, 300


def options_block(options, recommend):
    """The fixed block `ask --option/--recommend` ends a question body with; xray.py parses it back into chips."""
    if len(options) > OPTIONS_MAX:
        raise SystemExit(f"error: at most {OPTIONS_MAX} --option values")
    for t in options + ([recommend] if recommend is not None else []):
        if not t.strip() or len(t) > OPTION_LEN or any(c in t for c in "\r\n"):
            raise SystemExit(f"error: --option/--recommend text must be 1 to {OPTION_LEN} characters on one line")
    lines = ["Options:"] + [f"({i}) {t.strip()}" for i, t in enumerate(options, 1)] if options else []
    if recommend is not None:
        rec = recommend.strip()
        if rec.isdigit():  # a bare number names one of this block's options
            if not 1 <= int(rec) <= len(options):
                raise SystemExit(f"error: --recommend {rec} names no --option")
            rec = f"({int(rec)})"
        lines.append(f"Recommendation: {rec}")
    return "\n".join(lines)


def cmd_ask(args):
    who = actor(args)
    block = options_block(args.option, args.recommend) if args.option or args.recommend is not None else ""
    if block:
        args.body = (args.body + "\n\n" + block) if args.body else block
    stamp = now()
    db = connect()
    row = db.execute("SELECT * FROM questions WHERE project=? AND qid=?", (args.project, args.qid)).fetchone()
    if row is None:
        if not args.title:
            raise SystemExit("error: --title is required when asking a new question")
        db.execute(
            "INSERT INTO questions(project,qid,title,body,status,asked_at,updated_by) VALUES(?,?,?,?,?,?,?)",
            (args.project, args.qid, args.title, args.body or "", args.status or "OPEN", stamp, who))
        status = args.status or "OPEN"
        version = 1
    else:
        if args.expect_version is not None and row["version"] != args.expect_version:
            print(json.dumps({"error": "version_conflict", "current": row["version"]},
                             ensure_ascii=False, sort_keys=True), file=sys.stderr)
            raise SystemExit(3)
        body = args.body or ""
        if args.replace:
            new_body = body
        else:
            new_body = (row["body"] + "\n\n" + body) if body else row["body"]
        title = args.title if args.title else row["title"]
        status = args.status if args.status else row["status"]
        version = row["version"] + 1
        db.execute("""UPDATE questions SET title=?, body=?, status=?, version=?, updated_by=?
                      WHERE project=? AND qid=?""", (title, new_body, status, version, who, args.project, args.qid))
    emit({"project": args.project, "qid": args.qid, "status": status, "version": version})


def cmd_rule(args):
    who = actor(args)
    stamp = now()
    db = connect()
    row = db.execute("SELECT * FROM questions WHERE project=? AND qid=?", (args.project, args.qid)).fetchone()
    if not row:
        raise SystemExit(f"error: no question {args.qid} in {args.project}")
    if args.expect_version is not None and row["version"] != args.expect_version:
        print(json.dumps({"error": "version_conflict", "current": row["version"]},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise SystemExit(3)
    ruling = (row["ruling"] + "\n\n" if row["ruling"] else "") + args.text
    version = row["version"] + 1
    if args.keep_status:
        db.execute("""UPDATE questions SET ruling=?, version=?, updated_by=?
                      WHERE project=? AND qid=?""", (ruling, version, who, args.project, args.qid))
        status = row["status"]
    else:
        db.execute("""UPDATE questions SET ruling=?, status='ANSWERED', answered_at=?, version=?,
                      updated_by=? WHERE project=? AND qid=?""", (ruling, stamp, version, who, args.project, args.qid))
        status = "ANSWERED"
    emit({"project": args.project, "qid": args.qid, "status": status, "version": version})


def cmd_questions(args):
    db = connect()
    sql = "SELECT project,qid,title,status,asked_at,answered_at FROM questions WHERE project=?"
    params = [args.project]
    if args.status:
        sql += " AND status=?"
        params.append(args.status)
    emit([dict(r) for r in db.execute(sql + " ORDER BY rowid", params)])


# --- stats: read-only velocity metrics over the event log (schema 1; see `stats --help`).

STATS_SCHEMA = 1
PAREN = re.compile(r"\([^()]*\)")  # a parenthesised FAIL cites an older review
VERDICT = re.compile(r"(?i:\b(?:review(?:er)?|QA|critic|gate|re-?check)\b)[^\n]{0,120}?(?<![0-9] )\b(PASS|FAIL)(?:ED|ES)?\b")
TIER_ANY = re.compile(r"(opus|sonnet|haiku|fable)[-/·\s,]{0,3}(low|medium|high|xhigh|max)?", re.I)
BULK, BULK_MIN = 10, 15  # a close is a bulk sweep when its actor wrote >= 10 DONE within +-15 minutes

LIFE_SQL = """
WITH ev AS (
  SELECT project, entry_id, id, occurred_at, action, json_extract(payload,'$.status') AS st
  FROM events WHERE action IN ('create','import','status') AND (:p IS NULL OR project = :p)
), life AS (
  SELECT project, entry_id,
    MIN(CASE WHEN action='create' THEN occurred_at END)                      AS created_at,
    MIN(CASE WHEN action='status' AND st='IN PROGRESS' THEN occurred_at END) AS first_ip,
    MAX(CASE WHEN action='status' AND st='DONE' THEN id END)                 AS done_id,
    MAX(CASE WHEN action='status' THEN id END)                               AS last_id,
    SUM(action='status' AND st='DONE')                                       AS done_events
  FROM ev GROUP BY project, entry_id
)
SELECT l.project, l.entry_id, l.created_at, l.first_ip, l.done_id, l.last_id, l.done_events, n.status,
  d.occurred_at AS done_at, d.actor AS done_actor, d.payload AS done_payload,
  (julianday(d.occurred_at) - julianday(l.created_at)) * 24 AS lead_h,
  (julianday(d.occurred_at) - julianday(l.first_ip))  * 24 AS cycle_h
FROM life l
JOIN entries n ON n.project = l.project AND n.entry_id = l.entry_id
LEFT JOIN events d ON d.id = l.done_id
"""
SWEEP_SQL = f"""
WITH d AS (
  SELECT id, actor, julianday(occurred_at) * 1440 AS m FROM events
  WHERE action = 'status' AND json_extract(payload,'$.status') = 'DONE'
)
SELECT id FROM (SELECT id, COUNT(*) OVER (PARTITION BY actor ORDER BY m
                RANGE BETWEEN {BULK_MIN} PRECEDING AND {BULK_MIN} FOLLOWING) AS burst FROM d)
WHERE burst >= {BULK}
"""
WALK_SQL = """
SELECT id, project, entry_id, actor, action, occurred_at,
  json_extract(payload,'$.status') AS st, json_extract(payload,'$.worker') AS worker,
  json_extract(payload,'$.verdict') AS verdict, json_extract(payload,'$.tier') AS tier,
  json_extract(payload,'$.review_round') AS review_round,
  CASE WHEN action = 'append:dispatch' OR (action = 'append:round' AND occurred_at >= :s)
       THEN json_extract(payload,'$.text') END AS text
FROM events
WHERE action IN ('create','import','status','append:dispatch','append:round','append:review')
  AND (:p IS NULL OR project = :p)
ORDER BY id
"""
IDLE_SQL = """
WITH e AS (
  SELECT project, entry_id,
    (julianday(occurred_at) - julianday(LAG(occurred_at) OVER (PARTITION BY project, entry_id ORDER BY id))) * 24 AS gap_h
  FROM events WHERE (:p IS NULL OR project = :p)
)
SELECT project, entry_id, MAX(gap_h) AS max_gap_h, COALESCE(SUM(CASE WHEN gap_h > 8 THEN gap_h END), 0) AS idle_h
FROM e GROUP BY project, entry_id
"""
QUESTIONS_SQL = """
SELECT project, status, asked_at, answered_at, (julianday(answered_at) - julianday(asked_at)) * 24 AS rule_h
FROM questions WHERE status IN ('OPEN','ANSWERED','DROPPED') AND asked_at >= :s AND (:p IS NULL OR project = :p)
"""


def open_ro(path):
    """Stats never write: no folder, no WAL switch, no schema script, no empty ledger on a fresh machine."""
    if not path.is_file():
        print(f"error: no ledger at {path}", file=sys.stderr)
        raise SystemExit(4)
    try:
        db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=30)
        db.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.OperationalError:
        # A WAL ledger with no -shm beside it (no writer open) refuses mode=ro; mode=rw never creates
        # the file, and query_only refuses every write on this connection.
        db = sqlite3.connect(f"file:{quote(str(path))}?mode=rw", uri=True, timeout=30)
        db.execute("PRAGMA query_only=ON")
    db.row_factory = sqlite3.Row
    return db


def norm_tier(s):
    """worker-opus-medium, opus·medium and opus/medium are one key; a model with no effort is the model."""
    if not s:
        return None
    if s == "main":
        return s
    m = TIER_ANY.search(s)
    if not m:
        return None
    return f"{m[1].lower()}/{m[2].lower()}" if m[2] else m[1].lower()


def legacy_verdict(text):
    m = VERDICT.search(PAREN.sub(" ", (text or "")[:300]))
    return m.group(1).lower() if m else None


def pct(xs, q):
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, max(0, -(-len(xs) * q // 100) - 1))], 2)  # nearest rank


def dist(values):
    xs = sorted(x for x in values if x is not None)
    return {"n": len(xs), "p50": pct(xs, 50), "p90": pct(xs, 90),
            "mean": round(sum(xs) / len(xs), 2) if xs else None}


def rate(part, whole):
    return round(part / whole, 3) if whole else None


def stats_collect(db, project, since, until):
    s, p = since.isoformat(timespec="seconds"), project
    sweeps = {r[0] for r in db.execute(SWEEP_SQL)}
    walk = db.execute(WALK_SQL, {"p": p, "s": s}).fetchall()

    # One pass in id order: iteration counts, the entry tier, verdicts, park spans, the daily WIP replay.
    counts, tier_dispatch, tier_worker = {}, {}, {}
    structured, legacy, parks = [], [], []
    state, open_park, tally = {}, {}, {"IN PROGRESS": 0, "PARKED": 0}
    wip_days = {}
    for r in walk:
        key, act = (r["project"], r["entry_id"]), r["action"]
        c = counts.setdefault(key, {"dispatches": 0, "rounds": 0, "reviews": 0})
        if act == "append:dispatch":
            c["dispatches"] += 1
            m = DISPATCH_TIER.search(r["text"] or "")
            tier_dispatch[key] = norm_tier(m.group(0)) if m else None
        elif act == "append:review":
            c["reviews"] += 1
            if r["occurred_at"] >= s and r["verdict"] in ("pass", "fail"):
                structured.append({"key": key, "at": r["occurred_at"], "verdict": r["verdict"], "round": r["review_round"],
                                   "k": {"project": key[0], "actor": r["actor"], "tier": norm_tier(r["tier"]) or "none"}})
        elif act == "append:round":
            c["rounds"] += 1
            v = None if r["actor"].startswith("worker-") else legacy_verdict(r["text"])
            if v:
                legacy.append({"key": key, "at": r["occurred_at"], "verdict": v,
                               "k": {"project": key[0], "actor": r["actor"], "tier": tier_dispatch.get(key) or "none"}})
        else:
            new = "OPEN" if act == "create" else (r["st"] or "OPEN")
            if act == "status" and r["worker"]:
                tier_worker[key] = norm_tier(r["worker"])
            old = state.get(key)
            if old in tally:
                tally[old] -= 1
            if new in tally:
                tally[new] += 1
            state[key] = new
            if r["occurred_at"][:10] >= s[:10]:
                wip_days[r["occurred_at"][:10]] = dict(tally)
            if act == "status":
                if new == "PARKED" and key not in open_park:
                    open_park[key] = (r["occurred_at"], r["actor"])
                elif new != "PARKED" and key in open_park:
                    parks.append((key, *open_park.pop(key), r["occurred_at"], False))
    entry_tier = lambda key: tier_worker.get(key) or tier_dispatch.get(key) or "none"  # structured worker wins
    now_iso = until.isoformat(timespec="seconds")
    parks += [(key, at, who, now_iso, True) for key, (at, who) in open_park.items()]
    parked = [{"dwell_d": (datetime.fromisoformat(end) - datetime.fromisoformat(at)).total_seconds() / 86400,
               "ongoing": ongoing, "k": {"project": key[0], "actor": who, "tier": entry_tier(key)}}
              for key, at, who, end, ongoing in parks if end >= s]
    # Structured review events win: an entry with any of them drops its free-text verdicts.
    has_review = {key for key, c in counts.items() if c["reviews"]}
    legacy = [v for v in legacy if v["key"] not in has_review and v["at"] >= s]
    seen = {}
    for v in legacy:  # legacy round = ordinal of verdict-bearing rounds inside the window
        seen[v["key"]] = v["round"] = seen.get(v["key"], 0) + 1
    for v in structured:
        v["estimated"] = False
    for v in legacy:
        v["estimated"] = True

    closes, reopened_open, dropped = [], 0, []
    for r in db.execute(LIFE_SQL, {"p": p}):
        key = (r["project"], r["entry_id"])
        if r["status"] != "DONE" and (r["done_events"] or 0) >= 1:
            reopened_open += 1
        if r["status"] != "DONE" or r["done_id"] is None or r["done_id"] != r["last_id"] or r["done_at"] < s:
            continue
        pl = json.loads(r["done_payload"])
        prs, est = (pl["prs"], False) if pl.get("prs") else (list(dict.fromkeys(PR.findall(pl.get("note") or ""))), True)
        closes.append({"key": key, "at": r["done_at"], "created": r["created_at"], "first_ip": r["first_ip"],
                       "lead_h": r["lead_h"], "cycle_h": r["cycle_h"], "reopened": r["done_events"] > 1,
                       "sweep": r["done_id"] in sweeps, "commits": commit_urls(pl.get("note")), "prs": prs, "prs_estimated": est and bool(prs),
                       "it": counts.get(key, {"dispatches": 0, "rounds": 0, "reviews": 0}),
                       "k": {"project": key[0], "actor": r["done_actor"], "tier": entry_tier(key)}})
    for r in db.execute("""SELECT e.project, e.entry_id, e.actor FROM events e JOIN entries n
                           ON n.project = e.project AND n.entry_id = e.entry_id AND n.status = 'DROPPED'
                           WHERE e.action = 'status' AND json_extract(e.payload,'$.status') = 'DROPPED'
                             AND e.occurred_at >= :s AND (:p IS NULL OR e.project = :p)""", {"p": p, "s": s}):
        dropped.append({"k": {"project": r[0], "actor": r[2], "tier": entry_tier((r[0], r[1]))}})
    idle = {(r[0], r[1]): (r[2], r[3]) for r in db.execute(IDLE_SQL, {"p": p})}
    questions = [{"status": r["status"], "at": r["asked_at"],
                  "rule_h": r["rule_h"] if r["status"] == "ANSWERED" and r["answered_at"] and r["answered_at"] > r["asked_at"] else None,
                  "k": {"project": r["project"]}} for r in db.execute(QUESTIONS_SQL, {"p": p, "s": s})]
    return {"closes": closes, "verdicts": structured + legacy, "parked": parked, "dropped": dropped,
            "questions": questions, "idle": idle, "wip_days": wip_days, "reopened_open": reopened_open}


def commit_urls(note):
    """Distinct commit URLs in a note; a short and a full sha of one commit count once (owner/repo + first 7 hex)."""
    return list({(m.group(0).rsplit("/commit/", 1)[0], m.group(1)[:7].lower()): m.group(0) for m in COMMIT.finditer(note or "")}.values())


def commit_key(u):
    base, sha = u.rsplit("/commit/", 1)
    return base, sha[:7].lower()


def calendar(since, until):
    day, out = since.date(), []
    while day <= until.date():
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def landings(closes, field="prs"):
    """Distinct PR (or commit) URLs, each on the first close naming it: [(at, url, estimated)]. Commits are never estimated."""
    seen = {}
    for c in sorted(closes, key=lambda c: c["at"]):
        for u in c[field]:
            seen.setdefault(commit_key(u) if field == "commits" else u, (c["at"], u, field == "prs" and c["prs_estimated"]))
    return sorted(seen.values())


def spend_block(spend, path, since, closes, pick):
    if spend is None:
        return None
    rows = [e for e in spend.get("entries") or []
            if pick({"project": e.get("project"), "tier": norm_tier(e.get("tier")) or "none", "actor": None})]
    per = {}
    for e in rows:
        x = per.setdefault((e.get("project"), str(e.get("entry"))), {"usd": 0.0, "tokens": 0, "sup": 0.0})
        x["usd"] += e.get("usd") or 0
        x["tokens"] += sum((e.get("tokens") or {}).values())
    for s in spend.get("supervisor") or []:
        for sp in s.get("split") or []:
            if (sp.get("project"), str(sp.get("entry"))) in per:
                per[(sp.get("project"), str(sp.get("entry")))]["sup"] += sp.get("usd") or 0
    done = [per[c["key"]] for c in closes if c["key"] in per]
    usd = sum(e.get("usd") or 0 for e in rows)
    unattr = (spend.get("unattributed") or {}).get("usd") or 0
    gen = spend.get("generated_at")
    try:
        age = round((datetime.now(timezone.utc) - datetime.fromisoformat(gen)).total_seconds() / 3600, 1)
    except (TypeError, ValueError):
        age = None
    return {"file": str(path), "generated_at": gen, "age_h": age,
            "window_covered": bool(spend.get("since")) and spend["since"] <= since.isoformat(timespec="seconds"),
            "coverage_usd_pct": round(100 * usd / (usd + unattr), 1) if usd + unattr else None,
            "closed_with_spend": len(done), "usd_workers": round(usd, 2),
            "usd_supervisor": round(sum(x["sup"] for x in per.values()), 2),
            "usd_per_closed": dist(x["usd"] for x in done), "tokens_per_closed": dist(x["tokens"] for x in done),
            "usd_per_closed_incl_supervisor": dist(x["usd"] + x["sup"] for x in done), "unattributed_usd": unattr}


def stats_block(d, pick, days, now_counts, spend):
    closes = [c for c in d["closes"] if pick(c["k"])]
    head = [c for c in closes if not c["sweep"]]  # OQ-213: bulk sweeps leave the headline percentiles
    lead = lambda cs: dist(c["lead_h"] for c in cs if c["created"])
    cycle = lambda cs: dist(c["cycle_h"] for c in cs if c["first_ip"] and c["cycle_h"] >= 0)
    vs = [v for v in d["verdicts"] if pick(v["k"])]
    fails = [v for v in vs if v["verdict"] == "fail"]
    closed_keys = {c["key"] for c in closes}
    per_entry = {}
    for v in vs:
        per_entry.setdefault(v["key"], []).append(v["verdict"])
    by_round, by_tier = {}, {}
    for v in vs:
        rk = str(min(int(v["round"] or 1), 4)).replace("4", "4+")
        for table, k in ((by_round, rk), (by_tier, v["k"]["tier"])):
            t = table.setdefault(k, [0, 0])
            t[0] += 1
            t[1] += v["verdict"] == "fail"
    est_v = sum(v["estimated"] for v in vs)
    land = landings(closes)
    est_p = sum(e for _, _, e in land)
    stamps = [datetime.fromisoformat(at) for at, _, _ in land]
    pr_days = {}
    for at, _, _ in land:
        pr_days[at[:10]] = pr_days.get(at[:10], 0) + 1
    cland = landings(closes, "commits")
    cstamps = [datetime.fromisoformat(at) for at, _, _ in cland]
    commit_days = {}
    for at, _, _ in cland:
        commit_days[at[:10]] = commit_days.get(at[:10], 0) + 1
    close_days = {}
    for c in closes:
        close_days[c["at"][:10]] = close_days.get(c["at"][:10], 0) + 1
    qs = [q for q in d["questions"] if pick(q["k"])]
    parks = [x for x in d["parked"] if pick(x["k"])]
    idle = [d["idle"][c["key"]] for c in closes if c["key"] in d["idle"]]
    return {
        "closed": len(closes), "closed_sweep": len(closes) - len(head),
        "closed_imported": sum(1 for c in closes if not c["created"]),
        "closed_without_progress": sum(1 for c in closes if not c["first_ip"]),
        "reopened": sum(c["reopened"] for c in closes), "dropped": sum(1 for x in d["dropped"] if pick(x["k"])),
        "lead_h": lead(head), "lead_h_all": lead(closes), "cycle_h": cycle(head), "cycle_h_all": cycle(closes),
        "dispatches_per_closed": dist(c["it"]["dispatches"] for c in closes),
        "rounds_per_closed": dist(c["it"]["rounds"] for c in closes),
        "review": {
            "verdicts": len(vs), "fail": len(fails), "fail_rate": rate(len(fails), len(vs)), "estimated": est_v,
            "source": "estimated" if est_v == len(vs) and vs else "structured" if not est_v and vs else "mixed" if vs else None,
            "entries_reviewed": len(per_entry), "entries_with_fail": sum("fail" in x for x in per_entry.values()),
            "reviews_before_close": dist(len(x) for k, x in per_entry.items() if k in closed_keys),
            "by_round": [{"round": k, "verdicts": n, "fail": f, "fail_rate": rate(f, n)} for k, (n, f) in sorted(by_round.items())],
            "by_tier": [{"tier": k, "verdicts": n, "fail": f, "fail_rate": rate(f, n)} for k, (n, f) in sorted(by_tier.items())]},
        "parked": {"now": now_counts.get("PARKED"), "events": len(parks),
                   "dwell_d_resolved": dist(x["dwell_d"] for x in parks if not x["ongoing"]),
                   "dwell_d_ongoing": dist(x["dwell_d"] for x in parks if x["ongoing"])},
        "questions": {"asked": len(qs), "per_day": round(len(qs) / days, 1) if days else None,
                      "per_100_closed": round(100 * len(qs) / len(closes), 1) if closes else None,
                      "open_now": now_counts.get("OQ"), "ask_to_rule_h": dist(q["rule_h"] for q in qs)},
        "flow": {"closes_per_day": dist(close_days.get(day, 0) for day in d["calendar"]), "wip_now": now_counts.get("IN PROGRESS")},
        "prs": {"landed": len(land), "estimated": est_p,
                "source": "estimated" if est_p == len(land) and land else "structured" if not est_p and land else "mixed" if land else None,
                "pr_share": rate(sum(1 for c in closes if c["prs"]), len(closes)),
                "per_day": dist(pr_days.get(day, 0) for day in d["calendar"]),
                "gap_h": dist((b - a).total_seconds() / 3600 for a, b in zip(stamps, stamps[1:]))},
        "commits": {"landed": len(cland),
                    "commit_share": rate(sum(1 for c in closes if c["commits"]), len(closes)),
                    "per_day": dist(commit_days.get(day, 0) for day in d["calendar"]),
                    "gap_h": dist((b - a).total_seconds() / 3600 for a, b in zip(cstamps, cstamps[1:]))},
        "idle": {"max_gap_h": dist(i[0] for i in idle), "idle_h": dist(i[1] for i in idle)},
        "spend": spend_block(*spend, closes, pick) if spend else None,
    }


def stats_hud(label, t):
    r, p, k = t["review"], t["prs"], t["commits"]
    parts = ([f"{'~' if p['estimated'] else ''}{p['landed']} PRs"] if p["landed"] or not k["landed"] else []) + \
            ([f"{k['landed']} commits"] if k["landed"] else [])
    fail = "-" if r["fail_rate"] is None else f"{'~' if r['estimated'] else ''}{round(100 * r['fail_rate'])}%"
    cyc = t["cycle_h"]["p50"]
    return (f"{label} {t['closed']} closed | cycle {'-' if cyc is None else f'{cyc:g}h'} | review fail {fail} | "
            f"{' + '.join(parts)} | WIP {t['flow']['wip_now']} | "
            f"parked {t['parked']['now']} | OQ {t['questions']['open_now']}")


def stats_text(out):
    t, sc = out["totals"], out["scope"]
    g = lambda x, u="": "-" if x is None else f"{x:g}{u}"
    pd = lambda d, u="": f"p50 {g(d['p50'], u)}  p90 {g(d['p90'], u)}"
    tl = lambda e: "~" if e else ""
    r, pr, q, pk, cm = t["review"], t["prs"], t["questions"], t["parked"], t["commits"]
    lines = [
        f"ledger stats  {sc['projects']}  since {sc['since'][:10]} ({sc['days']:g} d)   ~ = estimated from free text",
        f"closed {t['closed']} (sweep {t['closed_sweep']}, reopened {t['reopened']}, imported {t['closed_imported']}, "
        f"no IN PROGRESS {t['closed_without_progress']})   dropped {t['dropped']}",
        f"lead   {pd(t['lead_h'], 'h')}        cycle {pd(t['cycle_h'], 'h')}     (sweeps excluded)",
        f"iter   dispatches/closed {pd(t['dispatches_per_closed'])} (mean {g(t['dispatches_per_closed']['mean'])})   "
        f"rounds {pd(t['rounds_per_closed'])}",
        f"review {tl(r['estimated'])}{g(r['fail_rate'] and round(100 * r['fail_rate'], 1), '%')} fail ({r['fail']}/{r['verdicts']})  "
        f"entries with a fail {r['entries_with_fail']}/{r['entries_reviewed']}  reviews before close {pd(r['reviews_before_close'])}",
        "       " + "  ".join(f"r{b['round']} {tl(r['estimated'])}{g(round(100 * b['fail_rate'], 1), '%')}" for b in r["by_round"]),
        f"parked {pk['now']} now   dwell resolved {pd(pk['dwell_d_resolved'], 'd')}   ongoing {pd(pk['dwell_d_ongoing'], 'd')}",
        f"OQ     {q['asked']} asked ({g(q['per_day'])}/day, {g(q['per_100_closed'])} per 100 closed)  {q['open_now']} open   "
        f"ask->ruling {pd(q['ask_to_rule_h'], 'h')}",
        f"flow   closes/day {pd(t['flow']['closes_per_day'])}   WIP now {t['flow']['wip_now']}",
        f"PRs    {tl(pr['estimated'])}{pr['landed']} landed  per day {pd(pr['per_day'])}   gap {pd(pr['gap_h'], 'h')}",
        f"commits {cm['landed']} landed  per day {pd(cm['per_day'])}   gap {pd(cm['gap_h'], 'h')}",
        f"idle   max gap {pd(t['idle']['max_gap_h'], 'h')}   idle>8h {pd(t['idle']['idle_h'], 'h')}",
        "spend  " + ("(no spend-report file)" if not t["spend"] else
                     f"${t['spend']['usd_workers']:g} workers  per closed {pd(t['spend']['usd_per_closed'])}"),
    ]
    for grp in out["groups"]:
        lines.append(f"  {grp['key']}: closed {grp['closed']}  cycle {pd(grp['cycle_h'], 'h')}  "
                     f"review {tl(grp['review']['estimated'])}{g(grp['review']['fail_rate'])} fail of {grp['review']['verdicts']}")
    return "\n".join(lines)


def cmd_stats(args):
    if bool(args.project) == bool(args.all):
        usage_error("stats takes exactly one of <project> or --all")
    until = datetime.now(timezone.utc).replace(microsecond=0)
    m = re.fullmatch(r"(\d+)d", args.since)
    if m:
        since = until - timedelta(days=int(m[1]))
    else:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            usage_error("--since takes Nd (days back) or YYYY-MM-DD")
    db = open_ro(DB)
    project = resolve(db, args.project) if args.project else None
    d = stats_collect(db, project, since, until)
    d["calendar"] = calendar(since, until)
    p = {"p": project}
    counts = {"entries": {r[0]: r[1] for r in db.execute(
                  "SELECT status, COUNT(*) FROM entries WHERE (:p IS NULL OR project = :p) GROUP BY status", p)},
              "questions": {r[0]: r[1] for r in db.execute(
                  "SELECT status, COUNT(*) FROM questions WHERE (:p IS NULL OR project = :p) GROUP BY status", p)}}
    now_counts = {**counts["entries"], "OQ": counts["questions"].get("OPEN", 0)}
    for k in ("IN PROGRESS", "PARKED"):
        now_counts.setdefault(k, 0)
    spend_path = Path(args.spend) if args.spend else (
        Path(os.environ["KIT_STATE_DIR"]) / "spend" / "entries.json" if os.environ.get("KIT_STATE_DIR") else None)
    try:
        spend = (json.loads(spend_path.read_text()), spend_path, since) if spend_path else None
    except (OSError, ValueError):
        spend = None  # no spend-report file yet (or a half-written one): spend stays null
    days = (until - since).total_seconds() / 86400
    totals = {"counts": counts, **stats_block(d, lambda k: True, days, now_counts, spend)}
    groups = []
    if args.by:
        keys = {c["k"][args.by] for c in d["closes"]} | {v["k"][args.by] for v in d["verdicts"]}
        keys |= {x["k"][args.by] for x in d["parked"]}
        for key in sorted(keys, key=str):
            gc = {}
            if args.by == "project":
                gc = {r[0]: r[1] for r in db.execute("SELECT status, COUNT(*) FROM entries WHERE project=? GROUP BY status", (key,))}
                gc["OQ"] = db.execute("SELECT COUNT(*) FROM questions WHERE project=? AND status='OPEN'", (key,)).fetchone()[0]
            groups.append({"key": key, **stats_block(d, lambda k, key=key: k.get(args.by) == key, days, gc, spend)})
    cl = {}
    for at, _, _ in landings(d["closes"], "commits"):
        cl[at[:10]] = cl.get(at[:10], 0) + 1
    land = {}
    for at, _, est in landings(d["closes"]):
        land.setdefault(at[:10], [0, False])
        land[at[:10]][0] += 1
        land[at[:10]][1] |= est
    daily, last = [], {"IN PROGRESS": None, "PARKED": None}
    for day in d["calendar"]:
        last = d["wip_days"].get(day, last)
        cs = [c for c in d["closes"] if c["at"][:10] == day]
        vs = [v for v in d["verdicts"] if v["at"][:10] == day]
        daily.append({"day": day, "closed": len(cs), "closed_sweep": sum(c["sweep"] for c in cs),
                      "wip": last["IN PROGRESS"], "parked": last["PARKED"], "prs": land.get(day, [0])[0], "commits": cl.get(day, 0),
                      "asked": sum(1 for q in d["questions"] if q["at"][:10] == day),
                      "verdicts": len(vs), "fail": sum(v["verdict"] == "fail" for v in vs),
                      "estimated": any(v["estimated"] for v in vs) or land.get(day, [0, False])[1]})
    label = args.since if m else f"since {args.since}"
    out = {"schema": STATS_SCHEMA, "generated_at": until.isoformat(), "database": str(DB),
           "scope": {"projects": project or "all", "since": since.isoformat(timespec="seconds"),
                     "until": until.isoformat(), "days": round(days, 2), "by": args.by},
           "totals": totals, "groups": groups, "daily": daily, "hud": stats_hud(label, totals)}
    if args.hud:
        print(out["hud"])
    elif args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(stats_text(out))


def cmd_projects(args):
    db = connect()
    emit([dict(r) | {"entries": db.execute("SELECT COUNT(*) FROM entries WHERE project=?", (r["name"],)).fetchone()[0]}
          for r in db.execute("SELECT name, alias_of, paths FROM projects ORDER BY name")])


def cmd_backup(args):
    target = Path(args.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = connect()
    with sqlite3.connect(target) as dest:
        source.backup(dest)
    emit({"backup": str(target), "bytes": target.stat().st_size})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    q = sub.add_parser("import-md", help="one legacy todos.md into a project")
    q.add_argument("project")
    q.add_argument("file")
    q.add_argument("--paths-file")
    q.add_argument("--alias-of")
    q.add_argument("--actor")
    q.set_defaults(func=cmd_import_md)

    q = sub.add_parser("export-md", help="regenerate the legacy markdown")
    q.add_argument("project")
    q.add_argument("--out")
    q.set_defaults(func=cmd_export_md)

    q = sub.add_parser("list")
    q.add_argument("project")
    q.add_argument("--status", choices=STATUSES)
    q.add_argument("--all", action="store_true", help="include DONE and DROPPED")
    q.set_defaults(func=cmd_list)

    q = sub.add_parser("plan", help="every entry that is not closed, one line each, with IDLE / UNBLOCKED flags")
    q.add_argument("project")
    q.add_argument("--idle-days", type=int, default=2)
    q.add_argument("--removed-days", type=int, default=14)
    q.set_defaults(func=cmd_plan)

    q = sub.add_parser("get")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("--events", action="store_true")
    q.set_defaults(func=cmd_get)

    q = sub.add_parser("create")
    q.add_argument("project")
    q.add_argument("--title", required=True)
    q.add_argument("--parallel", required=True, help="FORKABLE — why / BLOCKED behind #N — what they share")
    q.add_argument("--note")
    q.add_argument("--after", help="entry id: place the new entry right after it in the work order (a phase after its parent)")
    q.add_argument("--actor")
    q.set_defaults(func=cmd_create)

    q = sub.add_parser("set-status")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("--status", required=True, choices=STATUSES)
    q.add_argument("--note", required=True)
    q.add_argument("--fork", action="store_true")
    q.add_argument("--worker", help="model/effort of the worker writing this, e.g. opus/medium")
    q.add_argument("--pr", action="append", default=[], help="PR URL this status lands (repeatable; URLs in --note are read too)")
    q.add_argument("--operator", help="the operator's own words; required for DROPPED")
    q.add_argument("--expect-version", required=True, type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_set_status)

    q = sub.add_parser("append")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("text")
    q.add_argument("--kind", default="round", choices=("round", "dispatch", "note", "review"))
    q.add_argument("--verdict", type=str.lower, choices=("pass", "fail"), help="required with --kind review")
    q.add_argument("--tier", help="reviewed worker's <model>/<effort> or main (default: the last dispatch)")
    q.add_argument("--expect-version", required=True, type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_append)

    q = sub.add_parser("set-parallel")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("text")
    q.add_argument("--expect-version", required=True, type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_set_parallel)

    q = sub.add_parser("move", help="change an entry's place in the work order, with the reason")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("--before", help="entry id: place it right before that entry")
    q.add_argument("--after", help="entry id: place it right after that entry")
    q.add_argument("--top", action="store_true", help="first of the project's entries")
    q.add_argument("--bottom", action="store_true", help="last of the project's entries")
    q.add_argument("--note", required=True, help="why the priority changes")
    q.add_argument("--expect-version", required=True, type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_move)

    q = sub.add_parser("import-questions", help="a questions-for-operator file into the questions table")
    q.add_argument("project")
    q.add_argument("file")
    q.add_argument("--actor")
    q.set_defaults(func=cmd_import_questions)

    q = sub.add_parser("ask")
    q.add_argument("project")
    q.add_argument("qid")
    q.add_argument("--title", help="required when the question does not exist yet")
    q.add_argument("--body", help="appended to an existing question's body by default")
    q.add_argument("--replace", action="store_true", help="replace body instead of appending (existing question only)")
    q.add_argument("--status", default=None, choices=("OPEN", "ANSWERED", "DROPPED", "NOTE"))
    q.add_argument("--option", action="append", default=[],
                   help="a choice (repeatable, at most 8): ends the body with an 'Options:' block")
    q.add_argument("--recommend", help="the recommended choice: text, or the number of an --option")
    q.add_argument("--expect-version", type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_ask)

    q = sub.add_parser("rule")
    q.add_argument("project")
    q.add_argument("qid")
    q.add_argument("text")
    q.add_argument("--keep-status", "--no-answer", dest="keep_status", action="store_true",
                    help="append the ruling without marking the question ANSWERED")
    q.add_argument("--expect-version", type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_rule)

    q = sub.add_parser("questions")
    q.add_argument("project")
    q.add_argument("--status", choices=("OPEN", "ANSWERED", "DROPPED", "NOTE"))
    q.set_defaults(func=cmd_questions)

    q = sub.add_parser("stats", help="read-only velocity metrics: lead/cycle, iterations, review fail rate, parks, questions, PRs")
    q.add_argument("project", nargs="?")
    q.add_argument("--all", action="store_true", help="every project (exactly one of <project> or --all)")
    q.add_argument("--since", default="7d", help="Nd (days back from now, UTC) or YYYY-MM-DD (00:00 UTC); default 7d")
    q.add_argument("--by", choices=("project", "tier", "actor"), help="add a groups array, one metric block per key")
    q.add_argument("--json", action="store_true", help="schema 1 JSON")
    q.add_argument("--hud", action="store_true", help="print only the one-line HUD summary")
    q.add_argument("--spend", help="spend-report entries file (default $KIT_STATE_DIR/spend/entries.json when present)")
    q.set_defaults(func=cmd_stats)

    sub.add_parser("projects").set_defaults(func=cmd_projects)

    q = sub.add_parser("backup")
    q.add_argument("file")
    q.set_defaults(func=cmd_backup)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
