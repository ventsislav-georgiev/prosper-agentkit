#!/usr/bin/env python3
"""Format an agent's Slack message in the house style; print it for slack_send_message.

    slack-say.py [--title TEXT] LINE [LINE ...]

Each LINE is one quoted line. A leading marker adds its emoji:
data: 📊  done: ✅  ask: ❓  warn: ⚠️  fix: 🔧  link: 🔗  (no marker: no emoji).
An emoji line after the first line gets a blank quoted line before it.
With the kit setting github_url (KIT_GITHUB_URL, the GitHub web address) set,
owner/repo#N becomes a pull request link, and so does repo#N when github_owner
(KIT_GITHUB_OWNER) names the owner; with no owner set, repo#N is then refused like a
bare #N, since neither names a repo. Jira keys become links when the settings
jira_url (KIT_JIRA_URL, your Jira web address) and jira_projects
(KIT_JIRA_PROJECTS, comma-separated keys such as ABC,XYZ) are both set. The first line
is the setting slack_header (KIT_SLACK_HEADER), default ":sparkles: _Claude says:_".
This script only prints; it never sends anything. Money ($/€) and numbers with a
unit (s, ms, h, %, k, GB, vCPU, x, ...) go in backticks; dates and plain counts stay plain.
Refuses (exit 2) more than 3 markers, more than 6 lines, or a repeated line,
because the style is short, structured, and never says a thing twice.

In a DM, post the output as a new top-level message, never as a thread reply
(no thread_ts): the operator does not want threads in DMs.
"""
import os
import re
import sys

HEADER = os.environ.get("KIT_SLACK_HEADER") or ":sparkles: _Claude says:_"
MARKERS = {"data": "📊", "done": "✅", "ask": "❓", "warn": "⚠️", "fix": "🔧", "link": "🔗"}
MAX_MARKERS, MAX_LINES = 3, 6
# Slack collapses an empty quoted line and a no-break space; a braille blank (U+2800) holds the gap and, unlike a zero-width space, survives an agent copying the output into its Slack call.
GAP = "> ⠀"
GITHUB_URL = os.environ.get("KIT_GITHUB_URL", "").strip().rstrip("/")
OWNER = os.environ.get("KIT_GITHUB_OWNER", "").strip()
JIRA_URL = os.environ.get("KIT_JIRA_URL", "").strip().rstrip("/")
JIRA_PROJECTS = tuple(k for k in (x.strip() for x in os.environ.get("KIT_JIRA_PROJECTS", "").split(","))
                      if re.fullmatch(r"[A-Z][A-Z0-9]*", k))
_EXISTING = re.compile(r"(\[[^\]]*\]\([^)]*\)|<[^>]*>|https?://\S+|`[^`]*`)")
_PR = re.compile(r"(?<![\w/])(?:([\w.-]+)/)?([\w.-]+)#(\d+)\b")
_JIRA = re.compile(rf"\b(?:{'|'.join(JIRA_PROJECTS)})-\d+\b") if JIRA_URL and JIRA_PROJECTS else None
_UNIT = r"(?:k|M|%|ms|s|min|h|d|GB|GiB|TB|vCPU|x|slot-h)"
_NUM = re.compile(
    r"\*?(?<![\w$€.,])(?:[$€]\d[\d,.]*(?:[-–]\d[\d,.]*)?" + _UNIT + r"?"
    r"|\d[\d,.]*(?:[-–]\d[\d,.]*)?\s?" + _UNIT + r")(?:/(?:day|month|mo|30d|h|call|run))?(?![\w])\*?")
_BARE = re.compile(r"(?<![\w/])#\d+\b")


def _pr_link(m):
    if not GITHUB_URL:
        return m.group(0)
    owner = m.group(1) or OWNER
    if not owner:
        raise ValueError(f"{m.group(0)} names no owner; write owner/repo#N or set github_owner")
    return f"[{m.group(0)}]({GITHUB_URL}/{owner}/{m.group(2)}/pull/{m.group(3)})"


def linkify(text):
    """Put money and quantities with a unit in backticks; turn repo#N,
    owner/repo#N and configured Jira keys into Slack links; refuse a bare #N, which names no repo."""
    parts = _EXISTING.split(text)
    for i in range(0, len(parts), 2):
        seg = _NUM.sub(lambda m: f"`{m.group(0).strip('*')}`", parts[i])
        seg = _PR.sub(_pr_link, seg)
        if _JIRA:
            seg = _JIRA.sub(lambda m: f"[{m.group(0)}]({JIRA_URL}/browse/{m.group(0)})", seg)
        if _BARE.search(_EXISTING.sub("", seg)):
            raise ValueError(f"bare PR number in {text!r}; write repo#N")
        parts[i] = seg
    return "".join(parts)


def render(lines, title=None):
    out, seen, marked = [HEADER + (f" *{title}*" if title else "")], set(), 0
    if not lines:
        raise ValueError("no lines")
    if len(lines) > MAX_LINES:
        raise ValueError(f"{len(lines)} lines; at most {MAX_LINES}. Cut, or link the detail.")
    for line in lines:
        head, sep, rest = line.partition(":")
        if sep and head.strip() in MARKERS:
            line, marked = f"{MARKERS[head.strip()]} {rest.strip()}", marked + 1
            if len(out) > 1:
                out.append(GAP)
        line = linkify(line)
        key = line.strip().lower()
        if key in seen:
            raise ValueError(f"repeated line: {line!r}")
        seen.add(key)
        out.append(f"> {line.strip()}")
    if marked > MAX_MARKERS:
        raise ValueError(f"{marked} emoji markers; at most {MAX_MARKERS}.")
    return "\n".join(out)


def _selftest():
    s = render(["Hi Alex.", "data: $1.07k, stopped 28 Oct", "done: nothing to change"])
    assert s.splitlines() == [HEADER, "> Hi Alex.", GAP, "> 📊 `$1.07k`, stopped 28 Oct", GAP, "> ✅ nothing to change"], s
    assert render(["done: first", "plain"]).splitlines()[1:] == ["> ✅ first", "> plain"]
    assert render(["note: plain"], "T").splitlines()[1] == "> note: plain"
    for bad in (["a", "A"], ["done: a"] * 1 + ["done: b", "done: c", "done: d"], list("abcdefg"), []):
        try:
            render(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    if GITHUB_URL and OWNER and JIRA_URL and JIRA_PROJECTS:
        j = JIRA_PROJECTS[0] + "-89878"
        assert linkify(f"merge api#1609 ({j})") == (
            f"merge [api#1609]({GITHUB_URL}/{OWNER}/api/pull/1609) ([{j}]({JIRA_URL}/browse/{j}))")
    want = f"[octo/api#7]({GITHUB_URL}/octo/api/pull/7)" if GITHUB_URL else "octo/api#7"
    assert linkify("merge octo/api#7") == "merge " + want
    assert linkify("see [x#1](https://example.com/1) and https://example.com/a/b/pull/2 UTF-8") == \
        "see [x#1](https://example.com/1) and https://example.com/a/b/pull/2 UTF-8"
    assert linkify("averages *23 s* per call, up from 4.0 s on 29 Oct; $330-370/month, 50% off, 1178 tests, Gemini 3.1") == (
        "averages `23 s` per call, up from `4.0 s` on 29 Oct; `$330-370/month`, `50%` off, 1178 tests, Gemini 3.1")
    try:
        linkify("PR #12")
        raise AssertionError("bare #N passed")
    except ValueError:
        pass
    print("ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        _selftest()
        sys.exit(0)
    title = None
    if args[:1] == ["--title"]:
        title, args = args[1], args[2:]
    try:
        print(render(args, title))
    except ValueError as e:
        sys.exit(f"slack-say: {e}")
