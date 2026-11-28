#!/usr/bin/env node
// The Prosper Agent Kit's `dch-bridge` piece: a silent status line. Claude Code runs it through the kit runner, so
// KIT_STATE_DIR names the kit's state folder. It prints nothing, so Claude Code draws no status row. It runs as the
// status line only because that is what Claude Code re-runs on every render of every session: each run pushes the
// session's PRs to dch and keeps their state fresh (prs.mjs).
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { isatty } from 'node:tty';
import { kitStateDir } from './lib/config-dir.mjs';
import { load, prMeta, refreshIfStale } from './prs.mjs';

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
function pushMeta(sid, state) {
  let tmp;
  try {
    const dch = process.env.DCH_SESSION;
    if (!dch || typeof sid !== 'string' || !/^[0-9A-Za-z-]{1,64}$/.test(sid)) return;
    const body = { prs: prMeta(state) };
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

// The session id: the env var is this process's own; Claude Code's stdin payload is the fallback for one that
// does not set it. A TTY means a person ran this by hand, so stdin is not read.
let sid = process.env.CLAUDE_CODE_SESSION_ID;
if (!sid) {
  try { if (!isatty(0)) sid = JSON.parse(readFileSync(0, 'utf8'))?.session_id; } catch { /* empty or not JSON */ }
}
// One state read serves both jobs; load() returns an empty state for a missing or invalid sid.
const state = load(sid);
pushMeta(sid, state);
refreshIfStale(sid, state);
