# Prosper Agent Kit

Rules from the prosper-agentkit kit follow; your own lines are in local.md, read last.

The kit's bin folder is `KIT_BIN={{kit_bin}}`. Your shell does not set `KIT_BIN`: where these rules write
`$KIT_BIN/<tool>`, run the tool by that folder's full path.

# Modern CLI Tools — Prefer These

Use over POSIX equivalents (gitignore-aware, faster, better defaults). POSIX only when portability required (CI, portable scripts).

- `fd` > `find` — flags: `-t f/d`, `-e ext`, `-H` hidden, `-I` no-ignore, `-x cmd {}`
- `rg` > `grep -r` — flags: `-l`, `-i`, `-w`, `-t ts`, `-g '!dist'`, `-A/-B/-C`, `-U` multiline. Never `cat | grep`, never `find | xargs grep`.
- `sd 're' 'repl' <files>` > `sed -i` — in-place by default, sane regex
- `ast-grep` (`sg`) for structural refactors > regex: `sg -p 'console.log($A)' -r 'logger.info($A)' -l ts --update-all`
- `jq` for JSON (`jaq` drop-in, ~2× faster, use >10 MB); `yq -p yaml -o json` for YAML/TOML/XML/CSV conversion
- `eza` > `ls` (`-l --git`, `-T` tree); `zoxide` (`z frag`) > `cd`; `fzf` interactive filter
- `bat` for viewing only — when piping use plain read or `bat -pp`; `delta` git pager; `difft` AST-aware diffs
- `hyperfine` for benchmarks; `gh`/`glab` for GitHub/GitLab; `gitleaks detect` before commits
- macOS: `gsed` for GNU `sed -i` semantics
- Extras: `tokei` LOC, `dust` du, `duf` df, `procs` ps, `gron` grep-able JSON, `mlr` CSV, `dasel` any-format query, `xh` curl, `choose` cut/awk, `htmlq` HTML extract, `glow` render MD, `ouch` archives, `zellij` tmux

# Long-Running Monitors — Use the Kit's Monitors in `$KIT_BIN`

Watching a PR, a rollout, or any slow external thing: launch one of these as a background shell
instead of a fresh poll loop or repeated status checks. They print only state transitions —
silence means nothing changed — and exit 0 on a terminal state. The Monitors section of the kit's
REFERENCE.md lists every script.

- `$KIT_BIN/pr-watch.sh <pr> [owner/repo] [local-repo-dir]`: a PR until MERGED/CLOSED; it reruns
  infrastructure failures itself, and exits 3 when the author owes the next action (named on its last line).
  `pr-watch.sh --audit [owner]` lists your open PRs that owe an action or have no live watcher.
- `$KIT_BIN/gh-run-watch.sh <run-id> [owner/repo]`: one GitHub Actions run to its end.
- `$KIT_BIN/k8s-deploy-watch.sh <context> <namespace> <deployment>`: a Deployment's ready/desired count.

Rules for monitoring anything, with or without these scripts:

- Never park a watcher in a session scratchpad — it is wiped between sessions and the watcher dies with it.
- Re-check watchers are alive every ~5 minutes and restart any that died; a dead monitor is the failure mode.
- An unreachable backend is not a transition: go quiet, announce the recovery.
- Open PRs ready for review, never `--draft`, other teams' repos included.
- Every open PR you authored has a live `pr-watch.sh`: re-arm them after a restart or compaction, and run
  `pr-watch.sh --audit` on every heartbeat tick and after a restart.
- Resolve review findings yourself: fix, or decline with evidence, then resolve the thread. Never park a PR on an
  operator question while it has open threads.
- A `pr-watch.sh` exit 3 is the next action, not a note. Never pipe a watcher through `tail`: a Monitor shows every line.
- Extend these scripts rather than writing one-off loops; a new kind of subject earns a new script next to them, documented in the kit's REFERENCE.md.

# Todos — Session List + the Ledger Database

Two surfaces, one set of ids: the session task list is the working queue; the ledger is the record
that survives the session. The ledger is ONE SQLite database for every project, written only
through `$KIT_BIN/todo.py`; no file is a ledger. Write as work happens, not at the end — a crashed
session must lose nothing.

## Which ledger

- One project per queue: `todo.py <command> <project> …` over one database (`ledger.sqlite3` in the
  kit's state folder; `LEDGER_DB` names another). `todo.py projects` lists every project with its
  paths and entry count.
- Decided once, at session start: **session name first** (a project of that name exists → use it),
  else **start directory** (`CLAUDE_PROJECT_DIR`, equivalently stdin `workspace.project_dir`)
  matched against project names and their `paths` column (one path per line, for start dirs
  carrying nothing of the project name). Not the current working directory — a mid-session `cd`
  changes nothing. Unnamed sessions get auto-titled and those titles drift, so they never mint a
  project.
- A reused session name means "continue that ledger", deliberately. If it is genuinely a different
  project, say so and start a project under a new name. Never merge unrelated queues; never drop an
  old one.
- An issue board shared with QA, if you keep one, is a SEPARATE database with its own script and its
  own vocabulary. Rows there, entries here.

## Entry format

- Ids are stable — never renumber, and never reuse an id for different work (two items under one id
  hide whichever closed); a wrong id is closed with the reason, not deleted. The primary key allows
  one row per id, so an update can only go INSIDE its entry.
- `status` leads and is one of `OPEN` / `IN PROGRESS` / `DONE` / `DROPPED` / `PARKED`, written with
  `todo.py set-status <project> <id> --status <S> --note '<why>' --expect-version <v>`. It appends a
  dated status line to the entry's prose AND re-derives the column from it: the history stays and
  the row never disagrees with the record.
- `IN PROGRESS` means a worker or a review is live now: write it when picking an item up, not when
  finishing, and update the session task list under the same id in the same breath.
- Progress is appended, never overwritten: `todo.py append <project> <id> '<what happened>' --kind
  round --expect-version <v>` per meaningful step (it numbers and dates the round). A close records
  why it closed and what came out — "Done" alone is not a close.
- **The merge is the close.** When the PR merges (`pr-watch.sh` exits MERGED, or you see it merge),
  run `set-status --status DONE --note '<what came out of it>' --pr <url> [--pr <url>]` in that same action, before
  moving on: nothing else makes closing the next action, so a landed entry would keep reading IN
  PROGRESS (todo.py also reads PR URLs from the note; `--pr` is for one the note does not name). Work with no PR closes on its own terminal event (the deploy ran, the operator answered,
  the doc shipped).
- `todo.py set-parallel <project> <id> 'FORKABLE — <why nothing overlaps>'` or
  `'BLOCKED behind #414 and #399 — <what they share>'`. Ids before the em dash are the blockers and
  become the `blocked_by` column. FORKABLE is a claim against every other entry that could be live
  at the same moment: disjoint files, disjoint subsystems, no ordering. An entry sharing files with
  a sibling is NOT FORKABLE — name the sibling instead.
- A worker's claim, `set-status --status 'IN PROGRESS' --fork --worker <model>/<effort>`, puts the
  entry in the `fork` lane and is the only place a worker's tier is recorded; only `set-status` takes
  `--fork`. Untagged means the main lane.
- One database, many writers: every mutating command takes `--expect-version <v>` and exits 3 with
  `{"error":"version_conflict","current":…}` when someone else wrote first — re-read with `todo.py
  get` and reapply. The writer in the append-only `events` table is the session's name
  (`DCH_SESSION`, nothing to export); `LEDGER_ACTOR=<name>` or `--actor <name>` overrides it, for a
  worker or outside dch.
- Order is the work order (`ord`): `todo.py list <project>` is the live queue (add `--all` for the
  closed ones), top is next. Reorder with `todo.py move <project> <id> (--before <id> | --after <id>
  | --top | --bottom) --note '<why>' --expect-version <v>`: it changes only that entry's place and
  appends the reason as a `**Move, <date>**` line that no status rule reads.
- `todo.py export-md <project>` renders a ledger as markdown for reading whole or diffing. It is a
  report, never an input — nothing reads a ledger from a file.
- Questions for the operator are rows in the same database: `todo.py ask <project> OQ-<n> --title
  '<question>' --body '<what it blocks>'`, answered with `todo.py rule <project> OQ-<n> '<ruling>'`.
  `todo.py questions <project> --status OPEN` is the outstanding list.

## The list is the plan

Nothing is removed from the list without discussing it with the user: entries are only added and
reprioritised, and every one stays planned and pending until it is done.

- Sweep with `todo.py plan <project>` at session start, on every heartbeat tick and before any
  status answer. It prints every entry that is not closed, in work order, flags what has gone quiet
  (`[IDLE]`, `[UNBLOCKED]`, parked entries with their condition, recent drops) and ends with what to
  do about each flag. Act on the flags in that tick. A status answer is built from its lines, one
  entry per line, never from memory of the session.
- `DROPPED` needs the operator's own words: `set-status --status DROPPED --operator '<quote>'`; the
  tool refuses without them, and folding an entry into another is a drop of the first. Parking is
  the agent's call, with the un-park condition in the note; the sweep reopens it when that passes.
- A phase that ships on its own is its own entry: `todo.py create … --after <parent>` puts it right
  after its parent. A phase named only inside a spec or another entry's text is not planned.
- Work order is the operator's priority: taking a later entry ahead of an earlier unblocked one is
  said to the operator, with the reason. A priority change is made with `todo.py move`, with the
  operator's words in `--note`, never only as a note.

## Supervisor / worker protocol

- The main session supervises only — dispatch, review, unblocking, ledger upkeep, talking to the
  user. Workers implement, spawned via the Agent tool with the ledger id, the project name,
  `KIT_BIN=` and the bin folder's full path (agent files say `$KIT_BIN`), and the full entry text
  from `todo.py get <project> <id>` in the prompt (a worker inherits no conversation context —
  restate every binding constraint).
- Message another session only with work, a verdict or a question it must answer; never an
  acknowledgement, thanks or agreement alone. Batch updates for the same session into one message.
- Workers run without this file and without any project `CLAUDE.md` (`omitClaudeMd: true` in every
  `~/.claude/agents/worker-*.md`: about 6k tokens off every worker call). Their rules — ledger
  writes, deliverable file, handoff, shell, kill and background-job rules, worktrees, PR links — are
  in the agent file, so the prompt does not restate them, and the worker reads the project's memory
  index itself as its first step. A rule added here that a worker must follow goes into those agent
  files too; a rule shared by all workers can go in `worker-rules.md` in the kit's config folder
  instead (the `worker-rules-hook` piece hands it to each subagent at start); anything specific to
  the entry goes in the prompt.
- An unblocked entry is the authorization — dispatch without asking. Before spawning, re-read the
  entry and skip any already IN PROGRESS in the `fork` lane; the worker claims the entry itself
  before starting. Never dispatch a BLOCKED entry.
- Concurrency: max 6 live workers. Unclaimed FORKABLE entries fan out to that cap; everything else
  serializes in ledger order — still by workers, never the main lane. At dispatch, re-check
  FORKABLE pairwise and against live workers (annotations go stale): entries about to touch the
  same files or subsystem don’t launch together — the earlier one launches, the other waits and
  gets its Parallel line corrected. A worker colliding mid-flight with another is stopped and
  re-dispatched after the other closes.
- Review gate: a worker report creates a review task under the same id — the supervisor’s next
  action, holding every new launch until the review round lands in the ledger. The review is a
  critic’s pass: read the diff end to end, run the tests, check every report claim against
  evidence on disk (the report is a lead, never proof), and check against the entry’s
  done-condition plus what it should have delivered even unstated (tests, guards, scope quietly
  narrowed). Judge a dead worker by its output file, not its stall message. Pass → close stands;
  record every gate verdict as `todo.py append <project> <id> '<findings>' --kind review --verdict pass|fail --expect-version <v>`:
  one review event per gate (QA or a second reviewer concurring is a round, not a second verdict);
  the tier defaults to the entry's last dispatch, give `--tier <model>/<effort>` when the review
  covers another worker and `--tier main` for your own work. A conditional pass ("pass with
  required changes") is a fail;
  when the deliverable is a PR, arm `pr-watch.sh` through the Monitor tool in the same action (a
  worker’s backgrounded processes die when it reports; TaskStop the watcher on merge/close). Fail →
  entry stays IN PROGRESS; re-dispatch the same entry (after the `--verdict fail` review event; the new dispatch note names the new tier) with the critique, the missing evidence, and
  the narrowed search embedded in the prompt — to a fresh worker that reads the previous worker's
  deliverable file. SendMessage to the same worker only within 5 minutes of its report: its prompt
  cache lasts 5 minutes, and waking it later re-writes its whole context, seven times the cost of a
  fresh start.
- **A worker stays short and hands off.** Every call re-reads the worker's whole context, so its
  cost grows with the square of its length (workers past 200k tokens of context were 60% of worker
  spend). Size an entry so one worker finishes it in about 60 tool calls, and split it before
  dispatch when it will not. Past that the worker reports `HANDOFF` with its deliverable file (its
  agent file says how); dispatch a fresh worker for the remainder under the same entry. The review
  gate applies to the last worker's report, which covers the whole entry.
- **A worker returns a pointer, not a payload**: the verdict, its deliverable file's path and only
  the evidence the review needs to start; read the file when the review actually needs it. Every
  report is read whole into the supervisor's context, so at the worker cap long reports — not queue
  length — drive constant compaction, and a compacting supervisor is not reviewing.
- Every worker and subagent is a named agent `worker-<model>-<effort>` from `~/.claude/agents/`
  (the `workers-rules` piece lists them and why) — never `general-purpose`, never a bare `model`
  parameter. The supervising brain stays on the session model (`/model` shows it). The worker’s `description` leads with its tier in brackets, then the ledger project and id —
  `[opus/high] <project> #<id> Extract the billing module` —
  so the panel shows the tier and spend-report ties the worker's tokens to the entry. Confirm the pin
  took with `/tasks`: the row shows model and effort.
- Model choice — a trial, judged on cost per closed entry and on how often a review fails. Workers
  are half of all spend, and Sonnet 5.5 costs half of Opus 5.5 per token. The tiers are in the
  `workers-rules` piece; on top of it:
  - `worker-haiku`: a wrong answer must be cheap to spot; it never makes the judgment call. Keep the
    task small: past 100k tokens of prompt Haiku costs five times more per token.
  - A Sonnet worker whose review fails is re-dispatched to `worker-opus-medium`, not to Sonnet at a
    higher effort: effort does not add skill the model lacks.
  - Effort is how much tracing the entry needs. `medium` is the first dispatch for every entry,
    multi-file changes and debugging included (it costs about 70% of `high`); `low` only when the
    entry is single-file, fully specified and its diff is checkable at a glance; `high` is the redo
    after a `medium` worker's review failed, with the critique and a sharper prompt, never a first
    pick; `xhigh` / `max` only for an extreme, critical entry — rare, slow and token-heavy, never a
    first pick. A failed tier is recorded by the `--verdict fail` review event (its `--tier`).
  - Splitting the task beats raising effort when the entry is doing two things.
- Every dispatch appends a note to the entry:
  `todo.py append <project> <id> 'worker spawned via Agent, subagent_type: worker-<model>-<effort>
  (model: <model>, effort: <effort>).' --kind dispatch --expect-version <v>`
- **Stop what is done, remove what is unused.**
  - A worker whose review round has landed, or whose entry has closed, is stopped with TaskStop in the
    same action. A reported worker is kept only inside the 5-minute SendMessage window above.
  - A finished worker's worktrees go too: every scratch worktree when it reports, and the PR's own
    worktree when the entry closes. Remove each with `git worktree remove`, never with prune.
  - Never move the session into a worktree: a top-level `cd` there carries into later calls. Work in
    one with `git -C <wt>`, absolute paths, or a subshell `( cd <wt> && … )`, and remove it from
    outside. If a removed worktree's folder comes back, the session was still inside it; leave that
    folder and tell the operator.
  - On every heartbeat tick, run `ListAgents` and `git worktree list`. Stop any completed worker that
    is still listed, and remove any worktree of yours that no live entry owns. The agent panel and the
    shared disk are both finite.
  - This applies to every session, supervisor or QA alike: a session stops its own idle subagents and
    removes its own worktrees. It never touches another session's.

# Memory — SQLite via `memory.py`

Memory lives in the same database as the ledger and is written ONLY through `$KIT_BIN/memory.py`. The files
under `~/.claude/projects/<slug>/memory/` are generated mirrors: the harness loads `MEMORY.md` off
disk and recalls the bodies from there, so they must keep existing, but they are output. Never hand-edit
one — the next export overwrites it and the change is gone.
Claude Code's built-in memory instructions tell a session to write memory files directly; in a kit
session that is overridden: write through `memory.py` only (a file written directly has no row and is
archived by the next export).

- Write: `memory.py write <slug> <name> --description '<hook>' --type <user|feedback|project|reference>
  --body-file <file>` (or `--body`, or stdin). The row is written and that one file is regenerated in
  the same action, so the mirror is never behind the database.
- The index is a memory like any other, named `MEMORY`: rewrite it with `memory.py write <slug>
  MEMORY --body-file <file>`. One line per entry, `- [Title](file.md) — hook`, under 17 KB.
- Read: `memory.py get <slug> <name>` (add `--raw` for the file as written) and `memory.py search
  '<text>' [--slug <slug>]` across names, descriptions and bodies.
- `memory.py export <dir>` regenerates a whole directory from the database, `--check` reports what
  would change and writes nothing. A file with no row is moved to `<slug>/memory-archive/`, never
  deleted — and neither is anything else: retiring a memory is `memory.py delete`, which archives
  the file.
- The bytes of every imported memory are stored as written, so an export is byte-identical until
  something actually changes. A no-body pointer (frontmatter, no body) stays a pointer.

# AI Reviewer

Only a code push or a comment triggers it — answering a review thread does not, so post the comment too.

Resolve review threads yourself, AI or human, without asking: once a reply settles a thread with evidence or a fix is
pushed, resolve it (GraphQL `resolveReviewThread`). An open thread blocks the merge, and the operator does not want to be
the round-trip. This covers resolving only; arming and merging keep their own gates.

# Referring to PRs, Issues and MRs

Never hand back a bare number. Every mention of a pull request, issue, or merge request in
user-facing text carries its full URL, so it is one click away:

- `[#12794](https://example.com/owner/repo/pull/12794)` — not `12794`, not `PR #12794`. The address
  is your GitHub web address (the kit's `github_url` setting) and the pull request's owner and repo.
- Applies to every surface: prose, tables, bullet lists, status lines, reports of monitor output.
- Same rule for GitLab MRs, Jira issues, and Notion pages — link the identifier, always.
- Repeated mentions of the same PR in one reply need the link once, on the first mention.

# Posting in Slack — Use `slack-say.py`

Every Slack message an agent sends (DM, thread reply, channel post) is built with
`$KIT_BIN/slack-say.py [--title TEXT] LINE...` and sent with its output verbatim, including
the `> ⠀` spacer lines (a braille blank; Slack drops a truly empty quoted line).

- In a DM, never reply in a thread: post a new top-level message (no `thread_ts`), even when answering
  a specific earlier message. Threads stay for channels.
- English, written as the agent speaking, never as the operator. No sign-off naming the operator:
  the header and Slack's "Sent using @Claude" footer already say who wrote it.
- One fact per line, no repeats, nothing the reader does not need. Prefixes `data:` 📊, `done:` ✅,
  `ask:` ❓, `warn:` ⚠️, `fix:` 🔧, `link:` 🔗 add a marker only where it carries meaning. The tool
  refuses more than 3 markers, more than 6 lines, or a repeated line; cut the text, never route
  around it.
- No `*x*` emphasis (it renders italic). The tool puts money and numbers with a unit in backticks;
  dates and plain counts stay plain. Write PRs as `repo#N` (or `owner/repo#N`) and Jira
  keys as `KEY-N` (the projects in the kit's `jira_projects` setting): the tool turns them into links and refuses a bare `#N`.

@{{kit_config}}/local.md
