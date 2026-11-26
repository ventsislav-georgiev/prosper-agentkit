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
from datetime import date, datetime, timezone
from pathlib import Path

def db_path(env=os.environ):
    if env.get("LEDGER_DB"):
        return Path(env["LEDGER_DB"])
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
    tag = " (fork)" if args.fork else ""
    tier = f" ({args.worker.replace('/', ', ')} effort)" if args.worker else ""
    said = f' Operator: "{args.operator.strip()}"' if args.operator else ""
    line = f"**Status:** {args.status}{tag} {date.today()} — {args.note}{said}{tier}\n"
    body = cur["body"].rstrip("\n") + "\n" + line
    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "status", body,
                         {"status": args.status, "lane": "fork" if args.fork else "main", "note": args.note})))


def cmd_append(args):
    who = actor(args)
    db = connect()
    name = resolve(db, args.project)
    cur = get_entry(db, name, args.id)
    text = args.text
    if args.kind == "round":
        n = max((int(m.group(1)) for m in ROUND.finditer(cur["body"])), default=0) + 1
        text = f"**Round {n}, {date.today()}** — {text}"
    elif args.kind == "dispatch":
        text = f"**Dispatch note, {date.today()}** — {text}"
    body = cur["body"].rstrip("\n") + "\n\n" + text + "\n"
    emit(row_out(rewrite(db, name, args.id, args.expect_version, who, "append:" + args.kind, body,
                         {"kind": args.kind, "text": args.text})))


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


def cmd_ask(args):
    who = actor(args)
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


def cmd_stats(args):
    db = connect()
    where, params = ("WHERE project=?", [args.project]) if args.project else ("", [])
    rows = db.execute(f"""SELECT project, status, COUNT(*) n FROM entries {where}
                          GROUP BY project, status ORDER BY project, status""", params)
    out = {}
    for r in rows:
        out.setdefault(r["project"], {})[r["status"]] = r["n"]
    q = db.execute("SELECT project, status, COUNT(*) n FROM questions GROUP BY project, status")
    emit({"entries": out, "questions": {f"{r['project']}/{r['status']}": r["n"] for r in q},
          "database": str(DB)})


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
    q.add_argument("--operator", help="the operator's own words; required for DROPPED")
    q.add_argument("--expect-version", required=True, type=int)
    q.add_argument("--actor")
    q.set_defaults(func=cmd_set_status)

    q = sub.add_parser("append")
    q.add_argument("project")
    q.add_argument("id")
    q.add_argument("text")
    q.add_argument("--kind", default="round", choices=("round", "dispatch", "note"))
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

    q = sub.add_parser("stats")
    q.add_argument("project", nargs="?")
    q.set_defaults(func=cmd_stats)

    sub.add_parser("projects").set_defaults(func=cmd_projects)

    q = sub.add_parser("backup")
    q.add_argument("file")
    q.set_defaults(func=cmd_backup)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
