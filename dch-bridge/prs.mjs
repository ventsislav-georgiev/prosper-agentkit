#!/usr/bin/env node
// PRs opened in this session: the open ones listed, the merged ones counted.
//
// Three entry points, one file:
//   `prs.mjs add <sid>`      — URLs on stdin, for a hook of your own that sees a PR opened
//   `prs.mjs refresh <sid>`  — asks gh for each open PR's state, moves merged
//                              ones into the counter; spawned detached by the status line
//   import { load, prMeta, refreshIfStale } — the dch meta push and the refresh trigger, never block
//
// State never leaves <kit state>/hud/prs-<sid>.json, so it is per session by
// construction — no shared-file race like the OMC stdin cache has.
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getClaudeConfigDir, kitStateDir } from './lib/config-dir.mjs';

const REFRESH_MS = 60_000;

// Terminal-bound text: C0 and C1 controls (ESC, BEL, CSI ...) must never reach the screen from a gh title or a state file.
const clean = (s) => String(s ?? '').replace(/[\x00-\x1f\x7f-\x9f]/g, '');

const statePath = (sid) => join(kitStateDir(), 'hud', `prs-${sid}.json`);

// Same rule as prs-add.py and the meta push: a sid outside it is no session, so it never becomes a path.
const SID = /^[0-9A-Za-z-]{1,64}$/;
const validSid = (sid) => typeof sid === 'string' && SID.test(sid);

export function load(sid) {
  if (!validSid(sid)) return { open: {}, merged: 0 };
  try {
    const s = JSON.parse(readFileSync(statePath(sid), 'utf8'));
    const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
    if (!isObj(s)) return { open: {}, merged: 0 }; // a file holding null or a list
    if (!isObj(s.open)) s.open = {}; // a hand-edited open: add and refresh index into it
    return s;
  } catch (e) {
    return e?.code === 'ENOENT' ? importLegacy(sid) : { open: {}, merged: 0 };
  }
}

// Pre-kit HUD file, read once when the kit has no state yet; never written or removed.
function importLegacy(sid) {
  const none = { open: {}, merged: 0 };
  try {
    const old = JSON.parse(readFileSync(join(getClaudeConfigDir(), 'hud', `prs-${sid}.json`), 'utf8'));
    const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
    if (!isObj(old) || !isObj(old.open)) return none;
    const open = {};
    for (const [url, pr] of Object.entries(old.open)) {
      if (parseUrl(url) && isObj(pr) && typeof pr.repo === 'string' && Number.isInteger(pr.num) && pr.num > 0) open[url] = { repo: pr.repo, num: pr.num };
    }
    const merged = Number.isSafeInteger(old.merged) && old.merged >= 0 ? old.merged : 0;
    if (!Object.keys(open).length && !merged) return none;
    const state = { open, merged, checkedAt: 0 };
    save(sid, state);
    return state;
  } catch { return none; }
}

function save(sid, state) {
  if (!validSid(sid)) return;
  try {
    mkdirSync(dirname(statePath(sid)), { recursive: true });
    writeFileSync(statePath(sid), JSON.stringify(state));
  } catch { /* best effort */ }
}

/* ---------- refresh ---------- */
// Kicks off a detached `refresh` when the state is older than REFRESH_MS. The status line must never wait on the
// network, so the numbers are up to REFRESH_MS stale — which is fine, a merge is not a per-keystroke event.
export function refreshIfStale(sid, state) {
  if (!validSid(sid) || (!Object.keys(state.open ?? {}).length && !state.merged)) return;
  try {
    if (Date.now() - (state.checkedAt ?? 0) > REFRESH_MS) {
      spawn(process.execPath, [fileURLToPath(import.meta.url), 'refresh', sid], {
        detached: true, stdio: 'ignore',
      }).unref();
    }
  } catch { /* best effort */ }
}

// Open PRs and the merged count for the status line's dch meta push, open in
// insertion order, capped at 50 with titles trimmed so the payload stays small. Old state
// files carry `open: []`, which means none. Consumers render these as links, so
// only exact PR URLs pass (parseUrl, any plain host), and repo and num come from the URL itself.
export function prMeta(state) {
  const open = state.open && !Array.isArray(state.open) ? Object.entries(state.open) : [];
  return {
    open: open
      .map(([url, pr]) => [parseUrl(url), url, pr])
      .filter(([m]) => m)
      .slice(0, 50)
      .map(([m, url, pr]) => ({ url, repo: m.repo, num: m.num, title: clean(pr?.title).slice(0, 120) })),
    merged: Number(state.merged) || 0,
  };
}

/* ---------- cli ---------- */
// The same shape the prs-add hook passes: https, a plain host (no user, port, query or fragment), /<owner>/<repo>/pull/<n>.
// Any host, so GitHub Enterprise works. The host starts alphanumeric, so nothing parsed can start with "-".
const PR_URL = /^https:\/\/([A-Za-z0-9][A-Za-z0-9.-]*)\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)\/pull\/([0-9]{1,9})$/;
export function parseUrl(url) {
  const m = PR_URL.exec(String(url));
  return m ? { host: m[1], repo: `${m[2]}/${m[3]}`, num: Number(m[4]) } : null;
}

function add(sid, urls) {
  const state = load(sid);
  state.open ??= {};
  for (const url of urls) {
    const pr = parseUrl(url); // anything but a PR URL is refused: no flag, no escape reaches gh or the state
    // Already tracked, or already counted as merged — re-adding would double it.
    if (pr && !state.open[url] && !(state.mergedUrls ?? []).includes(url)) state.open[url] = { repo: pr.repo, num: pr.num };
  }
  state.checkedAt = 0; // force the next status line run to fetch titles
  save(sid, state);
}

function refresh(sid) {
  const state = load(sid);
  state.open ??= {};
  state.mergedUrls ??= [];
  for (const [url, pr] of Object.entries(state.open)) {
    const ref = parseUrl(url);
    if (!ref) { delete state.open[url]; continue; } // a state file edited by hand: never handed to gh
    let info;
    try {
      // argv only: the number and -R <host/owner/repo> are separate args, neither can start with "-"
      info = JSON.parse(execFileSync('gh', ['pr', 'view', String(ref.num), '-R', `${ref.host}/${ref.repo}`, '--json', 'state,title'], {
        encoding: 'utf8', timeout: 15_000, stdio: ['ignore', 'pipe', 'pipe'],
      }));
    } catch (e) {
      // GitHub says the repo or PR does not exist: a bogus ref (a test fixture
      // like o/r#12), never coming back, so drop it. Anything else is network
      // down or a timeout: keep it listed, retry next cycle.
      if (/Could not resolve to a (Repository|PullRequest)/.test(String(e.stderr ?? ''))) delete state.open[url];
      continue;
    }
    if (info.state === 'MERGED') {
      state.merged = (state.merged ?? 0) + 1;
      state.mergedUrls.push(url);
      delete state.open[url];
    } else if (info.state === 'CLOSED') {
      delete state.open[url]; // closed unmerged is not an achievement, just drop it
    } else {
      pr.title = clean(info.title);
    }
  }
  state.checkedAt = Date.now();
  save(sid, state);
}

// Realpaths: a kit reached through a symlinked path must still count as the entry script.
function isMain() {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)); } catch { return false; }
}

if (isMain()) {
  const [, , cmd, sid] = process.argv;
  if (!sid) process.exit(0);
  if (!validSid(sid)) process.exit(1);
  if (cmd === 'add') {
    const urls = readFileSync(0, 'utf8').split('\n').map((l) => l.trim()).filter(Boolean);
    if (urls.length) add(sid, urls);
  } else if (cmd === 'refresh') {
    // Two renders can race here; the stamp makes the loser a no-op.
    try { if (Date.now() - statSync(statePath(sid)).mtimeMs < 2000 && load(sid).checkedAt) process.exit(0); } catch { /* no state yet */ }
    refresh(sid);
  }
}
