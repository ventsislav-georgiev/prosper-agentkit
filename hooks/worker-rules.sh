#!/bin/bash
# Claude Code SubagentStart hook: hands the rules in worker-rules.md (kit config folder) to every subagent at start.
# Workers run with omitClaudeMd, so this is the one place for rules all of them share. No file: the kit's own
# rules/lean-code.md (the lean-code-rules piece's text). Your file wins whole; an empty or whitespace-only one sends
# nothing (the off switch). Any error: prints nothing. Always exits 0.
cat >/dev/null
f=${KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/prosper-agentkit}/worker-rules.md
[[ -e $f ]] || f=${0%"${0##*/}"}../rules/lean-code.md
[[ -f $f && -s $f ]] || exit 0
# Cap at 16 KB, cut at a line end, so a huge file cannot flood every worker.
"${0%"${0##*/}"}../lib/python3" -c 'import json,sys
cap = 16384
with open(sys.argv[1], "rb") as fh:
    b = fh.read(cap + 1)
if len(b) > cap:
    b = b[:cap]
    nl = b.rfind(b"\n")
    if nl > 0:
        b = b[:nl + 1]
t = b.decode("utf-8", "ignore")
if t.strip():
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": t}}))' "$f" 2>/dev/null
exit 0
