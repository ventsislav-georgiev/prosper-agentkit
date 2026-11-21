# Recursive deletes

- A recursive delete (`rm -r`, `find -delete`, `find -exec rm -r`, `xargs rm -r`) names its target by a literal path,
  or by a variable in the `${VAR:?}` form so an empty value stops the command. Never by a bare `$VAR`, an inherited
  variable (`$TMPDIR`, `$HOME`, `$PWD`) or a command substitution. A hook denies those shapes.
- Prefer `{{kit_bin}}/saferm [-n] <path>`: it refuses symlinked paths, paths outside the allowed scratch prefixes, git
  repos and worktrees, and more than 5000 entries. `-n` shows what it would remove.
- Remove a git worktree with `git worktree remove <path>`, never with `rm`.
- Never hide a delete in a script file, `eval` or `bash -c "$x"` to get past the hook.
