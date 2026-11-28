#!/usr/bin/env node
// The Prosper Agent Kit's status line (the `hud` piece). Claude Code runs it through the kit runner, so KIT_STATE_DIR
// names the kit's state folder: the ledger database todo.py writes (LEDGER_DB still wins) and this HUD's own files.
//
// With the oh-my-claudecode (OMC) HUD installed, its generated wrapper
// <claude config>/hud/omc-hud.mjs draws the main line and this file post-processes it: OMC owns that file and
// rewrites it on `/oh-my-claudecode:hud setup`, so the patches live here and simply import the wrapper (which runs
// main() on import). Without OMC this file reads Claude Code's stdin itself and prints a short main line (model,
// effort, context) above the same task and PR panel.
//
// The HUD has no config knobs for any of this, hence post-processing its
// output. The styling target is one consistent scheme:
//
//   label:      plain      (`5h:` and `ctx:` already were; wk/sk/org/model
//                           were dim or cyan)
//   number      green      (percentages keep the HUD's threshold colours)
//   text        cyan       (model name, org name)
//   (extra)     dim        (effort, reset times, token count)
import { spawn } from 'node:child_process';
import { mkdirSync, readdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { isatty } from 'node:tty';
import { pathToFileURL } from 'node:url';
import { getClaudeConfigDir, kitStateDir } from './lib/config-dir.mjs';
import { ledgerEntries } from './ledger.mjs';
import { statsLine } from './stats.mjs';
import { prHead, prLines, prMeta } from './prs.mjs';
import { readStdinCache, useStdin } from './stdin-cache.mjs';
import { omcAnchor } from './worktree-anchor.mjs';

const DIM = '\x1b[2m';
const CYAN = '\x1b[36m';
const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const RESET = '\x1b[0m';
// Bold black on yellow: a filled badge, the closest a terminal line gets to an
// outline. Marks a session running off the house defaults below.
const BADGE = '\x1b[1;30;43m';

// The model and effort every session is expected to run (the kit settings hud_default_model and
// hud_default_effort). Either one differing renders as a BADGE, so an off-default session is visible at a
// glance; an empty setting never badges.
const DEFAULT_MODEL = process.env.KIT_HUD_DEFAULT_MODEL ?? '';
const DEFAULT_EFFORT = process.env.KIT_HUD_DEFAULT_EFFORT ?? '';
const isDefault = (want, got) => !want || got === want;

const origWrite = process.stdout.write.bind(process.stdout);
let effortDone = false;
let ctxDone = false;
let tasksDone = false;

/* ---------- task list ----------
 * Claude Code's own task tree caps itself at five rows
 * (`Math.min(5, Math.max(3, rows - 14))`) even when expanded with ctrl+t, so
 * with a long list most of it is only ever "+18 pending". The full list is on
 * disk, one JSON per task, so render it here instead and leave the native
 * panel toggled off.
 *
 * Completed tasks are counted, not listed — they are the bulk of a long list
 * and none of the work left to do.
 */
// Three rows: the two lanes' live items plus whatever is next. Beyond that the
// panel stops being a glance and starts being a document, so the tail collapses
// into a counted breakdown instead (see `hidden` below) — which answers "how
// much is queued, how much is stuck" without spending a row per item.
const TASK_LIMIT = Number(process.env.OMC_HUD_TASKS ?? 3);

// Per-item rows are off by default: the panel collapses to one counts
// line. Nothing below is removed — the row builder, the glyph ladder and the
// hidden-tail tally are all still here and simply skipped, so
// `OMC_HUD_TASK_ROWS=1` brings the list back exactly as it was. The PR panel is
// unaffected; it keeps its own header and its open rows.
const TASK_ROWS = (process.env.OMC_HUD_TASK_ROWS ?? '0') !== '0';

// The counts line is off too: `tasks 102/109, 1 in progress,
// 6 in queue` is bookkeeping read out of the ledger, not off a
// status bar. `OMC_HUD_TASK_COUNTS=1` brings it back. With both flags at 0 the
// task panel renders nothing at all.
const TASK_COUNTS = (process.env.OMC_HUD_TASK_COUNTS ?? '0') !== '0';

// The PR summary row is off: the merged total rides the main line as
// `merged:N`, and the panel is then nothing but the clickable open PRs, which
// say "open" by being listed. `OMC_HUD_PR_HEAD=1` restores the
// `PR n open, m merged` row (and with it the open count).
const PR_HEAD = (process.env.OMC_HUD_PR_HEAD ?? '0') !== '0';

// And the merged total itself is off the rendered line now. dch does not read
// it from there — it parses the `{"prs":{"merged":…}}` meta that pushMeta
// sends with `dch --meta`, which keeps going out either way.
// `OMC_HUD_PR_MERGED=1` puts it back on the line.
const PR_MERGED = (process.env.OMC_HUD_PR_MERGED ?? '0') !== '0';

// Kit setting hud_pr_lines (env KIT_HUD_PR_LINES): "0"/"off"/"false"/"no" hides every PR row, the head and the
// `merged:N` tail. pushMeta still sends meta.prs to dch, and prLines still runs so the state refresh goes on.
const PR_SHOW = !['0', 'off', 'false', 'no'].includes((process.env.KIT_HUD_PR_LINES ?? '1').trim().toLowerCase());

// Only used to keep task subjects on one row. Claude Code pipes the statusline,
// so stdout is not a TTY and carries no columns; COLUMNS is inherited from the
// launching shell and therefore misses a mid-session resize.
const WIDTH = process.stdout.columns || Number(process.env.COLUMNS) || 100;

// Env var, not the cache: it is this process's own session, immune to another
// session overwriting the shared cache file mid-render.
const sessionId = () => process.env.CLAUDE_CODE_SESSION_ID ?? readStdinCache()?.session_id;

// Loads and classifies the session's tasks for the rendered panel.
function taskModel(sid) {
  let tasks = [];
  try {
    const dir = join(getClaudeConfigDir(), 'tasks', sid);
    tasks = readdirSync(dir)
      .filter((f) => f.endsWith('.json'))
      .map((f) => { try { return JSON.parse(readFileSync(join(dir, f), 'utf8')); } catch { return null; } })
      .filter(Boolean);
  } catch { /* no task store for this session — the ledger may still have work */ }

  // Merge in the kit ledger (todo.py, the kit rules' Ledger section). Both surfaces carry
  // the same ids by rule, so an id already in the live task store is skipped —
  // the session store is the newer of the two views. Sessions using only one of
  // them are the same code path with nothing to skip.
  // Live-store rows keep id order; ledger rows are numbered by their position in
  // the file below, so the two orderings never mix scales.
  tasks.sort((a, b) => (Number(a.id) || 0) - (Number(b.id) || 0));
  tasks.forEach((t, i) => { t.order = i; });
  const ids = new Set(tasks.map((t) => String(t.id)));
  // Where the session STARTED, never where the shell currently sits: a `cd` in
  // any Bash call moves process.cwd(), and the HUD would quietly swap in another
  // project's ledger. CLAUDE_PROJECT_DIR is this process's own and never moves;
  // `workspace.project_dir` says the same from stdin for sessions old enough to
  // predate the env var, and cwd is only the last resort.
  const cache = readStdinCache();
  const projectDir = process.env.CLAUDE_PROJECT_DIR
    ?? cache?.workspace?.project_dir
    ?? process.cwd();

  // Second differentiator, and the preferred one: a session named after its work
  // keeps that name across branches and worktrees. `session_name` is Claude Code's
  // own — the deliberate name when there is one, an auto-title otherwise, which
  // ledgerFile() ignores because no directory answers to it. DCH_SESSION is the
  // terminal session's name, for sessions Claude Code never named.
  const sessionName = cache?.session_name ?? process.env.DCH_SESSION ?? null;
  const STATUS = { OPEN: 'pending', 'IN PROGRESS': 'in_progress', DONE: 'completed', PARKED: 'parked' };
  const entries = ledgerEntries(projectDir, sessionName);
  for (const e of entries) {
    if (ids.has(e.id)) continue;
    tasks.push({
      id: e.id, subject: e.title, status: STATUS[e.status] ?? 'pending',
      ledger: true, lastRound: e.lastRound,
      blockedBy: e.blockedBy, forkable: e.forkable, lane: e.lane, worker: e.worker, order: tasks.length,
    });
  }

  // Nothing marked in progress means either genuinely nothing is being worked
  // on, or — far more often — the session picked an item up without writing the
  // status line. Fall back to the entry with the newest `**Round N, date**`
  // paragraph, which is the last one someone actually wrote into, and pin it to
  // the top so the live item is never sitting behind a `+N more`.
  // Ties on the date go to the entry latest in the file, since rounds append.
  // ponytail: date granularity only — a day with rounds in several entries pins
  // the last-written one, which is the right guess but only a guess. Marking the
  // status makes it exact, and an explicit `in_progress` always wins over this.
  // Per lane, not globally: a worker marking its own item must not suppress the
  // main lane's inference, and vice versa — otherwise one lane writing a status
  // hides the other lane's live work under `+N more`.
  // ponytail: only the main lane is inferred. A worker exists because the
  // supervisor dispatched it, so it writes `(fork)` on its status line; rounds
  // carry no lane, so there is nothing to infer a worker's item from.
  // Under the supervisor model (CLAUDE.md Todos) the main lane dispatches and
  // reviews but never implements, so once any worker is live an absent main
  // status is the EXPECTED state, not a forgotten line — and the newest round
  // is usually a worker's, so inferring would pin a worker's entry as ▷ main.
  // Infer only while no worker is live (single-lane sessions, old ledgers).
  const lane = (t) => t.lane ?? 'main';
  const liveWorkers = tasks.filter((t) => t.status === 'in_progress' && lane(t) === 'fork').length;
  if (!liveWorkers && !tasks.some((t) => t.status === 'in_progress' && lane(t) === 'main')) {
    let active = null;
    for (const t of tasks) {
      // Parked is a deliberate not-now, so recent activity on one is the record
      // of parking it, not of working it.
      if (t.status === 'completed' || t.status === 'parked' || !t.lastRound || lane(t) === 'fork') continue;
      if (!active || t.lastRound >= active.lastRound) active = t;
    }
    if (active) active.active = true;
  }

  const open = new Set(tasks.filter((t) => t.status !== 'completed').map((t) => t.id));
  const blocked = (t) => (t.blockedBy ?? []).some((id) => open.has(id));
  // "Order is the work order" (CLAUDE.md): within a section, top is next, and a
  // block moved to the end of the ledger is the user saying "later". Sorting
  // by id would throw that away — a deprioritised entry would keep its old place. Ledger rows
  // therefore tie-break on their position in the file; live-store rows have no
  // file to be positioned in and keep the id order.
  const byOrder = (a, b) => (a.order ?? 0) - (b.order ?? 0);

  // One classifier for both the row mark and the hidden tally: two copies of
  // this ladder would drift, and a tally disagreeing with the glyphs above it is
  // worse than no tally.
  const kind = (t) => (t.active ? 'inferred'
    : t.status === 'in_progress' ? (lane(t) === 'fork' ? 'fork' : 'live')
    : t.status === 'parked' ? 'parked'
    : blocked(t) ? 'blocked'
    : t.forkable ? 'forkable'
    : 'queued');

  const rank = { in_progress: 0, pending: 1 };
  const todo = tasks
    .filter((t) => t.status !== 'completed')
    .sort((a, b) => (b.active === true) - (a.active === true)
      || (rank[a.status] ?? 2) - (rank[b.status] ?? 2)
      // Both lanes' live items sit at the top, main first, so one panel shows
      // what each is on.
      || (lane(a) === 'fork') - (lane(b) === 'fork')
      || blocked(a) - blocked(b)
      || byOrder(a, b));
  return { tasks, todo, kind, lane, liveWorkers, project: entries.project };
}

// The counts line's numbers. `in progress` is both lanes plus an inferred item —
// every row that would have rendered with a lit mark; `queued` is everything else
// still open, blocked and parked included, since they are work not done.
function taskCounts({ tasks, todo, kind }) {
  const live = todo.filter((t) => ['live', 'inferred', 'fork'].includes(kind(t))).length;
  return { done: tasks.length - todo.length, total: tasks.length, in_progress: live, queued: todo.length - live };
}

function taskLines(sid, m) {
  // TASK_LIMIT <= 0 hides the panel.
  if (TASK_LIMIT <= 0 || !m.todo.length) return [];
  const { tasks, todo, kind, lane, liveWorkers } = m;

  // Hollow `▷` is inferred, not a real in_progress. Lit `∥` is a live worker's
  // item — several at once, one per dispatched worker. Dim `∥` is startable but
  // unclaimed: the supervisor owes it a worker, so a lingering dim `∥` is a
  // dispatch bug. `·` is unblocked but not FORKABLE — serial queue, neither
  // stalled nor fan-out.
  const GLYPH = {
    live: `${CYAN}▶${RESET}`, inferred: `${CYAN}▷${RESET}`, fork: `${CYAN}∥${RESET}`,
    forkable: `${DIM}∥${RESET}`, blocked: `${DIM}⊘${RESET}`, parked: `${DIM}⏸${RESET}`,
    queued: `${DIM}·${RESET}`,
  };
  // Tally order, most urgent first — not object order, which JS would give us.
  const KINDS = ['live', 'inferred', 'fork', 'forkable', 'blocked', 'parked', 'queued'];

  // Leading spaces get stripped before the statusline is painted, so the inset
  // has to be drawn with a glyph.
  const indent = `${DIM}│${RESET} `;
  const { done, in_progress: live, queued } = taskCounts(m);

  // Counts-only mode (numbers from taskCounts).
  if (!TASK_ROWS) {
    if (!TASK_COUNTS) return [];
    // The PR summary rides along rather than spending a second line on two
    // numbers; its open rows still render under it.
    const pr = PR_HEAD && PR_SHOW ? prHead(sid) : null;
    return [`${indent}${DIM}tasks ${GREEN}${done}${RESET}${DIM}/${tasks.length}, `
      + `${CYAN}${live}${RESET}${DIM} in progress, ${queued} in queue${RESET}`
      + (pr ? `${DIM}, ${pr}` : '')];
  }

  const width = WIDTH - 8; // indent + mark + id + spaces
  const lines = todo.slice(0, TASK_LIMIT).map((t) => {
    const mark = GLYPH[kind(t)];
    const text = t.subject.length > width ? `${t.subject.slice(0, width - 1)}…` : t.subject;
    const live = t.status === 'in_progress' || t.active;
    // A live worker's model·effort, parsed from the dispatch status line —
    // the statusline stdin payload only ever carries the MAIN session's model,
    // so this is the only surface that can show what tier a worker runs on.
    const tier = live && lane(t) === 'fork' && t.worker ? ` ${DIM}${t.worker}${RESET}` : '';
    return `${indent}${mark} ${DIM}${t.id}${RESET} ${live ? text : `${DIM}${text}${RESET}`}${tier}`;
  });

  const hidden = todo.length - lines.length;
  // `+9 more` said nothing about what those nine were, so a queue with six
  // blocked entries and one startable one looked the same as seven ready ones.
  // Same glyphs as the rows above, so the breakdown needs no legend of its own.
  if (hidden > 0) {
    const n = {};
    for (const t of todo.slice(TASK_LIMIT)) n[kind(t)] = (n[kind(t)] ?? 0) + 1;
    const parts = KINDS.filter((k) => n[k]).map((k) => `${GLYPH[k]}${DIM}${n[k]}${RESET}`);
    lines.push(`${indent}${DIM}… +${hidden}${RESET} ${parts.join(' ')}`);
  }

  // Progress header above the list. The `n done` tail it replaces said the same
  // thing without the denominator, so the total had to be counted by eye.
  // `∥N` is the live worker count — the supervisor's one-glance answer to "how
  // many are out right now"; omitted at zero so single-lane sessions look as
  // they always did.
  const workers = liveWorkers ? ` ${CYAN}∥${liveWorkers}${RESET}` : '';
  lines.unshift(`${indent}${DIM}tasks ${GREEN}${done}${RESET}${DIM}/${tasks.length}${RESET}${workers}`);
  return lines;
}

/* ---------- dch session meta ----------
 * Pushes the open PRs and merged total to dch, which shows them for this
 * session (`dch --meta <session> '<json>'`, standard key `prs`; dch stamps the time and clears it when the program exits). Pushed at
 * once when the content or DCH_SESSION changes, and otherwise re-pushed every
 * 30 s even when unchanged: the push is fire-and-forget, so a dch that rejected
 * or missed it, or one that cleared the meta on a respawn (`dch --restart`
 * resumes the same sid with the same content), is repaired within 30 s. dch
 * treats an identical push as a no-op that keeps its stamp. The last push is
 * `<kit state>/hud/meta-<sid>.sent` ("<DCH_SESSION>\n<json>", mtime = push time),
 * since every render is a fresh process. The render never waits on dch, and a
 * dch without --meta just fails out of sight. Never throws, never prints —
 * every session's statusline runs through here.
 */
const META_MAX = 16_000; // dch rejects > 16384 bytes
const META_REPUSH_MS = 30_000;
let metaDone = false;
function pushMeta(sid) {
  if (metaDone) return;
  metaDone = true;
  let tmp;
  try {
    const dch = process.env.DCH_SESSION;
    if (!dch || typeof sid !== 'string' || !/^[0-9A-Za-z-]{1,64}$/.test(sid)) return;
    const body = { prs: prMeta(sid) };
    let json = JSON.stringify(body);
    while (Buffer.byteLength(json) > META_MAX && body.prs.open.length) {
      body.prs.open.pop();
      json = JSON.stringify(body);
    }
    // The dch session is part of the key: the same claude session resumed under
    // another dch session has nothing there yet.
    const sent = `${dch}\n${json}`;
    const file = join(kitStateDir(), 'hud', `meta-${sid}.sent`);
    try {
      const age = Date.now() - statSync(file).mtimeMs;
      if (age >= 0 && age < META_REPUSH_MS && readFileSync(file, 'utf8') === sent) return;
    } catch { /* never sent */ }
    const child = spawn('dch', ['--meta', dch, json], { detached: true, stdio: 'ignore' });
    child.on('error', () => {}); // no dch on PATH: ENOENT arrives async, must not crash the render
    child.unref();
    mkdirSync(dirname(file), { recursive: true });
    tmp = `${file}.${process.pid}.tmp`;
    writeFileSync(tmp, sent, { mode: 0o600 });
    renameSync(tmp, file);
    tmp = null;
  } catch {
    try { if (tmp) unlinkSync(tmp); } catch { /* nothing to clean */ }
  }
}

// One render's panel: load once, push the dch meta, return the lines.
function panel() {
  const sid = sessionId();
  const m = taskModel(sid);
  pushMeta(sid);
  const stats = statsLine(m.project);
  const pr = prLines(sid, WIDTH, { head: PR_HEAD }); // runs even when hidden: it triggers the state refresh
  return [...taskLines(sid, m), ...(stats ? [`${DIM}│${RESET} ${DIM}${stats}${RESET}`] : []), ...(PR_SHOW ? pr : [])];
}

process.stdout.write = (chunk, ...rest) => {
  let s = typeof chunk === 'string' ? chunk : chunk.toString();

  // Hide `[OMC#version]` unless it carries an update notice. `omcLabel: false`
  // would kill the update notification too.
  if (s.includes('[OMC') && !s.includes('omc update')) {
    s = s.replace(/(?:\x1b\[[0-9;]*m)*\[OMC[^\]]*\](?:\x1b\[[0-9;]*m)*\s*(?:\x1b\[[0-9;]*m)*\|\s*/g, '');
  }

  // The main line, recognised before the label is rewritten away below. The
  // task panel anchors on this further down.
  const isMain = s.includes('Model:');

  if (isMain) {
    // Drop the space the HUD hardcodes after the label. The label itself goes
    // further down; this keeps the value from starting with blanks.
    s = s.replace(/(Model):\s+/, '$1:');

    // Reasoning effort, which Claude Code passes as stdin `effort.level` and
    // the HUD ignores. Read the cache lazily: the HUD has already refreshed it
    // for this render by the time it writes output, so this is current. It
    // renders as ` · high`: with the label gone the line is a name and a
    // qualifier, and a middot separates those with less ink than brackets.
    if (!effortDone) {
      // Cache first: it carries the live stdin value, so it follows a mid-session
      // /effort change. CLAUDE_EFFORT is the fallback — fixed at process spawn,
      // but per-process and therefore never another session's, and it renders
      // even when a concurrent session owns the shared cache file this instant.
      const level = readStdinCache()?.effort?.level ?? process.env.CLAUDE_EFFORT;
      if (level) {
        s = s.replace(
          /(Model:[^\x1b|\n]+?)(?=\x1b|\s*\||\n|$)/,
          isDefault(DEFAULT_EFFORT, level)
            ? `$1${RESET}${DIM} · ${level}${RESET}`
            : `$1${RESET}${DIM} · ${RESET}${BADGE} ${level} ${RESET}`,
        );
        effortDone = true;
      }
    }

    // Drop the `Model:` label outright. It labelled a value among several on a
    // crowded line; the model is now the only thing on it, so the name alone is
    // unambiguous. Keep it cyan, as the HUD paints its values.
    s = s.replace(/\x1b\[36mModel:([^\x1b]*)/, (_, name) => (isDefault(DEFAULT_MODEL, name.trim())
      ? `${CYAN}${name}${RESET}`
      : `${BADGE} ${name.trim()} ${RESET}`));
  }

  // Absolute context tokens after the percent. `total_input_tokens` is the
  // field the percent is derived from (÷ context_window_size), so the two
  // always agree.
  if (!ctxDone && s.includes('ctx:')) {
    const tokens = readStdinCache()?.context_window?.total_input_tokens;
    if (tokens > 0) {
      s = s.replace(
        /(ctx:(?:\x1b\[[0-9;]*m)*\d+%)/,
        `$1${RESET}${DIM}(${(tokens / 1000).toFixed(1)}k)${RESET}`,
      );
      ctxDone = true;
    }
  }

  // Drop the `fable:` weekly bucket. It arrives as a scopedWeeklyBucket from the
  // usage API with no HUD switch to turn it off, and it is a limit this account
  // never runs into — the two that matter are 5h and wk. Buckets are space
  // separated and carry no internal space, so the whole token goes with its
  // leading space.
  s = s.replace(/\s?(?:\x1b\[[0-9;]*m)*fable:\S*/g, '');

  // Undim labels so wk/sk/org match 5h/ctx. The `| ` prefix on a custom bucket
  // is a separator, so it stays dim while its label does not. Neither pattern
  // can touch the ` | ` separators themselves — those have no colon.
  s = s.replace(/\x1b\[2m\| ([a-z][\w]*):\x1b\[0m/g, `${DIM}| ${RESET}$1:`);
  s = s.replace(/\x1b\[2m([a-z][\w]*):\x1b\[0m/g, '$1:');

  // Custom-bucket values arrive unpainted (the HUD only colours percent-typed
  // buckets). Number green, text cyan. Anchored on the preceding reset rather
  // than \b: the label follows the `m` of an escape, and `m`/`s` are both word
  // characters, so there is no word boundary there to match.
  // Payload MB against the 32MB Anthropic request-body ceiling. Same
  // thresholds OMC's own payloadWarning uses (22/26MB in payload-estimate.js),
  // so the colour flips at the point the HUD would start nagging to compact.
  s = s.replace(/(\x1b\[0m|\s|^)(pl:)(\d+(?:\.\d+)?)MB/, (_m, pre, label, mb) => {
    const c = mb >= 26 ? RED : mb >= 22 ? YELLOW : GREEN;
    return `${pre}${label}${c}${mb}MB${RESET}`;
  });

  s = s.replace(/(\x1b\[0m|\s|^)(sk:)([^\x1b\s|]+)/, `$1$2${GREEN}$3${RESET}`);
  s = s.replace(/(\x1b\[0m|\s|^)(org:)([^\x1b\n]*[^\x1b\s\n])/, `$1$2${CYAN}$3${RESET}`);

  // Git info now rides at the end of the main line (layout.line1 is empty), so
  // the seam between session info and repo info gets a heavier separator than
  // the `|` that divides peers. Only visible when the line fits: past the
  // terminal width the HUD wraps at this very separator and consumes it.
  s = s.replace(
    /\x1b\[2m \| \x1b\[0m(?=(?:\x1b\[[0-9;]*m)*(?:branch|repo|profile):)/,
    `${DIM} » ${RESET}`,
  );

  // The main line is the anchor: it is always present and always last, so the
  // task list appends below the whole HUD exactly once.
  // Anchored on the model field, not on `ctx:`: the context bar is a layout
  // element that can be switched off, the model is the one field the main line
  // always has. `isMain` is read before the `Model:` label is rewritten away,
  // so there is no label left in `s` to match on by the time we get here.
  if (!tasksDone && isMain) {
    tasksDone = true;
    // Merged PRs are a running total, not an item, so they belong on the main
    // line next to the other counters rather than above the list of open ones.
    const { merged } = prMeta(sessionId());
    if (merged && PR_SHOW && PR_MERGED && !PR_HEAD) s = s.replace(/(\n?)$/, `${DIM} | ${RESET}merged:${GREEN}${merged}${RESET}$1`);
    const lines = panel();
    if (lines.length) {
      s = `${s.replace(/\n$/, '')}\n${lines.join('\n')}`;
      // Closing the native panel used to be driven from here too. It is now
      // purely event-driven, from the PostToolUse hook on task writes: the
      // statusline renders on a cadence of its own that has nothing to do with
      // when the panel opens, and every render spent a `dch --read` on a mirror
      // that lags the real screen by 1-2s anyway.
    }
  }

  return origWrite(s, ...rest);
};

try {
  const anchor = omcAnchor(process.cwd());
  if (anchor) process.chdir(anchor);
} catch {
  // The cwd was removed under this render: OMC must not recreate it.
  process.chdir(homedir());
}

// The main line without OMC, from Claude Code's stdin: `<model> · <effort> | ctx:N%`, each part only when the
// payload carries it. Badges as the OMC path does.
function plainHead() {
  const d = readStdinCache();
  const name = typeof d?.model?.display_name === 'string' ? d.model.display_name.trim() : '';
  const level = d?.effort?.level ?? process.env.CLAUDE_EFFORT;
  const pct = d?.context_window?.used_percentage;
  let s = name ? (isDefault(DEFAULT_MODEL, name) ? `${CYAN}${name}${RESET}` : `${BADGE} ${name} ${RESET}`) : '';
  if (typeof level === 'string' && level) {
    s += `${DIM}${s ? ' · ' : ''}${RESET}` + (isDefault(DEFAULT_EFFORT, level) ? `${DIM}${level}${RESET}` : `${BADGE} ${level} ${RESET}`);
  }
  if (typeof pct === 'number' && Number.isFinite(pct)) s += `${s ? `${DIM} | ${RESET}` : ''}ctx:${GREEN}${Math.round(pct)}%${RESET}`;
  return s;
}

// OMC's wrapper is OMC's file in Claude Code's folder; the kit never ships or writes it.
const omcWrapper = join(getClaudeConfigDir(), 'hud', 'omc-hud.mjs');
try {
  await import(pathToFileURL(omcWrapper).href);
} catch {
  // No OMC HUD (or a broken one): print the parts this file owns rather than
  // crashing — a short HUD beats a blank one. stdin is still unread when the
  // wrapper is absent; a TTY means a person ran this by hand, so it is not read.
  try { if (!isatty(0)) useStdin(JSON.parse(readFileSync(0, 'utf8'))); } catch { /* empty or not JSON */ }
  // No OMC main line here to carry `merged:N`, so the plain head takes it.
  const { merged } = prMeta(sessionId());
  let head = plainHead();
  if (merged && PR_SHOW && PR_MERGED && !PR_HEAD) head += `${head ? `${DIM} | ${RESET}` : ''}merged:${GREEN}${merged}${RESET}`;
  const lines = [head, ...panel()].filter(Boolean);
  if (lines.length) origWrite(`${lines.join('\n')}\n`);
}
