import sys, json, re
from collections import defaultdict
att = {}
for l in sys.stdin:
    if l.startswith('{"type":"api-request') or '"attachment"' not in l: continue
    try: o = json.loads(l)
    except ValueError: continue
    if o.get("type") == "attachment" and not o.get("isSidechain"):
        a = o["attachment"]; att[a.get("type")] = a
def groups(title, items, key):
    g = defaultdict(lambda: [0, 0])
    for name, size in items:
        k = key(name); g[k][0] += 1; g[k][1] += size
    print(f"\n{title}: {sum(v[1] for v in g.values())} chars")
    for k, v in sorted(g.items(), key=lambda x: -x[1][1])[:16]: print(f"  {v[1]:6d}  n={v[0]:3d}  {k}")
def keys(a): return {k: (type(v).__name__, len(json.dumps(v))) for k, v in a.items()}
for t in ("deferred_tools_delta", "deferred_tools_record", "skill_listing", "instructions", "prompt_snapshot"):
    print(t, keys(att.get(t) or {}))
a = att.get("deferred_tools_delta") or {}
src = a.get("addedLines") or a.get("addedNames") or a.get("names") or []
groups("deferred tools by server", [(n, len(n) + 1) for n in src],
       lambda n: "mcp__" + n.split("__")[1] if n.startswith("mcp__") else "built-in")
txt = (att.get("skill_listing") or {}).get("content") or ""
ent = [(m.group(1).split(": ")[0], len(m.group(1)) + 3) for m in re.finditer(r"^- (.+)$", txt, re.M)]
groups("skills by plugin", ent, lambda n: n.split(":")[0] if ":" in n else "(no plugin prefix)")
i = att.get("instructions") or {}
for v in i.values():
    if isinstance(v, list):
        for it in v:
            if isinstance(it, dict):
                print("  instr", len(json.dumps(it)), it.get("path") or it.get("file") or it.get("type") or list(it.keys()))
p = att.get("prompt_snapshot") or {}
print("\nprompt_snapshot head:", json.dumps(p)[:260])
