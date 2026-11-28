#!/bin/sh
''''exec "${0%"${0##*/}"}../lib/python3" "$0" "$@" # ''' # sh runs this line (lib/python3 picks the interpreter); Python reads a string
"""PostToolUse hook for Bash: feeds the dch-bridge's pull request state.

When a `gh pr create` command finishes, each pull request URL it printed (https, a host with no user or port, then
owner, repo, `pull` and a number as the path, no query or fragment) is handed to `dch-bridge/prs.mjs add <session id>`
on stdin. Any host passes, so GitHub Enterprise works. Anything else adds nothing. Always exits 0 and prints nothing.
PRS_HOOK_NODE names the command that runs prs.mjs (default: node); the rows are tests/prs-hook.test.sh.
"""
import json, os, re, subprocess, sys
from urllib.parse import urlsplit

PATH = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+")
SID = re.compile(r"[A-Za-z0-9-]+")
PRS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dch-bridge", "prs.mjs")


def pr_url(tok):
    try:
        u = urlsplit(tok)
        return (u.scheme == "https" and u.netloc != "" and "@" not in u.netloc and ":" not in u.netloc
                and not u.query and not u.fragment and "?" not in tok and "#" not in tok and PATH.fullmatch(u.path) is not None)
    except ValueError:
        return False


def urls(event):
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return []
    if "gh pr create" not in str(event["tool_input"].get("command", "")):
        return []
    r = event.get("tool_response")
    out = r.get("stdout") if isinstance(r, dict) else r
    if not isinstance(out, str):
        return []
    found = []
    for tok in out.split():
        if pr_url(tok) and tok not in found:
            found.append(tok)
    return found


def main():
    try:
        event = json.load(sys.stdin)
        sid = event.get("session_id")
        if not isinstance(sid, str) or not SID.fullmatch(sid):
            return
        for u in urls(event):
            # argv list, no shell; the URL goes on stdin (the add entry reads it there), never into argv
            subprocess.run([os.environ.get("PRS_HOOK_NODE") or "node", PRS, "add", sid], input=u + "\n",
                           text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
