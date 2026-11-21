// The ledger the kit's todo.py writes: `ledger.sqlite3` in the kit's state folder, or LEDGER_DB.
//
// The ledger and Claude Code's own task store are two views of one queue: the
// session list is the working queue, the ledger is the record that outlives the
// session, and CLAUDE.md pins them together by requiring the SAME ids in both.
// That shared id is what lets the HUD merge them without showing anything twice.
//
// A session may use either or both: a fresh session has an empty task store but
// an existing ledger, a throwaway session has tasks and no ledger.
//
// Nothing is parsed here any more. `todo.py` derives status, lane, worker tier,
// forkable and blockers from the entry's prose when it is written, so the HUD
// reads columns. One parser, in one language, on the write path — the markdown
// regexes that used to live in this file are now todo.py's, unchanged.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { kitStateDir } from './lib/config-dir.mjs';

// The same rule as todo.py: LEDGER_DB wins, else the kit's state folder.
const DB = process.env.LEDGER_DB || join(kitStateDir(), 'ledger.sqlite3');

// node:sqlite is loaded here, not at the top: on a node without it (before 22.13) a static import would fail the
// whole status line, this way only the ledger rows go. require, not import(), keeps open() synchronous.
function open() {
  try {
    const { DatabaseSync } = createRequire(import.meta.url)('node:sqlite');
    return new DatabaseSync(DB, { readOnly: true });
  } catch {
    return null; // no ledger on this machine, or mid-write and unreadable
  }
}

// Two differentiators, session name first. A session named after its work carries
// that name across branches, forks and fresh worktrees, so naming a new session
// `billing-next` again picks the same ledger back up wherever it is started from.
// The project directory is the fallback for sessions that were never named.
//
// Only ever RESOLVES an existing project, never creates one from the name:
// Claude Code auto-titles an unnamed session from its conversation ("Hide version
// and remove progress bars") and that title drifts as the work does. An auto-title
// simply matches nothing, which is the right outcome.
//
// Worktrees mean cwd is rarely the bare project name (`app.billing`, not `billing`),
// so match the project name inside a path SEGMENT and take the most specific hit.
// Segment-scoped, not whole-path: a ledger named `tools` must not claim every path
// that merely passes through some `tools` parent on its way somewhere unrelated.
// Some worktrees carry nothing of the project name at all — `app.wt-fanout`
// is a billing worktree, and no rule over its path can know that. Such a project
// lists the paths it owns in its `paths` column, one per line, matched against the
// whole cwd. Checked before the name rule, since it is explicit.
export function ledgerProject(db, cwd = process.cwd(), name = null) {
  if (process.env.OMC_HUD_LEDGER_PROJECT) return process.env.OMC_HUD_LEDGER_PROJECT;
  const rows = db.prepare('SELECT name, alias_of, paths FROM projects').all();
  const deref = (p) => p.alias_of ?? p.name;
  if (name) {
    const byName = rows.find((p) => p.name === name);
    if (byName) return deref(byName);
  }
  const hay = cwd.toLowerCase();
  const segs = hay.split('/').filter(Boolean);
  let best = null;
  for (const p of rows) {
    const claims = (p.paths ?? '').split('\n')
      .map((l) => l.trim().toLowerCase())
      .filter((l) => l && !l.startsWith('#'));
    if (claims.some((l) => hay.includes(l))) return deref(p);
    const needle = p.name.toLowerCase();
    if (!segs.some((s) => s.includes(needle))) continue;
    if (!best || p.name.length > best.name.length) best = p;
  }
  return best ? deref(best) : null;
}

// DROPPED is the one status that leaves entirely: CLAUDE.md keeps those so a wrong
// id is closed rather than deleted, which is history, not work, and not a
// denominator to measure against.
export function ledgerEntries(cwd = process.cwd(), name = null) {
  const db = open();
  if (!db) return [];
  try {
    const project = ledgerProject(db, cwd, name);
    if (!project) return [];
    return db.prepare(`SELECT entry_id, title, status, last_round, forkable, blocked_by, lane, worker
                       FROM entries WHERE project = ? AND status != 'DROPPED' ORDER BY ord`)
      .all(project)
      .map((r) => ({
        id: r.entry_id,
        title: r.title,
        status: r.status,
        lastRound: r.last_round,
        forkable: !!r.forkable,
        blockedBy: r.blocked_by ? r.blocked_by.split(',') : [],
        lane: r.lane,
        worker: r.worker,
      }));
  } catch {
    return [];
  } finally {
    db.close();
  }
}
