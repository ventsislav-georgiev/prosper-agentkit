// The statusline's own stdin, as OMC cached it.
//
// Claude Code hands the statusline a rich JSON payload on stdin (model, effort,
// context window, workspace, session name), and OMC's wrapper reads it first —
// by the time this file's callers run, stdin is drained. OMC writes the payload
// to `.omc/state/hud-stdin-cache.json`, so read it from there instead. With no
// OMC HUD installed, hud-compact.mjs reads stdin itself and hands it to useStdin().
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

// Exactly ONE cache file per directory, shared by every session started there.
// A concurrent session can overwrite it between our render and theirs, so the
// session id is checked before anything is returned — better no value than
// another session's value, since every caller has a per-process fallback.
const REL = join('.omc', 'state', 'hud-stdin-cache.json');

let memo;

export function readStdinCache() {
  if (memo !== undefined) return memo;
  memo = null;
  const sid = process.env.CLAUDE_CODE_SESSION_ID;
  // Walk up: the cache lands in whichever ancestor OMC treats as the project
  // root, which is not always the directory the statusline runs from.
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    try {
      const data = JSON.parse(readFileSync(join(dir, REL), 'utf8'));
      if (!sid || data.session_id === sid) { memo = data; break; }
    } catch { /* no cache at this level */ }
    const up = dirname(dir);
    if (up === dir) break;
  }
  return memo;
}

// The payload read straight from stdin (no OMC HUD): it is this render's own, so it wins over any cache file.
export function useStdin(data) {
  if (data && typeof data === 'object') memo = data;
}
