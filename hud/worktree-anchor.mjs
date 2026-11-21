// OMC writes `.omc/state/...` under the git root of process.cwd(), with mkdir -p. In a linked worktree a
// render racing `git worktree remove` recreates the removed folder, which then has no .git and outlives
// the worktree. Anchoring OMC in the main checkout keeps every write out of worktrees.
import { readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';

/** The main checkout's root when `cwd` is inside a linked worktree, else undefined. */
export function omcAnchor(cwd) {
  for (let dir = cwd; ; dir = dirname(dir)) {
    let st;
    try { st = statSync(join(dir, '.git')); } catch { st = undefined; }
    if (st?.isDirectory()) return undefined;
    // A submodule's .git file points into the superproject's .git/modules, not .git/worktrees: left alone.
    if (st?.isFile()) return /^gitdir:\s*(.+?)\/\.git\/worktrees\/[^/\n]+\s*$/m.exec(readFileSync(join(dir, '.git'), 'utf8'))?.[1];
    if (dirname(dir) === dir) return undefined;
  }
}
