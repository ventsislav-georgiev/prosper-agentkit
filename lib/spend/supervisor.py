"""What fills one session's context: supervisor.py <transcript.jsonl> 'YYYY-MM-DD HH:MM' (local time).

Prints (1) the session's spend split since that time, (2) what the context holds right after the
latest compaction (the floor), (3) what was added to the context since that time, by kind.
Sizes are characters; tokens are estimated with the chars-per-token ratio of the first request after
the compaction.
"""
import json, os, re, sys
from collections import defaultdict
from datetime import datetime

from cache import ts
from report import price


def size(c):
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(b.get("text") or "") + size(b.get("content")) if isinstance(b, dict) else 0 for b in c)
    return 0


def att_size(a):
    return sum(len(v) if isinstance(v, str) else len(json.dumps(v)) for k, v in a.items()
               if k in ("content", "files", "addedLines", "addedBlocks", "stdout", "context", "snapshot", "text",
                        "description", "deltaSummary", "shell", "date"))


def user_kind(text):
    for tag, k in (("<task-notification", "task notification"), ("<cross-session-message", "peer message"),
                   ("<system-reminder", "system reminder"), ("<command-", "slash command")):
        if tag in text[:300]:
            return k
    return "typed or scheduled prompt"


def show(title, d, ratio, top=14):
    tot = sum(d.values()) or 1
    print(f"\n{title}: {tot:,} chars ~ {tot / ratio / 1000:.0f}k tokens")
    for k, v in sorted(d.items(), key=lambda x: -x[1])[:top]:
        print(f"  {v:9,}  {100 * v / tot:4.1f}%  ~{v / ratio / 1000:5.1f}k  {k}")


def main():
    path, start = sys.argv[1], datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M").timestamp()
    rows = []
    for l in open(path, errors="replace"):
        if l.startswith('{"type":"api-request'):
            continue
        try:
            o = json.loads(l)
        except ValueError:
            continue
        if not o.get("isSidechain"):
            rows.append(o)
    last = max((i for i, o in enumerate(rows) if o.get("subtype") == "compact_boundary"), default=None)

    # 1. spend split
    seen, d, n = {}, defaultdict(float), 0
    for o in rows:
        m = o.get("message") if isinstance(o.get("message"), dict) else {}
        u, t = m.get("usage"), ts(o.get("timestamp") or "")
        if o.get("type") == "assistant" and u and t and t >= start:
            seen[m.get("id")] = (u, m.get("model", ""))
    for u, model in seen.values():
        pi, po, pr = price(model)
        cw, cw1 = u.get("cache_creation_input_tokens") or 0, (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
        d["cache read"] += (u.get("cache_read_input_tokens") or 0) * pr / 1e6
        d["cache write"] += ((cw - cw1) * 1.25 + cw1 * 2) * pi / 1e6
        d["output"] += (u.get("output_tokens") or 0) * po / 1e6
        n += 1
    T = sum(d.values()) or 1
    print(f"{os.path.basename(path)[:8]}: ${T:.1f} over {n} calls since {sys.argv[2]}: " +
          ", ".join(f"{k} ${v:.1f} ({100 * v / T:.0f}%)" for k, v in d.items()))

    # 2. the floor: everything between the latest compaction and the first reply after it
    ratio = 3.5
    if last is not None:
        floor, first = defaultdict(int), None
        for o in rows[last:]:
            t = o.get("type")
            if t == "assistant" and (o.get("message") or {}).get("usage"):
                first = o["message"]["usage"]
                break
            if t == "user":
                floor["summary of the conversation" if o.get("isCompactSummary") else "user message"] += size(o["message"].get("content"))
            elif t == "attachment":
                a = o["attachment"]
                if a.get("type") == "instructions":
                    for f in a.get("files") or []:
                        p = f.get("path") or "?"
                        floor["instructions: " + ("memory index" if p.endswith("MEMORY.md") else p.replace(os.path.expanduser("~"), "~"))] += len(f.get("content") or "")
                elif a.get("type") == "file":
                    floor["re-read files"] += len(json.dumps(a.get("content")))
                else:
                    floor[a.get("type", "?")] += att_size(a)
        if first:
            msg_tok = first.get("cache_creation_input_tokens") or 0
            ratio = (sum(floor.values()) / msg_tok) if msg_tok else ratio
            print(f"\nfirst call after the latest compaction: {first.get('cache_read_input_tokens')} tokens read "
                  f"(tools + system prompt), {msg_tok} written (messages); {ratio:.2f} chars per token")
        show("floor after compaction (messages only)", floor, ratio, 18)

    # 3. growth since start
    names, g = {}, defaultdict(int)
    for o in rows:
        t, when = o.get("type"), ts(o.get("timestamp") or "")
        m = o.get("message") if isinstance(o.get("message"), dict) else {}
        c = m.get("content")
        if t == "assistant" and isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use":
                    names[b.get("id")] = b.get("name")
                    if when and when >= start:
                        g["tool call input: " + re.sub(r"^mcp__(\w+?)__.*", r"mcp \1", b.get("name", "?"))] += len(json.dumps(b.get("input")))
                elif b.get("type") == "text" and when and when >= start:
                    g["assistant text"] += len(b.get("text") or "")
        elif not when or when < start or o.get("isCompactSummary"):
            continue
        elif t == "user":
            if isinstance(c, str):
                g["user: " + user_kind(c)] += len(c)
            else:
                for b in c or []:
                    if b.get("type") == "tool_result":
                        g["tool result: " + re.sub(r"^mcp__(\w+?)__.*", r"mcp \1", names.get(b.get("tool_use_id")) or "?")] += size(b.get("content"))
                    elif b.get("type") == "text":
                        g["user: " + user_kind(b.get("text") or "")] += len(b.get("text") or "")
        elif t == "attachment" and last is not None and rows.index(o) < last + 60 and rows.index(o) > last:
            continue    # counted in the floor
        elif t == "attachment":
            g["attachment: " + o["attachment"].get("type", "?")] += att_size(o["attachment"])
    show(f"added to the context since {sys.argv[2]} (thinking not included: it is not stored)", g, ratio, 22)


if __name__ == "__main__":
    main()
