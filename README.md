# Prosper Agent Kit

A way of working for Claude Code, installed and removed by Prosper as one kit.

| Part | What it gives the agent |
|---|---|
| **Protocol** | a supervisor that hands work to named workers and reviews it, one ledger of work, a heartbeat that keeps the queue moving |
| **Tracking** | one SQLite database for todos, open questions and memory |
| **Guard rails** | hooks that stop the commands that hurt most when an agent gets them wrong |
| **Tools** | monitors, an MCP bridge, a dch bridge, and tools to measure startup context and spend |

- **Where it sits:** Prosper is the Mac app you watch and steer agent sessions from. dch keeps those sessions alive and
  lets agents and scripts drive them. This kit is what each session knows and is allowed to do.
- **Pieces:** every part is its own piece; switch any of them off on the install sheet.
- **Details:** this page explains how the parts fit together. [REFERENCE.md](REFERENCE.md) has every piece, setting and
  file.

## How it works

The kit's `CLAUDE.md` holds the protocol, and seven short rule files hold the safety and tooling rules. Your own
`local.md` is read last, so your lines win.

The sections follow the work: who does it, where it is tracked, what keeps it moving, what keeps it safe, and the tools
around it.

### 1. Roles

#### Supervisor

The main session only supervises: it hands out work, reviews it, unblocks it, keeps the ledger and talks to you.

- **Dispatch:** an unblocked entry is the go-ahead; there is no asking.
- **Concurrency:** at most 6 workers at once. `FORKABLE` entries run side by side; entries touching the same files never
  do.
- **Clean up:** finished workers are stopped and their worktrees removed. The session never `cd`s into a worktree.

#### Workers

Eight agent files with model, effort and tools fixed, because the Agent tool has no effort setting of its own.

| Worker | Used for |
|---|---|
| `worker-haiku` | finding and reading only; it never edits |
| `worker-sonnet-low` / `-medium` | fully specified work that a test or build checks |
| `worker-opus-medium` | the default for anything harder |
| `worker-opus-low` | single-file work too hard for Sonnet |
| `worker-opus-high` | the redo after a failed review, never a first pick |
| `worker-opus-xhigh` / `-max` | rarely: an extreme, critical entry |

- **Escalation:** a failed Sonnet review goes to `worker-opus-medium`, not to Sonnet at a higher effort.
- **Short runs:** a worker aims to finish in about 60 tool calls. Past that it writes down what is done and what
  remains, and a fresh worker carries on.
- **Short reports:** a verdict and a file path, not the full output.

#### Review gate

Every worker report gets a critic's pass before anything new launches.

- The supervisor reads the diff, runs the tests and checks each claim against what is on disk.
- The verdict goes into the ledger.
- **Pass** with a pull request starts `pr-watch.sh`. **Fail** goes to a fresh worker with the critique.

#### QA session (optional)

The kit neither installs nor requires one, but it pairs well with the protocol: a second, independent session that
checks the supervisor's work before it ships.

- **Before every push:** the supervisor sends QA the commit, the changed files and the evidence (tests, CI), and waits
  for a verdict. Risky changes (parsers, regexes, CI workflows, anything security-relevant) get a deeper read.
- **Mutation checks:** QA breaks the code on purpose and checks that a test fails. A change no test notices means a test
  that proves nothing.
- **Release checks:** after a release, QA checks the build, the artifact and the update feed on its own.
- **Its own copy and ledger:** its own clone pinned to an exact commit, its own project in the same database, its own
  workers under the same protocol.

### 2. The ledger: the list is the plan

- **Two lists, one set of ids:** the session's task list is the working queue; the ledger is the record that outlives
  the session. Both are written as work happens, so a crash loses nothing.
- **One ledger per project:** chosen once at session start, by session name first, then by the start folder. A later
  `cd` changes nothing.
- **Entries:**
  - ids never change and are never reused;
  - status is `OPEN`, `IN PROGRESS`, `DONE`, `DROPPED` or `PARKED`, and every change adds a dated line, so the history
    stays;
  - progress is appended, never overwritten; a close says why and what came out of it.
- **The merge is the close:** when a pull request merges, its entry is marked `DONE` with the link in the same step.
- **Nothing leaves the list without you:** `todo.py plan` runs at session start, on every heartbeat and before any
  status answer, and the agent acts on its flags (idle, unblocked, parked) in the same tick.
  - `DROPPED` needs your own words; the tool refuses without them.
  - `PARKED` needs the condition that un-parks it.
  - The order is your priority: moving an entry, or taking a later one first, carries your words in the note.
- **Questions for you:** `OQ-<n>` rows in the same database, answered with `todo.py rule`.
- **Many writers:** every write passes `--expect-version`. If another session wrote first, the write is refused
  (exit 3) and the writer re-reads and applies its change again.

### 3. Memory: the same database

- **One file:** the ledger and Claude Code's memory share `ledger.sqlite3` in the kit's state folder, or the file
  `LEDGER_DB` names (`KIT_LEDGER_DB` also works; `LEDGER_DB` wins).
- **Records:** review gates with `todo.py append --kind review --verdict pass|fail [--tier ...]`, landings with
  `todo.py set-status --pr <url>`. `memory.py` goes through `todo.py`'s connection.
- **Memory files are copies:** the files Claude Code loads from `~/.claude/projects/<project>/memory/` are written from
  the database.
  - `memory.py write` saves the row and rewrites that one file in the same step.
  - `memory.py delete` removes the row, then rewrites the project's memory folder.
  - `memory.py export <dir>` rewrites a folder on request; `--check` shows what would change.
- **Write only through `memory.py`:** nothing copies on a schedule. A file written straight to disk has no row, so the
  next export moves it to `memory-archive/`. It is kept, but Claude no longer loads it.

### 4. Keeping work moving

#### Heartbeat

The kit says what a heartbeat does, not how often:

- run `todo.py plan` and act on what it flags;
- run `ListAgents` and `git worktree list`, then stop finished workers and remove leftover worktrees.

- **When:** in Claude Code's self-paced `/loop`, each tick schedules the next; every 20 to 30 minutes works well.
- **Fallback only:** a worker's report, a monitor exiting or a message from another session wakes the supervisor
  sooner. The timer catches whatever went quiet.

#### Monitors

Long waits use the kit's watchers, not a polling loop written on the spot. Each prints only changes (silence means
nothing changed) and exits on an end state.

| Monitor | Follows |
|---|---|
| `pr-watch.sh` | a pull request until it merges or closes; reruns infrastructure failures and merges once approved and green |
| `gh-run-watch.sh` | one GitHub Actions run to its end |
| `k8s-deploy-watch.sh` | a Deployment's ready count |

The session checks its watchers are alive about every 5 minutes.

### 5. Guard rails

| Guard | What it stops | Use instead |
|---|---|---|
| killguard | `pkill` and `killall`, which match every process whose command line holds the pattern, other sessions included | `kill <pid>` for a process you started, or `safekill` |
| removeguard | `rm -r $VAR`, `rm -r $(...)` and recursive deletes of top-level folders, repos and worktrees | a literal path, `${VAR:?}`, or `saferm` |
| prodguard | `gcloud`, `aws`, `kubectl`, `terraform` and `tofu` writing to a production target from your `prodguard.conf` | the guarded copies; reads pass, a production write exits 77 and is handed to you |
| compactguard | a compaction summary that grows without bound | the oversized summary is archived and a shorter one is asked for |

- **Permission rules:** about a hundred allow and deny entries on top: no reading secret files, no disk or privilege
  tools, asking before deleting a GitHub repo or release.
- **Failure mode:** when Prosper cannot run killguard, removeguard or prodguard at all, the call is blocked. A guard that
  runs but cannot parse a call lets it through, so a broken parse never blocks every command.
- **Limits:** they read the command text, so a delete hidden in `eval`, a script file or another language gets through.
  They are a seatbelt; your cloud permissions remain the real boundary.

#### What is enforced and what is instruction

| Kind | Covers |
|---|---|
| Enforced by hooks | the four guards and the permission rules |
| Enforced by the tools | the ledger refuses a stale write, refuses `DROPPED` without your words, and keeps the status column in step with the entry's history |
| Instruction only | everything else: the model follows it, which is why there is a review gate and why a QA session pays off |

### 6. Talking to people

- **Links:** every pull request, issue, merge request or Jira key in text you read is a full link.
- **Slack:** messages are built with `slack-say.py`: at most 6 lines, written as the agent, never as you.
- **Review threads:** resolved by the agent once a reply or a fix settles them.
- **Prosper:** `ProsperApp ctl` drives it (`describe` lists the commands). When "Let agents control Prosper" is off, the
  agent tells you instead of working around it.

### 7. Tools

#### dch bridge

The kit's link from Claude Code to dch. It runs as Claude Code's status line, because that is the hook Claude Code
calls on every update with the live session. It prints nothing, so no status row is drawn. Each run pushes the
session's pull requests (open ones and the merged count) to dch with `dch --meta`, where Prosper shows them, and keeps
their state fresh from `gh` in the background. `prs-hook` adds a pull request when `gh pr create` prints one.

#### MCP bridge

- **Problem:** a laptop that switches networks (Wi-Fi to tethering, a VPN that reconnects) drops in-flight calls to a
  remote MCP server, and Claude Code marks the server failed until you reconnect it with `/mcp`.
- **What `mcpbridge` does:** a local stdio MCP server that relays to the remote streamable-HTTP one.
  - It holds each call while the network is gone and retries it up to a deadline (`--deadline`, default 120 s).
  - It re-opens the MCP session once the server is back and never exits on an upstream failure.
  - A tool call that may already have reached the server gets an error, not a second run.
  - For a server that needs a login, it runs the MCP OAuth flow in your browser once and keeps the tokens in
    `~/.config/mcpbridge/` (folder 0700, files 0600, never logged).
- **Setup:** point a server entry in Claude Code's MCP config at it:

```json
"my-server": { "command": "<kit bin>/mcpbridge", "args": ["https://example.com/mcp"] }
```

#### Startup context

Every session pays for its system prompt, tool list, MCP servers, skills listing and CLAUDE.md files before your first
message, and again on every turn. Measure first, then switch off what you never call:

1. **Measure** with `ctxprobe.sh` (`spend-tools`): `ctxprobe.sh ~/src/app` prints the starting tokens of a fresh session
   in that folder. Run it again with one variant; the difference is that thing's cost. Each run is one small real
   model call. Variants:
   - `--disable-slash-commands` (no skills);
   - `--settings '{"enabledPlugins":{"name@marketplace":false}}'` (one plugin off).
2. **Find what you never use** with `usage-audit.py [days]`: built-in tool calls, MCP calls per server and per project,
   and Skill calls from your transcripts (default 14 days).
3. **Switch it off:**
   - plugins: `/plugin`, or `enabledPlugins` in `~/.claude/settings.json`;
   - an MCP server a project never uses: a `permissions.deny` rule in that project's `.claude/settings.local.json`,
     naming the server the way Claude Code's MCP permission rules do (`mcp`, two underscores, the server name);
   - rarely used built-in tools: the `permissions.deny` list below.

- **Skills budget:** past its size budget Claude Code shortens skill descriptions, so dropping one skill saves less than
  its size. Measure before and after.
- **Recommended denies:** `settings-recommended.example.json` (in the kit's config folder) denies these built-in tools,
  about 3.4k fewer tokens per session start. Not applied for you: merge what you want into `~/.claude/settings.json`.

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

#### Spend review

`spend-report.py START [END]` (`spend-tools`) reports what a time window cost at API list prices, used only as weights.
Everything reads only.

- **Breakdown:**
  - main sessions against workers; cache reads, writes and output;
  - full cache rewrites by cause (expiry, account rotation, compaction, other);
  - workers by model and by tier; ledger dispatches per tier, with the entries later sent to a higher tier;
  - the cost per closed ledger entry.
- **Prosper's pool files:** usage rows, events and `state.json` under
  `~/Library/Application Support/Prosper/agentpool` (`ccpool` before Prosper's rename), for bench and rotation events, refused startup quota checks,
  compaction summary calls the transcripts do not show, and the sessions pinned to each account.
- **Subcommands** (run it without arguments for the list):
  - break the window down: `expiry`, `tokens`, `ctxsize`, `byproject`, `revive`;
  - size the account pool: `points`, `accounts`, `fit`;
  - take one transcript apart: `compact`, `supervisor`, `floor`.
- **Smaller plans:** list those accounts in the `spend_small_accounts` setting so the account-week totals leave them out.
- **Daily review:** `rules/daily-review-prompt.md` in the kit folder is a prompt for a spend session to run once a day
  from a session cron. It runs the report for the last 24 hours, compares it with the day before and your baseline, and
  names at most one recommendation.

## What it changes

| Piece | What it adds |
|---|---|
| `rules` | one import line in `~/.claude/CLAUDE.md` that loads the kit's `CLAUDE.md`, then your `local.md` |
| `workers`, `workers-rules` | the eight named worker agents, and the rules for picking one |
| `worker-rules-hook` | a `SubagentStart` hook that hands your `worker-rules.md`, or the kit's lean-code rules, to every subagent |
| `lean-code-rules` | the same lean-code rules for your own sessions |
| `ledger-tools` | `todo.py` and `memory.py` over one SQLite database |
| `dch-bridge` | a silent status line that pushes the session's pull requests to dch |
| `ledger.stats` command | Ledger Stats, a Prosper window over `todo.py stats --json`: KPI tiles, a trends chart, per-tier and per-project tables (needs System Access for the kit and `ledger-tools` on) |
| `prs-hook` | feeds pull requests from `gh pr create` to `dch-bridge` |
| `monitors-tools` | `pr-watch.sh`, `gh-run-watch.sh` and `k8s-deploy-watch.sh` |
| `killguard-tools`, `-hook`, `-rules` | `safekill`, a hook denying `pkill` and `killall`, and the matching rules |
| `removeguard-tools`, `-hook`, `-rules` | `saferm`, a hook denying unsafe recursive deletes, and the matching rules |
| `prodguard-tools`, `-hook`, `-rules` | guarded cloud CLIs, a hook denying the ways around them, and the matching rules |
| `compactguard-hook`, `-rules` | a `PreCompact` hook that caps the summary, and the matching rules |
| `deny-system`, `deny-secrets`, `ask-destructive-gh`, `allow-readonly`, `allow-git`, `allow-build`, `allow-network` | permission rules in `~/.claude/settings.json`; rules you already have stay |
| `guard-examples` | example config files for the guards and recommended settings |
| `slack-tools` | `slack-say.py` |
| `prosper-rules` | how to use `ProsperApp ctl` |
| `mcpbridge-tools` | `mcpbridge`, a stdio MCP server that keeps a remote MCP server's calls alive across network switches |
| `spend-tools` | `ctxprobe.sh` and `usage-audit.py`, to measure a session's starting tokens and find what you never use; `spend-report.py`, the spend review over your transcripts, Prosper's ccpool files and the ledger |

Each piece is described in full in [REFERENCE.md](REFERENCE.md#what-it-changes).

## Requirements

- **Apps:** Prosper 2.175.0 or later, and Claude Code.
- **Shell tools:** `sh`, `bash`, `python3` and `awk` on PATH; `jq` when present.
  - Python scripts start `/usr/bin/python3` when the Command Line Tools or Xcode back it (skipping a pyenv, asdf or conda
    shim), and `python3` on PATH otherwise.
- **dch bridge:** `node`.
- **Monitors:** `gh` signed in, `jq` and `curl`, and `kubectl` for `k8s-deploy-watch.sh`.

## Customise

All in `~/.config/prosper-agentkit/`:

| File | What it does |
|---|---|
| `local.md` | your own instructions; read last, never overwritten by the kit |
| `worker-rules.md` | rules every worker gets at start (`worker-rules-hook`). Without it workers get the kit's lean-code rules; your file replaces them whole, and an empty file sends nothing |
| `prodguard.conf`, `removeguard.conf` | production targets and delete scopes; the examples are copied there for you |
| `hooks/<name>.pre`, `hooks/<name>.post` | your own script before or after any hook or tool |

- **Pieces:** switch any piece off on the install sheet; a piece that needs it goes off with it.
- **More:** settings, worker models and the recommended Claude Code settings are in
  [REFERENCE.md](REFERENCE.md#customise).

## Remove

Remove the kit in Prosper.

- **Taken out:** the import line, the hooks, the status line (your own comes back), the permission rules, its tools
  and the agent files it wrote.
- **Kept:** your `local.md`, your config files, the ledger database and the memory files.
  [REFERENCE.md](REFERENCE.md#remove) lists everything that stays.
