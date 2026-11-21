#!/usr/bin/env python3
"""Transactional CLI for Claude Code's memory files — SQLite is the source of truth.

The harness loads `MEMORY.md` off disk and recalls `memory/<name>.md` bodies, so
the files must keep existing: they are GENERATED MIRRORS. Every write lands in
SQLite and re-exports the file it touched; `export` regenerates a whole directory.
The exact bytes of each file live in `raw`, so the first export after an import is
byte-identical and harness recall is unaffected. The database is todo.py's.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ inside the installed kit folder
import todo  # noqa: E402  same database, same connection rules

PROJECTS = Path.home() / ".claude" / "projects"
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
# Two link shapes live in this corpus: the wiki form CLAUDE.md documents and the
# markdown form MEMORY.md actually uses.
LINKS = re.compile(r"\[\[([^\]]+)\]\]|\]\(([\w.-]+)\.md\)")

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  project_slug TEXT NOT NULL,
  name TEXT NOT NULL,          -- file stem; `MEMORY` is the index the harness loads
  description TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  raw TEXT NOT NULL,           -- exact file bytes: what export writes back
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  PRIMARY KEY (project_slug, name)
);
CREATE TABLE IF NOT EXISTS memory_links (
  project_slug TEXT NOT NULL,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  PRIMARY KEY (project_slug, src, dst)
);
"""


def connect():
    db = todo.connect()
    db.executescript(SCHEMA)
    return db


def split_frontmatter(raw):
    m = FRONTMATTER.match(raw)
    return (m.group(1), raw[m.end():]) if m else ("", raw)


def field(front, key):
    m = re.search(rf"^\s*{key}:\s*(.*)$", front, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def relink(db, slug, name, body):
    db.execute("DELETE FROM memory_links WHERE project_slug=? AND src=?", (slug, name))
    for m in LINKS.finditer(body):
        db.execute("INSERT OR IGNORE INTO memory_links(project_slug,src,dst) VALUES(?,?,?)",
                   (slug, name, m.group(1) or m.group(2)))


def store(db, slug, name, raw, who):
    front, body = split_frontmatter(raw)
    db.execute("""INSERT INTO memories(project_slug,name,description,type,body,raw,updated_at,updated_by)
                  VALUES(?,?,?,?,?,?,?,?)
                  ON CONFLICT(project_slug,name) DO UPDATE SET
                    description=excluded.description, type=excluded.type, body=excluded.body,
                    raw=excluded.raw, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
               (slug, name, field(front, "description"), field(front, "type"), body, raw, todo.now(), who))
    relink(db, slug, name, body)


def slug_of(directory):
    d = Path(directory).resolve()
    return d.parent.name if d.name == "memory" else d.name


def memory_dir(slug):
    return PROJECTS / slug / "memory"


def cmd_import(args):
    who = todo.actor(args)
    d = Path(args.directory)
    slug = args.slug or slug_of(d)
    db = connect()
    db.execute("BEGIN IMMEDIATE")
    try:
        names = []
        for f in sorted(d.glob("*.md")):
            store(db, slug, f.stem, f.read_text(), who)
            names.append(f.stem)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    todo.emit({"slug": slug, "imported": len(names)})


def compose(front, name, description, type_, body):
    """Frontmatter the harness already accepts, keeping the keys it wrote itself."""
    origin = field(front, "originSessionId")
    modified = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return ("---\n"
            f"name: {name}\n"
            f'description: "{description}"\n'
            "metadata: \n"
            f"  node_type: {field(front, 'node_type') or 'memory'}\n"
            f"  type: {type_}\n"
            + (f"  originSessionId: {origin}\n" if origin else "")
            + f"  modified: {modified}\n"
            "---\n" + body)


def write_file(slug, name, raw):
    d = memory_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(raw)


def cmd_write(args):
    who = todo.actor(args)
    db = connect()
    body = Path(args.body_file).read_text() if args.body_file else (args.body if args.body is not None else sys.stdin.read())
    row = db.execute("SELECT * FROM memories WHERE project_slug=? AND name=?", (args.slug, args.name)).fetchone()
    front = split_frontmatter(row["raw"])[0] if row else ""
    if args.name == "MEMORY" or args.no_frontmatter:
        raw = body  # the index carries no frontmatter, and neither do a few hand-written notes
    else:
        raw = compose(front, args.name,
                      args.description if args.description is not None else (row["description"] if row else ""),
                      args.type or (row["type"] if row else "project"), body)
    db.execute("BEGIN IMMEDIATE")
    try:
        store(db, args.slug, args.name, raw, who)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    write_file(args.slug, args.name, raw)  # the mirror is regenerated on every write
    todo.emit({"slug": args.slug, "name": args.name, "bytes": len(raw), "file": str(memory_dir(args.slug) / f"{args.name}.md")})


def cmd_get(args):
    db = connect()
    row = db.execute("SELECT * FROM memories WHERE project_slug=? AND name=?", (args.slug, args.name)).fetchone()
    if not row:
        raise SystemExit(f"error: no memory {args.name!r} for {args.slug}")
    sys.stdout.write(row["raw"] if args.raw else row["body"])


def cmd_search(args):
    db = connect()
    sql = "SELECT project_slug, name, description, type FROM memories WHERE (name LIKE ? OR description LIKE ? OR body LIKE ?)"
    like = f"%{args.query}%"
    params = [like, like, like]
    if args.slug:
        sql += " AND project_slug=?"
        params.append(args.slug)
    todo.emit([dict(r) for r in db.execute(sql + " ORDER BY project_slug, name LIMIT ?", params + [args.limit])])


def cmd_delete(args):
    db = connect()
    n = db.execute("DELETE FROM memories WHERE project_slug=? AND name=?", (args.slug, args.name)).rowcount
    db.execute("DELETE FROM memory_links WHERE project_slug=? AND src=?", (args.slug, args.name))
    if not n:
        raise SystemExit(f"error: no memory {args.name!r} for {args.slug}")
    cmd_export(argparse.Namespace(directory=str(memory_dir(args.slug)), slug=args.slug, check=False))


def cmd_export(args):
    """Rewrite the directory from the database. A file with no row is ARCHIVED, never deleted."""
    db = connect()
    d = Path(args.directory) if args.directory else memory_dir(args.slug)
    slug = args.slug or slug_of(d)
    rows = db.execute("SELECT name, raw FROM memories WHERE project_slug=? ORDER BY name", (slug,)).fetchall()
    if not rows:
        raise SystemExit(f"error: no memories for slug {slug!r}")
    d.mkdir(parents=True, exist_ok=True)
    kept, changed = set(), []
    for r in rows:
        f = d / f"{r['name']}.md"
        kept.add(f.name)
        if not f.exists() or f.read_text() != r["raw"]:
            changed.append(f.name)
            if not args.check:
                f.write_text(r["raw"])
    orphans = [f.name for f in d.glob("*.md") if f.name not in kept]
    if orphans and not args.check:
        archive = d.parent / "memory-archive"
        archive.mkdir(exist_ok=True)
        for name in orphans:
            (d / name).rename(archive / name)
    todo.emit({"slug": slug, "directory": str(d), "files": len(rows),
               "differed" if args.check else "rewritten": changed, "orphans": orphans})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("import")
    q.add_argument("directory")
    q.add_argument("--slug")
    q.add_argument("--actor")
    q.set_defaults(func=cmd_import)

    q = sub.add_parser("write")
    q.add_argument("slug")
    q.add_argument("name")
    q.add_argument("--body")
    q.add_argument("--body-file")
    q.add_argument("--description")
    q.add_argument("--type", choices=("user", "feedback", "project", "reference"))
    q.add_argument("--no-frontmatter", action="store_true")
    q.add_argument("--actor")
    q.set_defaults(func=cmd_write)

    q = sub.add_parser("get")
    q.add_argument("slug")
    q.add_argument("name")
    q.add_argument("--raw", action="store_true")
    q.set_defaults(func=cmd_get)

    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("--slug")
    q.add_argument("--limit", type=int, default=40)
    q.set_defaults(func=cmd_search)

    q = sub.add_parser("delete")
    q.add_argument("slug")
    q.add_argument("name")
    q.set_defaults(func=cmd_delete)

    q = sub.add_parser("export")
    q.add_argument("directory", nargs="?")
    q.add_argument("--slug")
    q.add_argument("--check", action="store_true", help="report differences, write nothing")
    q.set_defaults(func=cmd_export)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
