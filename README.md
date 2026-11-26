# Prosper Agent Kit

A way of working for Claude Code, installed and removed by Prosper as one kit. It gives the agent a protocol, guard rails
and a place to track work:

- **The protocol:** one ledger of work, a supervisor that hands work to named workers and reviews it, and a heartbeat
  that keeps the queue moving.
- **Guard rails:** hooks that stop the commands that hurt most when an agent gets them wrong.
- **Tracking:** one SQLite database for todos, open questions and memory, shown live in the status line.

Every part is its own piece, and you can switch any piece off on the install sheet. This page explains how the parts
work together. [REFERENCE.md](REFERENCE.md) has every piece, setting and file in detail.

Where it sits: Prosper is the Mac app you watch and steer your agent sessions from. dch keeps those sessions alive and lets
agents and scripts drive them. This kit is what each session knows and is allowed to do.

## How it works

The kit's `CLAUDE.md` holds the working protocol, and six short rule files hold the safety and tooling rules. Your own
`local.md` is read last, so your lines win.

### The ledger: the list is the plan

- **Two lists, one set of ids.** The session's task list is the working queue. The ledger is the record that outlives
  the session. Both are written as work happens, so a crashed session loses nothing.
- **One ledger per project.** The project is chosen once, at session start: by the session's name first, then by the
  folder it started in. A later `cd` changes nothing.
- **Entries.** Ids never change and are never reused. Status is one of `OPEN`, `IN PROGRESS`, `DONE`, `DROPPED` or
  `PARKED`, and every change adds a dated line to the entry, so the history stays. Progress is appended, never
  overwritten. A close says why and what came out of it.
- **The merge is the close.** When a pull request merges, its entry is marked `DONE` with the link in the same step.
- **Nothing leaves the list without you.** `todo.py plan` runs at session start, on every heartbeat and before any
  status answer, and the agent acts on its flags (idle, unblocked, parked) in that same tick.
  - `DROPPED` needs your own words; the tool refuses without them.
  - `PARKED` needs the condition that un-parks it.
  - The order is your priority. Moving an entry, or taking a later one first, is done with your words in the note.
- **Questions for you** are `OQ-<n>` rows in the same database, answered with `todo.py rule`.
- **Many writers.** Every write passes `--expect-version`. When another session wrote first, the write is refused
  (exit 3), and the writer re-reads and applies its change again.

### One database for work and memory

The ledger and Claude Code's memory share one SQLite file: `ledger.sqlite3` in the kit's state folder, or the file
`LEDGER_DB` names. `memory.py` reads and writes memory through `todo.py`'s connection.

The memory files Claude Code loads from `~/.claude/projects/<project>/memory/` are copies made from the database:

- `memory.py write` saves the row and rewrites that one file in the same step, so the file is never behind.
- `memory.py delete` removes the row, then rewrites the project's whole memory folder.
- `memory.py export <dir>` rewrites a folder when you ask. `--check` shows what would change and writes nothing.

Nothing copies them on a schedule. A memory file written straight to disk, without `memory.py`, has no row in the
database, so the next export of that project moves it to `memory-archive/`. It is not deleted, but Claude no longer
loads it. That is why the rules say to write memory only through `memory.py`.

### Supervisor and workers

The main session only supervises: it hands out work, reviews it, unblocks it, keeps the ledger and talks to you.
Workers do the implementing.

- **Dispatch.** An unblocked entry is the go-ahead; there is no asking. At most 6 workers run at once. Entries marked
  `FORKABLE` run side by side; entries that touch the same files never do.
- **Named workers.** Eight agent files with their model, effort and tools fixed, because the Agent tool has no effort
  setting of its own:

  | Worker | Used for |
  |---|---|
  | `worker-haiku` | finding and reading only; it never edits |
  | `worker-sonnet-low` / `-medium` | fully specified work that a test or build checks |
  | `worker-opus-medium` | the default for anything harder |
  | `worker-opus-low` | single-file work too hard for Sonnet |
  | `worker-opus-high` | the redo after a failed review, never a first pick |
  | `worker-opus-xhigh` / `-max` | rarely: an extreme, critical entry |

  A failed Sonnet review goes to `worker-opus-medium`, not to Sonnet at a higher effort.
- **Short workers, short reports.** A worker aims to finish in about 60 tool calls. Past that it writes down what is
  done and what remains, and a fresh worker carries on. Its report is a verdict and a file path, not the full output.
- **Review gate.** Every worker report gets a critic's pass. The supervisor reads the diff, runs the tests and checks
  each claim against what is on disk, and nothing new launches until that review is in the ledger. A pass with a pull
  request starts `pr-watch.sh`. A fail goes to a fresh worker with the critique.
- **Clean up.** Finished workers are stopped, their worktrees removed, and the session never `cd`s into a worktree.

### The heartbeat

The kit says what a heartbeat does, not how often:

- run `todo.py plan` and act on what it flags;
- run `ListAgents` and `git worktree list`, then stop finished workers and remove leftover worktrees.

The session decides when. In Claude Code's self-paced `/loop`, each tick schedules the next one; every 20 to 30
minutes works well. That timer is only the fallback: a worker's report, a monitor exiting or a message from another
session wakes the supervisor sooner. The timer catches whatever went quiet without saying so.

### Monitors

Long waits use the kit's watchers instead of a polling loop written on the spot. Each prints only changes, so silence
means nothing changed, and each exits on an end state.

- `pr-watch.sh` follows a pull request until it merges or closes. It reruns infrastructure failures and merges once
  the pull request is approved and green.
- `gh-run-watch.sh` follows one GitHub Actions run to its end.
- `k8s-deploy-watch.sh` follows a Deployment's ready count.

The session checks that its watchers are still alive about every 5 minutes.

### MCP bridge

A laptop that switches networks (Wi-Fi to tethering, a VPN that reconnects) drops in-flight calls to a remote MCP
server, and Claude Code then marks that server failed until you reconnect it with `/mcp`. `mcpbridge` is a local stdio
MCP server that relays to the remote streamable-HTTP one: it holds each call while the network is gone, retries it up
to a deadline (`--deadline`, default 120 s), re-opens the MCP session once the server is back, and never exits on an
upstream failure. A tool call that may already have reached the server is answered with an error, not run twice. For
a server that needs a login it runs the MCP OAuth flow in your browser once and keeps the tokens in
`~/.config/mcpbridge/` (folder 0700, files 0600, never logged). Point a server entry in Claude Code's MCP config at it:

```json
"my-server": { "command": "<kit bin>/mcpbridge", "args": ["https://example.com/mcp"] }
```

### Startup context

Every session pays for its system prompt, tool list, MCP servers, skills listing and CLAUDE.md files before your first
message, and it pays again on every turn. To trim it, measure first, then switch off what you never call:

1. Measure with `ctxprobe.sh` (`spend-tools`): `ctxprobe.sh ~/src/app` prints the starting tokens of a fresh session in
   that folder. Run it again with one variant, such as `ctxprobe.sh ~/src/app --disable-slash-commands` (no skills) or
   `--settings '{"enabledPlugins":{"name@marketplace":false}}'` (one plugin off); the difference is what that thing
   costs. Each run is one small real model call.
2. Find what you never use with `usage-audit.py [days]`: built-in tool calls, MCP calls per server and per project, and
   Skill calls from your transcripts of the last 14 days.
3. Switch off the plugins you never call (`/plugin`, or `enabledPlugins` in `~/.claude/settings.json`). Deny an MCP
   server in the projects that never use it: a `permissions.deny` rule in that project's `.claude/settings.local.json`
   naming the server the way Claude Code's MCP permission rules do (`mcp`, two underscores, the server name). Copy the `permissions.deny` list from `settings-recommended.example.json` to drop the built-in tools few sessions call.

The skills listing has a size budget: past it Claude Code shortens the descriptions, so dropping one skill saves less
than its size. Measure before and after rather than adding up file sizes.

The kit's `settings-recommended.example.json` (in the kit's config folder) lists deny rules for these built-in tools,
about 3.4k fewer tokens at every session start. They are not applied for you: merge the ones you want into
`~/.claude/settings.json`.

| Tool | What it is for |
|---|---|
| `EnterPlanMode`, `ExitPlanMode` | plan mode: the model writes a plan and waits for your approval; denying them turns plan mode off |
| `EnterWorktree`, `ExitWorktree` | move the session into a new git worktree and back |
| `NotebookEdit` | edit cells of a Jupyter notebook |
| `Workflow` | run a saved multi-step workflow |
| `ReportFindings` | hand back structured findings from a review run |
| `ShareOnboardingGuide` | share an onboarding guide for a repository with teammates |
| `DesignSync` | sync designs from a design tool into the session |
| `PublishPlugin` | publish a plugin to a marketplace |
| `RemoteTrigger` | create and run scheduled remote agents |

### Spend review

`spend-report.py START [END]` (`spend-tools`) reports what a time window cost at API list prices, used only as
weights: main sessions against workers, cache reads, writes and output, full cache rewrites by cause (expiry,
account rotation, compaction, other), workers by model and by worker tier, ledger dispatches per tier with the entries
later sent to a higher tier, and the cost per closed ledger entry. It also reads Prosper's ccpool files (usage rows,
events and `state.json` under `~/Library/Application Support/Prosper/ccpool`) for bench and rotation events, refused
startup quota checks, compaction summary calls the transcripts do not show, and the sessions pinned to each account.
Subcommands break the window down further (`expiry`, `tokens`, `ctxsize`, `byproject`, `revive`), size the account
pool (`points`, `accounts`, `fit`) and take one transcript apart (`compact`, `supervisor`, `floor`); run it without
arguments for the list. Accounts on a smaller plan go in the `spend_small_accounts` setting so the account-week
totals leave them out. `rules/daily-review-prompt.md` in the kit folder is a prompt for a spend session to run once a
day from a session cron: it runs the report for the last 24 hours, compares it with the day before and your own
baseline, and names at most one recommendation. Everything reads only.

### Safety guards

| Guard | What it stops | What to use instead |
|---|---|---|
| killguard | `pkill` and `killall`, which match every process whose command line holds the pattern, other sessions included | `kill <pid>` for a process you started, or `safekill` |
| removeguard | `rm -r $VAR`, `rm -r $(...)` and recursive deletes of top-level folders, repos and worktrees | a literal path, `${VAR:?}`, or `saferm` |
| prodguard | `gcloud`, `aws`, `kubectl`, `terraform` and `tofu` writing to a production target from your `prodguard.conf` | the guarded copies; reads pass, a production write exits 77 and is handed to you |
| compactguard | a compaction summary that grows without bound | the oversized summary is archived and a shorter one is asked for |

Permission rules add about a hundred allow and deny entries on top: no reading secret files, no disk or privilege tools,
asking before deleting a GitHub repo or release.

When Prosper cannot run killguard, removeguard or prodguard at all, the tool call is blocked. A guard that runs but
cannot parse a call lets it through, so a broken parse never blocks every command. They are a seatbelt, not a
boundary: they read the command text, so a delete hidden in `eval`, a script file or another language gets through. Your cloud
permissions remain the real boundary.

### Talking to people

- Every pull request, issue, merge request or Jira key in text you read is a full link.
- Slack messages are built with `slack-say.py`: at most 6 lines, written as the agent, never as you.
- Review threads are resolved by the agent once a reply or a fix settles them.
- `ProsperApp ctl` drives Prosper: `describe` lists the commands. When "Let agents control Prosper" is off, the
  agent tells you instead of working around it.

### What is enforced and what is instruction

- **Enforced by hooks:** the four guards and the permission rules.
- **Enforced by the tools:** the ledger refuses a stale write, refuses `DROPPED` without your words and keeps the
  status column in step with the entry's history.
- **Instruction only:** everything else in this section. The model follows it, which is why there is a review gate,
  and why a second session checking the work pays off.

### A QA session

The kit neither installs nor requires one; its rules mention a QA session only in passing. It is a practice that pairs
well with the protocol: a second, independent session that checks the supervisor's work before it ships, alongside
the supervisor:

- **Before every push** the supervisor sends QA the commit, the changed files and the evidence (tests, CI), and waits
  for a verdict. Risky changes (parsers, regexes, CI workflows, anything security-relevant) get a deeper read.
- **Mutation checks.** QA breaks the code on purpose and checks that a test fails. A change no test notices means a
  test that proves nothing.
- **Release checks.** After a release, QA checks the build, the artifact and the update feed on its own.
- **Its own copy and its own ledger.** QA works in its own clone, pinned to an exact commit, and keeps its own project
  in the same database, with its own workers under the same protocol.

## What it changes

| Piece | What it adds |
|---|---|
| `rules` | one import line in `~/.claude/CLAUDE.md` that loads the kit's `CLAUDE.md`, then your `local.md` |
| `killguard-tools`, `-hook`, `-rules` | `safekill`, a hook denying `pkill` and `killall`, and the matching rules |
| `removeguard-tools`, `-hook`, `-rules` | `saferm`, a hook denying unsafe recursive deletes, and the matching rules |
| `prodguard-tools`, `-hook`, `-rules` | guarded cloud CLIs, a hook denying the ways around them, and the matching rules |
| `compactguard-hook`, `-rules` | a `PreCompact` hook that caps the summary, and the matching rules |
| `worker-rules-hook` | a `SubagentStart` hook that hands your `worker-rules.md`, or the kit's lean-code rules, to every subagent |
| `lean-code-rules` | the same lean-code rules for your own sessions |
| `ledger-tools` | `todo.py` and `memory.py` over one SQLite database |
| `monitors-tools` | `pr-watch.sh`, `gh-run-watch.sh` and `k8s-deploy-watch.sh` |
| `slack-tools` | `slack-say.py` |
| `mcpbridge-tools` | `mcpbridge`, a stdio MCP server that keeps a remote MCP server's calls alive across network switches |
| `spend-tools` | `ctxprobe.sh` and `usage-audit.py`, to measure a session's starting tokens and find what you never use; `spend-report.py`, the spend review over your transcripts, Prosper's ccpool files and the ledger |
| `hud` | a status line with tasks, ledger entries and live workers |
| `prs-hook` | feeds pull requests from `gh pr create` into the status line |
| `guard-examples` | example config files for the guards and recommended settings |
| `workers`, `workers-rules` | the eight named worker agents, and the rules for picking one |
| `prosper-rules` | how to use `ProsperApp ctl` |
| `deny-system`, `deny-secrets`, `ask-destructive-gh`, `allow-readonly`, `allow-git`, `allow-build`, `allow-network` | permission rules in `~/.claude/settings.json`; rules you already have stay |

Each piece is described in full in [REFERENCE.md](REFERENCE.md#what-it-changes).

## Requirements

- Prosper 2.175.0 or later, and Claude Code.
- `sh`, `bash`, `python3` and `awk` on PATH; `jq` is used when present. Python scripts start `/usr/bin/python3` when
  the Command Line Tools or Xcode back it, which skips a pyenv, asdf or conda shim, and `python3` on PATH otherwise.
- For the status line: `node` 22.13 or later.
- For the monitors: `gh` signed in, `jq` and `curl`, and `kubectl` for `k8s-deploy-watch.sh`.

## Customise

- Your own instructions go in `~/.config/prosper-agentkit/local.md`. It is read last and the kit never overwrites it.
- Rules every worker should get go in `~/.config/prosper-agentkit/worker-rules.md`; the `worker-rules-hook` piece hands
  them to each subagent at start. Without that file workers get the kit's lean-code rules; your file replaces them
  whole, and an empty file sends nothing.
- Production targets go in `prodguard.conf`, and delete scopes in `removeguard.conf`, both in the same folder. The
  examples are copied there for you.
- Run your own script before or after any hook or tool with a `<name>.pre` or `<name>.post` file in
  `~/.config/prosper-agentkit/hooks/`.
- Switch any piece off on the install sheet; a piece that needs it goes off with it.

Settings, worker models and the recommended Claude Code settings are in [REFERENCE.md](REFERENCE.md#customise).

## Remove

Remove the kit in Prosper. It takes out everything it added: the import line, the hooks, the status line (your own comes
back), the permission rules, its tools and the agent files it wrote. Your `local.md`, your config files, the ledger
database and the memory files stay. [REFERENCE.md](REFERENCE.md#remove) lists everything that stays.
