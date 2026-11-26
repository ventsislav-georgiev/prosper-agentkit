# Lean changes (condensed from the ponytail plugin)

- Make the smallest change that fully solves the task, and finish every place it must reach: callers, tests, fixtures, config.
- Before writing code, take the first that works: not needed at all, an existing helper in the codebase, the standard library or platform, an installed dependency, then the minimum new code. Never add a dependency for a few lines.
- No abstraction, option, config or "for later" code nobody asked for. Deletion beats addition; keep the codebase's structure.
- Bug fix: find every caller first, then fix the root cause once in the shared code.
- New non-trivial logic gets one small test or self-check. A known shortcut gets a `shortcut: <limit>, <when to upgrade>` comment.
- Never cut validation at trust boundaries, error handling that prevents data loss, security, or anything the user asked for.
- End the reply with one or two lines: what you skipped or did not check, and any risk.
