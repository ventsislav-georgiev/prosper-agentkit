# Prosper Agent Kit: reference

Every piece, setting and file in detail. For how the pieces work together, start with [README.md](README.md).

Guard hooks, safe defaults and named workers for Claude Code, installed and removed by Prosper as one kit. Each part is its own
piece: you can switch any piece off on the install sheet and keep the rest.

## What it changes

- `rules`: adds one import line to your `~/.claude/CLAUDE.md` that loads this kit's `CLAUDE.md`: the whole working
  rule set (modern CLI tools, monitors, the ledger and memory through `todo.py` and `memory.py`, the supervisor and
  worker protocol, PR links, Slack messages through `slack-say.py`, killguard), with every tool path pointing at the
  kit's bin folder. It ends by importing your own `local.md` from the kit's config folder. It stays on while any other instruction piece is on.
- `killguard-tools`: the `safekill` command in the kit's bin folder. `safekill [-n] [-s SIG] <pattern>` lists your
  processes whose command line matches, then signals them by pid. It signals nothing when the pattern is under 6
  characters or only digits, or when any match is a Claude Code or dch session; `-n` only lists.
- `killguard-hook`: a `PreToolUse` hook for `Bash` and `Monitor` that denies `pkill` and `killall` in any command
  position. Needs `killguard-tools`.
- `killguard-rules`: instruction text: kill the pid you recorded, use `safekill` for a pattern. Needs `killguard-hook`.
- `removeguard-tools`: the `saferm` command in the kit's bin folder. `saferm [-n] [-f] [-g] <path>...` deletes
  recursively only below allowed scratch prefixes, and refuses a symlinked path, a guarded folder, a git repo or
  worktree, and more than 5000 entries without `-f`. One refusal deletes nothing.
- `removeguard-hook`: a `PreToolUse` hook for `Bash` and `Monitor` that denies a recursive delete (`rm -r`,
  `find -delete`, `find -exec rm -r`, `xargs rm -r`) whose target is a bare or inherited variable, a command
  substitution, a top-level or guarded folder, a session socket folder, or a git repo or worktree. Ordinary deletes
  pass. Needs `removeguard-tools`.
- `removeguard-rules`: instruction text for safe recursive deletes. Needs `removeguard-hook`.
- `prodguard-tools`: guarded `gcloud`, `aws`, `kubectl`, `terraform` and `tofu` in the kit's bin folder. Each runs the
  next real binary on your PATH. Reads pass; a command that is not provably read-only and targets production (what
  your `prodguard.conf` lists) is refused with exit 77, and so is one whose target cannot be told. With no
  `prodguard.conf` nothing is production: every command passes and prints one line saying so.
- `prodguard-hook`: a `PreToolUse` hook for `Bash` and `Monitor` that denies the ways around the guarded copies: the
  real binary by its path, a `which -a` or `command -p` lookup, a `PATH` that puts a real binary first, and a tool
  run by name when the session finds the real binary first (the kit's bin folder is at the end of PATH, so with the
  real CLI installed this is the usual case). Each deny names the guarded copy to use instead. Setting the production
  override, or running a cloud CLI on a pseudo-terminal, is denied as a stop. Needs `prodguard-tools`.
- `prodguard-rules`: instruction text: use the guarded copies, never the override, hand a refused production write to
  you. Needs `prodguard-hook`.
- `compactguard-hook`: a `PreCompact` hook that keeps the compaction summary from growing without bound. When the
  previous summary is over 50,000 characters it saves it to a `compact-archive` folder next to the session transcript
  and asks for a new one of at most 35,000 characters that keeps open work in full and points at the archive for
  finished work. Under the budget it prints nothing; it never blocks a compaction. `compactguard.py --test` checks it.
- `compactguard-rules`: instruction text: follow those summary instructions and search the archive before reopening
  finished work. Needs `compactguard-hook`.
- `worker-rules-hook`: a `SubagentStart` hook that hands `worker-rules.md` from the kit's config folder
  (`~/.config/prosper-agentkit/worker-rules.md`) to every subagent at start, as added context. Workers run without the
  CLAUDE.md files, so this is the one place for rules all of them share. With no file it sends the kit's
  `rules/lean-code.md` (the `lean-code-rules` text); your file replaces it whole, never merged. An empty or
  whitespace-only file sends nothing, which is how to switch the default off for workers. It sends at most 16 KB, cut
  at a line end, and never blocks a subagent.
- `lean-code-rules`: instruction text from `rules/lean-code.md`, condensed from the ponytail plugin: the smallest change
  that fully solves the task, reuse before new code, no unasked-for abstraction, a check for new logic, and a closing
  line on what was skipped. It is the same file the `worker-rules-hook` sends by default, so main sessions and workers
  get one text without a `local.md` import.
- `ledger-tools`: the `todo.py` and `memory.py` commands in the kit's bin folder. `todo.py` keeps per-project work
  ledgers (entries, status lines, rounds, operator questions) in one SQLite database; every write takes
  `--expect-version` and refuses a stale one with exit 3, and needs a writer name (`--actor` or `LEDGER_ACTOR`).
  `memory.py` keeps Claude Code memory notes in the same database and rewrites the matching file under
  `~/.claude/projects/<project>/memory/` on every write. The database is `ledger.sqlite3` in the kit's state folder;
  set `LEDGER_DB` to a file path to use another one. Run either with `--help` for the commands.
- `monitors-tools`: three watchers in the kit's bin folder, made to run in the background and left alone. Each prints
  only state changes, so silence means nothing changed, and each says so when its backend is unreachable or its
  subject does not exist rather than going quiet. See Monitors below.
- `slack-tools`: the `slack-say.py` command in the kit's bin folder. `slack-say.py [--title TEXT] LINE...` prints a
  short Slack message in a fixed style for Claude to send with its Slack tool; it never sends anything itself.
  `data:`, `done:`, `ask:`, `warn:`, `fix:` and `link:` line markers add an emoji, `owner/repo#N` becomes a pull
  request link once `github_url` is set, money and numbers with a unit go in backticks, and it refuses a bare `#N`, a repeated line, more
  than 6 lines or more than 3 markers. `--selftest` checks it.
- `mcpbridge-tools`: the `mcpbridge` command in the kit's bin folder, a stdio MCP server that relays to a remote
  streamable-HTTP MCP server and survives network switches. `mcpbridge <url> [--deadline SECONDS]` (default 120)
  holds each call while the server is unreachable (connection errors, DNS, timeouts, HTTP 404, 502, 503 and 504) and
  retries it with a 1, 2, 4, up to 10 s backoff, re-initialising the MCP session from the client's cached
  `initialize` once the server is back. A call still failing at the deadline gets a JSON-RPC error (`-32000`) and the
  next call is served as normal. A `tools/call` that may already have reached the server (read timeout, stream cut
  mid-response, HTTP 502 or 504) is answered with an error and not retried. Auth is MCP OAuth 2.1 (protected-resource
  metadata, dynamic client registration, PKCE S256, the RFC 8707 `resource`): the first 401 opens a browser and holds
  the call up to 300 s, later tokens are refreshed without asking. Tokens live in
  `~/.config/mcpbridge/<origin>.json` (folder 0700, file 0600, atomic writes, a lock file shared by every running
  bridge) and never go to logs, argv or URLs. `mcpbridge --logout <url>` deletes them. Use it as an MCP server entry:
  `"command": "<kit bin>/mcpbridge", "args": ["https://example.com/mcp"]`. If the first login takes longer than
  Claude Code's MCP startup timeout, reconnect with `/mcp` once the browser says it is done, or start Claude Code
  once with `MCP_TIMEOUT=300000`.
- `spend-tools`: two commands in the kit's bin folder for trimming what a session pays at start (see Startup context
  in README.md). `ctxprobe.sh [dir] [claude args...]` runs one `claude -p` with a one-word reply in `dir` (default: a
  fresh empty temp folder, removed after) and prints its input plus cache read plus cache write tokens; extra args
  measure a variant (`--settings '{...}'`, `--disable-slash-commands`, `--strict-mcp-config`). It needs `claude` and `jq`, makes one small real model call, and exits 1 when the reply has
  no usage. `usage-audit.py [days] [--root DIR]` reads the transcripts changed in the last `days` (default 14) under
  `--root`, else `$CLAUDE_CONFIG_DIR/projects`, else `~/.claude/projects`, and prints built-in tool calls, MCP calls
  per server and per project folder, and Skill calls. It reads only and skips lines that are not JSON.
  `spend-report.py [report] START [END]` is the spend review (see Spend review in README.md); its subcommands are
  `expiry`, `byproject`, `tokens`, `ctxsize`, `revive`, `points`, `accounts`, `fit`, `compact`, `supervisor`, `floor`
  and `selftest`, and `spend-report.py` alone prints them. Its modules live in `lib/spend/`. It reads transcripts from
  `$CLAUDE_CONFIG_DIR/projects` (else `~/.claude/projects`), Prosper's ccpool files from `$PROSPER_CCPOOL_DIR` (else
  `~/Library/Application Support/Prosper/ccpool`) and the ledger as `todo.py` finds it (`LEDGER_DB` wins), opened
  read-only; a missing ledger is reported, never created. `rules/daily-review-prompt.md` is a daily review prompt to
  give a spend session.
- `hud`: Claude Code's status line, run with `node` (22.13 or later, for `node:sqlite`). It lists the session's open
  tasks and the ledger entries of the current project, read from the kit's ledger database (`LEDGER_DB` wins, as for
  `todo.py`), with a live-worker count; per-item rows and counts are off until `OMC_HUD_TASK_ROWS=1` or
  `OMC_HUD_TASK_COUNTS=1`. With the oh-my-claudecode HUD installed (`omc-hud.mjs` in Claude Code's `hud` folder) it
  restyles that HUD's line and adds the panel below it; without it, it prints the model, effort and context use. Its
  own files (pull request state, the last `dch --meta` push) live in `hud/` in the kit's state folder. It replaces your
  status line while it is on; Remove puts yours back.
- `prs-hook`: a `PostToolUse` hook for `Bash` that feeds the `hud` pull request panel. When a `gh pr create` command
  finishes, each pull request URL (https, any host, then owner, repo, `pull` and the number) it printed is added to the
  session's list; anything else adds nothing. It never blocks and prints nothing. Needs `hud`. A session with no kit PR state takes its list once from the pre-kit HUD file (`~/.claude/hud/prs-<session>.json`) and never changes that file.
- `guard-examples`: copies `removeguard.conf.example`, `prodguard.conf.example` and
  `settings-recommended.example.json` into the kit's config folder once. They are examples only: the guards read
  `removeguard.conf` and `prodguard.conf`, never the examples, and nothing reads the settings example (see
  Recommended settings below).
- `workers`: installs eight agent files into `~/.claude/agents/`: `worker-haiku.md` (read-only), `worker-sonnet-low.md`,
  `worker-sonnet-medium.md` and `worker-opus-low.md`, `-medium`, `-high`, `-xhigh` and `-max`. Each is the
  general-purpose agent with its model, effort and tools pinned. They run without the CLAUDE.md files and call the
  kit's tools as `$KIT_BIN/<tool>`; the prompt that spawns one names the folder (`KIT_BIN=<path>`). If a file of the same
  name is already there and the kit did not write it, it is left alone and the piece reports it as refused.
- `workers-rules`: instruction text that tells Claude to hand work to those named workers and how to pick a tier.
  Needs `workers`: switching `workers` off switches this off too.
- `prosper-rules`: instruction text for Prosper's control CLI, `ProsperApp ctl` (the binary inside Prosper.app): run
  `describe` first, then the commands (start, read, talk to or resume agent sessions, X-ray search, layouts, settings).
  Changing commands need Prosper's Settings switch "Let agents control Prosper" on; reads never do. The kit has no
  skill piece kind, so this is a rules piece; `CLAUDE.md` and every worker agent file carry a short pointer to it.
- `deny-system`: 27 deny rules for disk tools, privilege tools and recursive deletes of top-level folders.
- `deny-secrets`: 42 deny rules: 41 keep Claude from reading or editing secret files (keys, cloud and tool
  credentials, `.env` files) and one denies the `Artifact` tool.
- `ask-destructive-gh`: asks before `gh repo delete` and `gh release delete`.
- `allow-readonly`: 17 allow rules for reading and read-only tools (`git status`, `git diff`, `git log` and similar).
- `allow-git`: 15 allow rules for local git writes (`git add`, `git commit`, `git switch` and similar) and `gh pr merge`.
- `allow-build`: 7 allow rules for build and test commands (`swift build`, `swift test`, `go test` and similar).
- `allow-network`: 4 allow rules for `curl`, `wget`, `ssh` and `kubectl`.

The three guard hooks are marked `on_error = "deny"`: when Prosper's kit runner cannot run one (bad arguments, `kit.env` missing or unsafe, input over 1 MiB, a failing `.pre` hook, a missing script), the tool call is blocked rather than let through. This needs Prosper 2.175.0-beta.50 or later.

If a broken runner state blocks every `Bash` and `Monitor` call (each refusal ends with "blocked: this deny guard fails
closed"), an agent's `Bash` is blocked too, so its only way out is `Edit` of `~/.claude/settings.json` (remove that
hook group). You can run the kit's Repair (Settings, Agent Kits, or `ProsperApp ctl kits.repair` from your own
Terminal), or switch the failing guard piece off there (`ProsperApp ctl kits.apply` with it in `off`).

The guards are a seatbelt, not a boundary: they read the command text, so `eval`, `bash -c "$x"`, a script file or a
delete written in another language get through. The removeguard hook allows a command it fails to parse rather than
block every call. prodguard does not see `bq`, `gsutil`, `helm` or `k9s`, AWS keys whose profile names no account, or a
bucket-only target; your cloud permissions are the boundary. Its override needs a person typing `production` in their
own terminal, outside any agent session.

Permission rules are added to `permissions.allow`, `permissions.deny` and `permissions.ask` in
`~/.claude/settings.json`; rules you already have stay.

### Monitors

Start them as background commands (Claude Code's `Monitor` tool turns each printed line into a notification). They
poll every 5 minutes or less and exit when the subject reaches an end state.

- `pr-watch.sh <pr-number|url> [owner/repo] [local-repo-dir]`: a pull request's state, merge state, review decision,
  unresolved review threads and failing or pending checks, one line per change. It reruns jobs that failed without a
  failed step (runner or network trouble), holds while the status page in `actions_status_url` reports an Actions
  outage, and with a local repo folder
  pushes an empty commit as the last retrigger. It merges the pull request once it is approved, green and has no
  requested reviewer (`AUTOMERGE=0` only watches; `MERGE_METHOD=merge|rebase|squash`, default `squash`). It exits 0
  when the pull request is merged or closed, and 3 when only the author can move it (new review comments on an
  unresolved thread, a merge conflict, changes requested), so the exit is the signal. A newer watch of the same pull
  request stops the older one.
- `gh-run-watch.sh <run-id> [owner/repo]` or `gh-run-watch.sh --sha <sha> --workflow <name> [owner/repo]`: one
  GitHub Actions run to its end, with each job's result and the failed step names. The `--sha` form waits for the
  run to be created. Without `owner/repo` it uses the current folder's repo, and it refuses to start (exit 2) when
  there is none, or when the commit or run does not exist. Exits 0 on success, 1 on any other result.
- `k8s-deploy-watch.sh <kube-context> <namespace> <deployment>`: a Deployment's ready count, image and pods (name and
  12 characters of the image digest). It refuses to start (exit 2) when the Deployment does not exist, stays quiet
  while the cluster is unreachable and says when it is back, and reports a Deployment deleted mid-watch.
  `K8S_DEPLOY_WATCH_INTERVAL` sets the poll interval in seconds (default 300).

## Requirements

- Prosper 2.175.0 or later.
- Claude Code.
- `sh`, `bash`, `python3` and `awk` on PATH. The hooks use `jq` when it is on PATH and `python3` otherwise. Every kit
  script starts Python through `lib/python3`: `/usr/bin/python3 -I` when the Command Line Tools or Xcode back it
  (without them it is a stub that opens an install prompt), else `python3 -I` on PATH. A pyenv, asdf or conda shim
  on PATH adds about 0.3 s to every start, so the hooks skip it when they can.
- For the `hud` status line: `node` 22.13 or later on PATH.
- For the monitors: `gh` signed in, `jq` and `curl` (`pr-watch.sh`, `gh-run-watch.sh`) and `kubectl`
  (`k8s-deploy-watch.sh`).

## Customise

- Put your own instructions in `local.md` in the kit's config folder (`~/.config/prosper-agentkit/local.md`). It is
  read last and the kit never overwrites it.
- Rules every worker should get go in `worker-rules.md` in the same folder; the `worker-rules-hook` piece hands them
  to each subagent at start (workers do not read `local.md`). Without the file workers get the kit's lean-code rules;
  your file replaces them whole, and an empty file sends nothing. For main sessions, switch `lean-code-rules` off.
- To move a worker to a newer model, edit the `model:` line of its agent file in `~/.claude/agents/`. The file is then
  yours: Prosper keeps an edited file and reports it instead of replacing it.
- removeguard: copy `removeguard.conf.example` to `removeguard.conf` in the kit's config folder
  (`~/.config/prosper-agentkit/`) and edit it. `[allow]` lists the prefixes `saferm` may delete below and replaces the
  default (Claude Code session scratchpads); `[guard]` adds folders the hook and `saferm` refuse. Your home folder,
  `~/.claude` and the system temp folders are always guarded. Outside the kit the tools read
  `~/.config/removeguard/config` instead, and so do they under the kit when `removeguard.conf` is missing.
- prodguard: copy `prodguard.conf.example` to `prodguard.conf` in the kit's config folder and list your production
  GCP projects and project numbers, cluster endpoints, AWS profiles and account ids, and terraform workspaces, one per
  line. A `*` in an entry stands for any run of letters, digits and `-`, so `*-production` covers every name ending in
  `-production`. If you run your own guarded shims, list their absolute folders under `[trusted-shim-dirs]`: a cloud
  CLI found there first on PATH counts as guarded, so the hook allows it by name. Outside the kit prodguard reads
  `~/.config/prodguard/prodguard.conf`.
- Kit settings on the install sheet: `ai_reviewer` is the login of a review bot that re-reviews only on a push or an
  `/ai-review` comment, so `pr-watch.sh` names that comment instead of a re-review request. `actions_status_url` is
  the GitHub status page's `components.json` API address; with it `pr-watch.sh` holds retriggers during an Actions
  outage. `github_url` is the GitHub web address `slack-say.py` links pull requests to, and `github_owner` lets it
  link `repo#N` without an owner; `jira_url` and `jira_projects` (comma-separated keys) turn those Jira
  keys into links; `slack_header` is the message's first line. `hud_default_model` and `hud_default_effort` are
  the model name and effort your sessions should run; the `hud` status line shows any other one as a badge.
  `spend_small_accounts` (comma-separated labels) names the accounts on a smaller plan, which
  `spend-report.py points` and `accounts` leave out of the account-week totals. All are
  empty or a plain default until you set them.
- Switch off any piece you do not want on the install sheet; a piece that needs it goes off with it.
- Run your own script before or after any hook or tool: put an executable file named `<name>.pre` or `<name>.post` in
  `~/.config/prosper-agentkit/hooks/`. `<name>` is the piece id for a hook or the status line (`killguard-hook`,
  `removeguard-hook`, `prodguard-hook`, `compactguard-hook`, `worker-rules-hook`, `prs-hook`, `hud`) and the command name for a tool (`safekill`,
  `saferm`, `gcloud`, `aws`, `kubectl`, `terraform`, `tofu`, `todo.py`, `memory.py`, `pr-watch.sh`, `gh-run-watch.sh`, `k8s-deploy-watch.sh`, `slack-say.py`, `ctxprobe.sh`, `usage-audit.py`, `spend-report.py`). A `.pre`
  that exits non-zero stops the run (exit 2 blocks the tool call for a hook); a `.post` sees
  `KIT_STATUS` and cannot change the output. Prosper runs only a regular file you own that is not group- or
  world-writable.

### Recommended settings

A kit cannot write `env` or other settings keys, so these stay a suggestion you apply by hand. The same block is in
`settings-recommended.example.json` in the kit's config folder. To use it, merge it into `~/.claude/settings.json`
(keep your own keys):

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
    "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
    "DISABLE_TELEMETRY_OFF": "1",
    "CLAUDE_CODE_ENABLE_AUTO_MODE": "1",
    "CLAUDE_AUTO_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT": "1",
    "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
    "CLAUDE_CODE_DISABLE_AGENT_VIEW": "1",
    "ENABLE_TOOL_SEARCH": "true",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"
  },
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "deny": [
      "DesignSync",
      "EnterPlanMode",
      "EnterWorktree",
      "ExitPlanMode",
      "ExitWorktree",
      "NotebookEdit",
      "PublishPlugin",
      "RemoteTrigger",
      "ReportFindings",
      "ShareOnboardingGuide",
      "Workflow"
    ]
  }
}
```

The first five turn off telemetry, error reports, feedback surveys and other non-essential calls. The next seven set
the working style: auto mode, background tasks, the short system prompt, no git instructions, no agent view, tool
search on and claude.ai MCP servers off. The last one sets the auto-compact window: 250000 compacted about twice as often, 300000 is the chosen balance. `disableBypassPermissionsMode`
keeps the bypass-permissions mode from being turned on, so the guards and deny rules always apply. The `deny` list drops built-in tools few sessions call, about 3.4k fewer tokens at every
session start; `EnterPlanMode` and `ExitPlanMode` take plan mode with them. README.md (Startup context) says what each
tool is for: keep the ones you use.

## Remove

Remove the kit in Prosper. It takes out the import line, the hooks, the status line (your own comes back), the
permission rules it added, the tools in its bin folder and the agent files it wrote. Your `local.md` stays, and so do
the three `.example` files, your `removeguard.conf` and `prodguard.conf`, the ledger database and the HUD's files in
the kit's state folder, the compaction archives, the memory files `memory.py` wrote, the tokens `mcpbridge` stored in
`~/.config/mcpbridge/` (`mcpbridge --logout <url>` first removes them), your `.pre` and `.post` scripts, an agent file you edited, and any recommended settings you pasted
into `~/.claude/settings.json` by hand (take those out yourself).
