# Controlling Prosper

The Prosper app on this Mac has a control CLI: `ProsperApp ctl <command> [--json '<args object>']`. `ProsperApp` is the
binary inside Prosper.app (`Contents/MacOS/ProsperApp`); run it by that path unless it is on your PATH. It talks to the
running app and prints one JSON reply: exit 0 on success, 1 on an error reply or bad usage, 2 when Prosper is not running.

Use it to look at or drive Prosper's Agent Sessions: start a session, read or talk to another one, resume from History,
search its X-ray, switch layouts, change a setting. Do not drive the UI by other means when a command exists.

- Run `ProsperApp ctl describe` first. It lists every command with its summary, arguments and whether it changes state;
  that list is the truth, this text only shows the common paths.
- Reads (`mutates: false`) always work. Changing commands are refused with "agent control is off in Settings" while
  Settings, General, "Let agents control Prosper" is off: tell the person, do not try to work around it.
- Every change shows a notice with Undo (where an undo exists; `sessions.say`, `sessions.stop`, `sessions.restart`,
  `sessions.resume`, `actions.run` and `layouts.delete` have none, and `layouts.delete` is final). `ProsperApp ctl log`
  lists the recent changes. Secrets are never readable through it.
- `sessions.say` and the `prompt` of `sessions.new` refuse text that starts with `/` or `!`, and hidden characters.
- Arguments are checked before the command runs: an unknown, missing or mistyped one is an error naming it.
- A session is named by its dch name or shown title (`sessions.list`); a History record by its id (`sessions.history`).

Examples (replace the paths and names; `ProsperApp ctl` stands for the full binary path):

```sh
# start a Claude session in a folder with a first message
ProsperApp ctl sessions.new --json '{"agent":"claude","cwd":"/Users/example/project","prompt":"Read the README and list the open TODOs"}'
# two sessions side by side (both must be live; agent is claude, codex or shell)
ProsperApp ctl layout.set --json '{"layout":"side-by-side","left":"api","right":"web"}'
# resume from History: dch's own message, none, or yours
ProsperApp ctl sessions.history
ProsperApp ctl sessions.resume --json '{"id":"<id from history>"}'
ProsperApp ctl sessions.resume --json '{"id":"<id>","noMessage":true}'
ProsperApp ctl sessions.resume --json '{"id":"<id>","message":"Carry on with the migration"}'
# talk to a session and wait for it: say needs it idle, then wait with changed:true
ProsperApp ctl sessions.say --json '{"name":"api","text":"Run the tests"}'
ProsperApp ctl sessions.wait --json '{"name":"api","changed":true,"timeout":60}'
ProsperApp ctl sessions.transcript --json '{"name":"api","limit":10}'
# X-ray: search a session's history, or ask what it said about a file
ProsperApp ctl xray.search --json '{"session":"api","query":"migration","scope":"project"}'
ProsperApp ctl xray.ref --json '{"session":"api","path":"src/main.swift"}'
# layouts
ProsperApp ctl layouts.list
ProsperApp ctl layouts.switch --json '{"name":"Work"}'
```

- `sessions.wait` without `changed:true` answers at once when the session is already idle: always pass `changed:true`
  right after `sessions.say`. It returns `{reached, state}`, `{ended}` when the session ended first, and an error on timeout.
- `sessions.prompt` shows the question a blocked session waits on. Answering it stays with the person.
- Other commands: `sessions.interrupt`, `sessions.screen`, `sessions.get`, `sessions.rename`, `sessions.model`,
  `sessions.effort`, `sessions.focus`, `actions.list` and `actions.run`, `settings.schema`, `settings.get` and
  `settings.set`, `themes.list` and `themes.set`, `extensions.list`, `ccpool.status`. Read `describe` for their arguments.
