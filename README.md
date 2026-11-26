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

### Safety guards

| Guard | What it stops | What to use instead |
|---|---|---|
| killguard | `pkill` and `killall`, which match every process whose command line holds the pattern, other sessions included | `kill <pid>` for a process you started, or `safekill` |
| removeguard | `rm -r $VAR`, `rm -r $(...)` and recursive deletes of top-level folders, repos and worktrees | a literal path, `${VAR:?}`, or `saferm` |
| prodguard | `gcloud`, `aws`, `kubectl`, `terraform` and `tofu` writing to a production target from your `prodguard.conf` | the guarded copies; reads pass, a production write exits 77 and is handed to you |
| compactguard | a compaction summary that grows without bound | the oversized summary is archived and a shorter one is asked for |

Permission rules add about a hundred allow and deny entries on top: no reading secret files, no disk or privilege tools,
asking before deleting a GitHub repo or release.

The guards fail closed: when one cannot run, the tool call is blocked. They are a seatbelt, not a boundary. They read
the command text, so a delete hidden in `eval`, a script file or another language gets through. Your cloud
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

The kit does not install one, but its rules expect it: a second, independent session that checks the supervisor's work
before it ships. It works alongside the supervisor:

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
| `ledger-tools` | `todo.py` and `memory.py` over one SQLite database |
| `monitors-tools` | `pr-watch.sh`, `gh-run-watch.sh` and `k8s-deploy-watch.sh` |
| `slack-tools` | `slack-say.py` |
| `hud` | a status line with tasks, ledger entries and live workers |
| `prs-hook` | feeds pull requests from `gh pr create` into the status line |
| `guard-examples` | example config files for the guards and recommended settings |
| `workers`, `workers-rules` | the eight named worker agents, and the rules for picking one |
| `prosper-rules` | how to use `ProsperApp ctl` |
| `deny-system`, `deny-secrets`, `ask-destructive-gh`, `allow-readonly`, `allow-git`, `allow-build`, `allow-network` | permission rules in `~/.claude/settings.json`; rules you already have stay |

Each piece is described in full in [REFERENCE.md](REFERENCE.md#what-it-changes).

## Requirements

- Prosper 2.175.0 or later, and Claude Code.
- `sh`, `bash`, `python3` and `awk` on PATH; `jq` is used when present.
- For the status line: `node` 22.13 or later.
- For the monitors: `gh` signed in, `jq` and `curl`, and `kubectl` for `k8s-deploy-watch.sh`.

## Customise

- Your own instructions go in `~/.config/prosper-agentkit/local.md`. It is read last and the kit never overwrites it.
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
