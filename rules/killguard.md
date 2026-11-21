# Killing processes

- Never run `pkill` or `killall`. A pattern kill reaches every process whose command line matches, including other
  Claude Code sessions, and on macOS an option after the pattern becomes one more pattern. A hook denies both.
- Kill a process you started by the pid you recorded when you started it (`$!`): `kill <pid>`.
- When you must kill by pattern, use `{{kit_bin}}/safekill`. Run `{{kit_bin}}/safekill -n '<pattern>'` first to list
  the matches, then `{{kit_bin}}/safekill '<pattern>'`. It refuses a pattern under 6 characters or only digits, and
  any match that is a Claude Code or dch session; narrow the pattern instead of working around a refusal.
