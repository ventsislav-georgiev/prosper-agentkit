#!/bin/sh
''''exec "${0%"${0##*/}"}../../lib/python3" "$0" "$@" # ''' # sh runs this line (lib/python3 picks the interpreter); Python reads a string
__doc__ = """Spend review from Claude Code transcripts, Prosper's ccpool files and the kit ledger. Reads only.

  spend-report.py [report] START [END]    spend for a window: main vs workers, cache rewrites by cause, ccpool bench
                                          events, compaction summaries, workers by model and tier, ledger dispatches
  spend-report.py expiry START END        supervisor cache-expiry rewrites by session
  spend-report.py byproject START END     spend by project folder
  spend-report.py tokens START END        token totals, cache hit, 1h vs 5m writes, top supervisor sessions
  spend-report.py ctxsize START END       supervisor spend by context size per call
  spend-report.py revive START [END]      double cache writes after a session restart
  spend-report.py points [--hourly]       weekly-limit points per account per day (100 = one account-week)
  spend-report.py accounts                how many accounts a week of usage needs
  spend-report.py fit [MIN_STEP]          how the five-hour limit weighs token types
  spend-report.py compact FILE [SINCE]    what fills one main session's context between compactions
  spend-report.py supervisor FILE SINCE   one session's spend split, its floor after compaction, what it added since
  spend-report.py floor < FILE            startup attachments of a transcript (deferred tools, skills, instructions)
  spend-report.py entries --since T [--until T] --json [--out FILE]
                                          worker tokens and $ per ledger entry and tier, each main session's split (JSON;
                                          T may also be 12h / 7d back)
  spend-report.py selftest                the row-conversion and settings checks

Times are local, 'YYYY-MM-DD HH:MM'. Dollars are API list prices, used only as weights.
Transcripts: $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects. ccpool: $PROSPER_CCPOOL_DIR, else
~/Library/Application Support/Prosper/agentpool (ccpool before Prosper's rename). Ledger: $LEDGER_DB as todo.py finds it. Accounts on a smaller plan
(left out of the account-week totals): the kit setting spend_small_accounts (KIT_SPEND_SMALL_ACCOUNTS)."""
import os, runpy, sys

CMDS = {"report", "expiry", "byproject", "tokens", "ctxsize", "revive", "points", "accounts", "fit", "compact",
        "supervisor", "floor", "entries", "selftest"}

NEED = {"expiry": 2, "byproject": 2, "tokens": 2, "ctxsize": 2, "revive": 1, "compact": 1, "supervisor": 2, "entries": 2}

if __name__ == "__main__":
    args = sys.argv[1:]
    name = args.pop(0) if args and args[0] in CMDS else "report"
    if (name == "report" and not args) or (args and args[0] in ("-h", "--help")):
        print(__doc__)
        sys.exit(0 if args else 2)
    if len(args) < NEED.get(name, 0):   # a missing argument gets the command's usage line, not a traceback
        sys.exit("usage: " + next(l.strip() for l in __doc__.splitlines() if l.strip().startswith(f"spend-report.py {name} ")))
    if name in ("compact", "supervisor") and not os.path.isfile(args[0]):
        sys.exit(f"spend-report {name}: no such transcript: {args[0]}")
    # -I leaves the script folder off sys.path; the modules live in the kit's lib/spend
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "lib", "spend"))
    sys.argv = [name + ".py"] + args
    runpy.run_module("ccdata" if name == "selftest" else name, run_name="__main__", alter_sys=True)
