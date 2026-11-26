"""Classify every API call's cache behaviour: why was context written instead of read?"""
import json, os
from datetime import datetime

# Claude Code transcripts: $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects
ROOT = os.path.join(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or "~/.claude"), "projects")


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def scan(path):
    calls = {}
    side = "/subagents/" in path
    try:
        f = open(path, "r", errors="replace")
    except OSError:
        return path, side, []
    for line in f:
        if '"type":"assistant"' not in line or '"usage"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        m = o.get("message") or {}
        u = m.get("usage") or {}
        t = ts(o.get("timestamp", ""))
        mid = m.get("id")
        if not mid or t is None or m.get("model", "").startswith("<"):
            continue
        cc = u.get("cache_creation") or {}
        e = calls.get(mid)
        row = [t, u.get("input_tokens") or 0, u.get("cache_creation_input_tokens") or 0,
               cc.get("ephemeral_1h_input_tokens") or 0, u.get("cache_read_input_tokens") or 0,
               u.get("output_tokens") or 0, m.get("model", "?"), side or bool(o.get("isSidechain")), {b.get("name") for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use"}]
        if e is None:
            calls[mid] = row
        else:
            for i in (1, 2, 3, 4, 5):
                e[i] = max(e[i], row[i])
            e[8] |= row[8]
    return path, side, [(k, *v) for k, v in calls.items()]

