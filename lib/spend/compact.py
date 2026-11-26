"""What fills a main session's context between compactions: compact.py <transcript.jsonl> [since 'YYYY-MM-DD HH:MM']"""
import json, sys, re
from collections import defaultdict
from datetime import datetime
path = sys.argv[1]
since = datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M").timestamp() if len(sys.argv) > 2 else 0
tools, seen = {}, set()
calls = []                      # (t, ctx, out, model)
adds = []                       # (t, category, chars)
def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None
def size(c):
    if isinstance(c, str): return len(c)
    if isinstance(c, list): return sum(len(b.get("text", "")) if isinstance(b, dict) else 0 for b in c)
    return 0
def kind(text):
    if "<cross-session-message" in text: return "peer session message"
    if "<task-notification" in text: return "task notification (worker/monitor/bg shell)"
    if "<system-reminder" in text: return "system reminder"
    if "This session is being continued" in text or "summary" in text[:200].lower(): return "compaction summary"
    return "user / other text"
for line in open(path, errors="replace"):
    try: o = json.loads(line)
    except Exception: continue
    if o.get("isSidechain"): continue
    m = o.get("message") or {}; t = ts(o.get("timestamp", "")); c = m.get("content")
    if t is None or t < since: 
        if o.get("type") == "assistant" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use": tools[b.get("id")] = b.get("name", "?")
        continue
    if o.get("type") == "assistant":
        u = m.get("usage") or {}; mid = m.get("id")
        if isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_use":
                    tools[b.get("id")] = b.get("name", "?")
                    adds.append((t, "own tool-call input: " + ("Agent/SendMessage prompts" if b.get("name") in ("Agent", "SendMessage") else "other"), len(json.dumps(b.get("input") or {}))))
                elif b.get("type") == "text": adds.append((t, "own prose", len(b.get("text", ""))))
        if mid and mid not in seen and not m.get("model", "").startswith("<"):
            seen.add(mid)
            calls.append((t, (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0), u.get("output_tokens") or 0, m.get("model", "?")))
    elif o.get("type") == "user":
        if isinstance(c, str): adds.append((t, kind(c), len(c)))
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    n = tools.get(b.get("tool_use_id"), "?")
                    n = "mcp" if n.startswith("mcp__") else n
                    adds.append((t, "result: " + n, size(b.get("content"))))
                elif b.get("type") == "text": adds.append((t, kind(b.get("text", "")), len(b.get("text", ""))))
calls.sort()
comps = [i for i in range(1, len(calls)) if calls[i][1] < 0.6 * calls[i - 1][1] and calls[i - 1][1] > 100000]
hours = (calls[-1][0] - calls[0][0]) / 3600 if calls else 0
print(f"{path.split('/')[-2][-22:]}  model {calls[-1][3]}  {len(calls)} calls over {hours:.1f}h, {len(comps)} compactions = one every {hours * 60 / max(len(comps), 1):.0f} min, {len(calls) / max(len(comps), 1):.0f} calls apart")
if comps:
    pk = sorted(calls[i - 1][1] for i in comps); af = sorted(calls[i][1] for i in comps)
    print(f"context at compaction: median {pk[len(pk) // 2] / 1000:.0f}k (min {pk[0] / 1000:.0f}k, max {pk[-1] / 1000:.0f}k); after: median {af[len(af) // 2] / 1000:.0f}k")
    g = []
    for a, b in zip(comps, comps[1:]):
        if b - a > 5: g.append((calls[b - 1][1] - calls[a][1]) / (b - a))
    if g: g.sort(); print(f"growth: median {g[len(g) // 2]:.0f} tokens per call")
tot = defaultdict(lambda: [0, 0])
for t, k, n in adds: tot[k][0] += 1; tot[k][1] += n
T = sum(v[1] for v in tot.values()) or 1
print("what was added to context (chars, ~4 per token):")
for k, v in sorted(tot.items(), key=lambda x: -x[1][1])[:14]:
    print(f"  {100 * v[1] / T:5.1f}%  {v[1] / 1e6:6.2f}M  n={v[0]:5d}  avg {v[1] / v[0]:6.0f}  {k}")
out = sum(c[2] for c in calls)
print(f"output tokens {out / 1e6:.2f}M (thinking is not kept in context in full; prose+tool input above is)")
