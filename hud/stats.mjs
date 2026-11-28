#!/usr/bin/env node
// The ledger stats one-liner (`todo.py stats <project> --hud`) for the HUD.
//
//   import { statsLine }       — reads <kit state>/hud/stats-<project>.txt only, never runs todo.py, never waits;
//                                a missing or older-than-REFRESH_MS file kicks off ONE detached refresh
//   `stats.mjs refresh <proj>` — runs todo.py and rewrites the file; spawned detached by the render
//
// One lock file (created O_EXCL by the render, removed by the refresh) keeps concurrent renders from spawning a storm.
// A failed todo.py (no ledger, exit 4) rewrites the old text, or an empty file, so the failure is retried in
// REFRESH_MS, not on every render.
import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { kitStateDir } from './lib/config-dir.mjs';

const REFRESH_MS = 5 * 60_000;
const LOCK_STALE_MS = 60_000; // a refresh that died without removing its lock
const PROJECT = /^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/; // a name outside it never becomes a path or an argv word

const file = (project, ext) => join(kitStateDir(), 'hud', `stats-${project}.${ext}`);
// Terminal-bound text: controls from a hand-edited cache file never reach the screen.
const clean = (s) => String(s ?? '').replace(/[\x00-\x1f\x7f-\x9f]/g, '').slice(0, 300);

// The installed kit's todo.py: $KIT_BIN, else the tools dir next to this hud dir (source tree), else PATH.
function todoPy() {
  const here = dirname(fileURLToPath(import.meta.url));
  const found = [process.env.KIT_BIN && join(process.env.KIT_BIN, 'todo.py'), join(here, '..', 'tools', 'ledger', 'todo.py')]
    .find((p) => p && existsSync(p));
  return found ?? 'todo.py';
}

function kick(project) {
  const lock = file(project, 'lock');
  try {
    mkdirSync(dirname(lock), { recursive: true });
    try { if (Date.now() - statSync(lock).mtimeMs > LOCK_STALE_MS) unlinkSync(lock); } catch { /* no lock */ }
    closeSync(openSync(lock, 'wx')); // EEXIST: another render's refresh is running
    spawn(process.execPath, [fileURLToPath(import.meta.url), 'refresh', project], { detached: true, stdio: 'ignore' }).unref();
  } catch { /* locked, or best effort */ }
}

export function statsLine(project) {
  if (typeof project !== 'string' || !PROJECT.test(project)) return null;
  let text = null;
  let fresh = false;
  try {
    fresh = Date.now() - statSync(file(project, 'txt')).mtimeMs < REFRESH_MS;
    text = clean(readFileSync(file(project, 'txt'), 'utf8')).trim();
  } catch { /* no cache yet */ }
  if (!fresh) kick(project);
  return text || null;
}

function refresh(project) {
  const out = file(project, 'txt');
  try {
    let text = '';
    try { text = readFileSync(out, 'utf8'); } catch { /* none yet */ }
    const r = spawnSync(todoPy(), ['stats', project, '--hud'], { encoding: 'utf8', timeout: 20_000, stdio: ['ignore', 'pipe', 'ignore'] });
    if (r.status === 0 && r.stdout.trim()) text = r.stdout.trim();
    const tmp = `${out}.${process.pid}.tmp`;
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(tmp, text);
    renameSync(tmp, out);
  } catch { /* best effort */ } finally {
    try { unlinkSync(file(project, 'lock')); } catch { /* already gone */ }
  }
}

function isMain() {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)); } catch { return false; }
}

if (isMain()) {
  const [, , cmd, project] = process.argv;
  if (cmd === 'refresh' && PROJECT.test(project ?? '')) refresh(project);
}
