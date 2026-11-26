#!/bin/sh
''''exec "${0%"${0##*/}"}../../lib/python3" "$0" "$@" # ''' # sh runs this line (lib/python3 picks the interpreter); Python reads a string
__doc__ = """What sessions actually use, from transcripts: usage-audit.py [days] [--root DIR].

Counts built-in tool calls, MCP calls per server and project, and Skill calls in the Claude Code transcripts changed in
the last <days> (default 14). The input for deciding which plugins, MCP servers and tools to switch off or deny; see
ctxprobe.sh for what each costs at session start. Transcripts are read from --root, else $CLAUDE_CONFIG_DIR/projects,
else ~/.claude/projects. Reads only."""
import argparse, glob, json, os, time
from collections import Counter, defaultdict


def default_root():
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or "~/.claude"
    return os.path.join(os.path.expanduser(base), "projects")


def audit(root, days):
    # shortcut: counts whole transcripts touched in the window, not only calls inside it; filter by timestamp if exact counts matter
    since = time.time() - days * 86400
    tools, skills, mcp = Counter(), Counter(), defaultdict(Counter)
    for p in glob.glob(os.path.join(glob.escape(root), "**", "*.jsonl"), recursive=True):
        if os.path.getmtime(p) < since:
            continue
        proj = os.path.relpath(p, root).split(os.sep)[0]
        with open(p, errors="ignore") as f:
            for line in f:
                if '"tool_use"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                content = (o.get("message") or {}).get("content") if isinstance(o, dict) else None
                for c in content if isinstance(content, list) else []:
                    if not (isinstance(c, dict) and c.get("type") == "tool_use" and isinstance(c.get("name"), str)):
                        continue
                    n = c["name"]
                    if n.startswith("mcp__"):
                        mcp[n.split("__")[1]][proj] += 1
                    else:
                        tools[n] += 1
                    if n == "Skill":
                        skills[str((c.get("input") or {}).get("skill", "?"))] += 1
    return tools, mcp, skills


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="?", type=float, default=14.0, help="window in days (default 14)")
    ap.add_argument("--root", default=default_root(), help="transcripts folder (default: Claude Code's projects folder)")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        ap.error("no transcripts folder at %s" % a.root)
    tools, mcp, skills = audit(a.root, a.days)
    print("TOOLS", tools.most_common())
    for s, c in sorted(mcp.items(), key=lambda x: (-sum(x[1].values()), x[0])):
        print("MCP", s, sum(c.values()), dict(c.most_common(6)))
    print("SKILLS", skills.most_common())


if __name__ == "__main__":
    main()
