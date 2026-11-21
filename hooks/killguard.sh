#!/bin/bash
# Claude Code PreToolUse hook (Bash, Monitor): denies pkill and killall. A pattern kill on a shared machine reaches other
# sessions, and on macOS an option after the pattern becomes another pattern. Use safekill, or kill <pid>.
input=$(</dev/stdin)
# Fast path: no pkill or killall anywhere in the call, nothing to parse.
case $input in *pkill* | *killall*) ;; *) exit 0 ;; esac
# jq when it is on PATH, else python3: the kit does not require jq.
cmd=$(jq -r '.tool_input.command // empty' <<<"$input" 2>/dev/null) ||
  cmd=$(/usr/bin/python3 -Ic 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("command") or "")' <<<"$input" 2>/dev/null) ||
  exit 0
[[ -n $cmd ]] || exit 0

RUN='(^|[;&|({`'"'"'"]|\$\()[[:space:]]*((sudo|nohup|exec|env|xargs|command|time|nice|timeout([[:space:]]+-[^[:space:]]+)*[[:space:]]+[0-9.]+[smhd]?)[[:space:]]+)*([^[:space:];&|]*/)?(pkill|killall)([[:space:]]|$)'
LC_ALL=C /usr/bin/grep -Eq "$RUN" <<<"$cmd" || exit 0

# Under the kit, safekill is the KIT_BIN shim; run standalone, it is the kit copy next to this hook.
sk=${KIT_BIN:+$KIT_BIN/safekill}
sk=${sk:-$(cd "$(dirname "$0")/../tools/killguard" 2>/dev/null && pwd)/safekill}
reason="killguard: pkill and killall are not allowed (a pattern kill takes down every process whose command line matches, other sessions included). Kill the pid you recorded with \$! (kill <pid>), or run $sk -n '<pattern>' to list the matches, then $sk '<pattern>'."
jq -nc --arg r "$reason" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}' 2>/dev/null ||
  /usr/bin/python3 -Ic 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))' "$reason" 2>/dev/null ||
  { echo "$reason" >&2; exit 2; }
