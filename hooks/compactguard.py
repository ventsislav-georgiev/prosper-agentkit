#!/bin/sh
''''exec "${0%"${0##*/}"}../lib/python3" "$0" "$@" # ''' # sh runs this line (lib/python3 picks the interpreter); Python reads a string
"""PreCompact hook: keeps a session's compaction summary from growing without bound.

A summary is copied forward on every compaction, so anything it restates is paid for again each
time (output tokens to write it, then input tokens on every call). When the previous summary is
over BUDGET characters this hook saves it to an archive directory next to the transcript and prints
instructions, which Claude Code appends to the summary prompt: keep what binds unfinished work,
point at the archive for the rest. Under the budget it prints nothing and compaction is untouched.

Always exits 0: exit 2 would block the compaction. `compactguard.py --test` runs the self-check.
"""
import json, os, sys, time

BUDGET = 50_000   # characters; above this the previous summary is archived and the next one is capped
TARGET = 35_000


def last_summary(path):
    text = None
    with open(path, errors="replace") as f:
        for line in f:
            if "isCompactSummary" not in line or line.startswith('{"type":"api-request'):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("isCompactSummary"):
                c = (o.get("message") or {}).get("content")
                text = c if isinstance(c, str) else "".join(b.get("text", "") for b in c or [] if isinstance(b, dict))
    return text


def instructions(path, now=None):
    text = last_summary(path)
    if not text or len(text) <= BUDGET:
        return ""
    arch = os.path.join(os.path.splitext(path)[0], "compact-archive")
    os.makedirs(arch, mode=0o700, exist_ok=True)  # the transcripts beside it are 0600
    saved = os.path.join(arch, time.strftime("summary-%Y%m%dT%H%M%SZ.md", time.gmtime(now)))
    with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    return f"""The previous summary of this conversation was {len(text):,} characters, over the {BUDGET:,} budget. A summary is copied forward on every compaction, so its length is paid for again each time. Its full text is saved at {saved}; earlier ones are in {arch}.
Write this summary in at most {TARGET:,} characters:
- Keep in full: the session's role, the user's standing instructions that apply to all work, every rule that binds an entry or task that is still open or in progress, the pending tasks, the current work and the next step.
- Do not restate rules, history or detail that concern only finished or closed work. Write this one line instead: "Rules and history of finished work are archived in {arch}; search it (rg '<entry id or keyword>' {arch}) before reopening or re-dispatching anything this summary does not describe."
- Quote a standing instruction of the user verbatim, but once.
- Never shorten what concerns unfinished work to meet the budget: drop finished work first, and go over the budget if that is still not enough."""


def self_check():
    import shutil, tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "s.jsonl")

    def write(n):
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "isCompactSummary": True, "message": {"content": "old"}}) + "\n")
            f.write(json.dumps({"type": "user", "isCompactSummary": True, "message": {"content": [{"type": "text", "text": "x" * n}]}}) + "\n")
    try:
        write(BUDGET)
        assert instructions(p) == "" and not os.path.exists(os.path.join(d, "s", "compact-archive"))
        write(BUDGET + 1)
        out = instructions(p, 0)
        saved = os.path.join(d, "s", "compact-archive", "summary-19700101T000000Z.md")
        assert saved in out and open(saved).read() == "x" * (BUDGET + 1)
        assert os.stat(saved).st_mode & 0o777 == 0o600 and os.stat(os.path.dirname(saved)).st_mode & 0o777 == 0o700
        # a missing transcript raises; the hook's main catches it and still exits 0
        try:
            instructions(os.path.join(d, "missing.jsonl"))
            raise AssertionError("missing transcript did not raise")
        except FileNotFoundError:
            pass
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("compactguard: all checks passed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        self_check()
        sys.exit(0)
    try:
        out = instructions(json.load(sys.stdin).get("transcript_path") or "")
        if out:
            print(out)
    except Exception as e:  # noqa: BLE001  a broken hook must never block or fail a compaction
        print(f"compactguard: {e}", file=sys.stderr)
    sys.exit(0)
