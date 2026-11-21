import { homedir } from 'node:os';
import { join, normalize, parse, sep } from 'node:path';

function stripTrailingSep(p) {
  if (!p.endsWith(sep)) {
    return p;
  }

  return p === parse(p).root ? p : p.slice(0, -1);
}

// Claude Code's own folder (its task store, and an OMC HUD if one is installed): CLAUDE_CONFIG_DIR, else ~/.claude.
export function getClaudeConfigDir() {
  const home = homedir();
  const configured = process.env.CLAUDE_CONFIG_DIR?.trim();

  if (!configured) {
    return stripTrailingSep(normalize(join(home, '.claude')));
  }

  if (configured === '~') {
    return stripTrailingSep(normalize(home));
  }

  if (configured.startsWith('~/') || configured.startsWith('~\\')) {
    return stripTrailingSep(normalize(join(home, configured.slice(2))));
  }

  return stripTrailingSep(normalize(configured));
}

// The kit's state folder, the same rule as todo.py: KIT_STATE_DIR (set by the kit runner), else the XDG data dir.
// The ledger database and the HUD's own files (hud/) live here.
export function kitStateDir() {
  if (process.env.KIT_STATE_DIR) return process.env.KIT_STATE_DIR;
  return join(process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'), 'prosper-agentkit');
}
