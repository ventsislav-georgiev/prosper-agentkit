Daily spend review: the prompt a spend session runs once a day (for example from a session cron at 12:07). Put your
own reference numbers (a reference day, a baseline file) in your copy; the kit ships none. The tools are in the kit's
bin folder ($KIT_BIN).

Run `$KIT_BIN/spend-report.py` for yesterday 12:00 to today 12:00 into a dated file in your own reports folder and
compare it with the previous day, a reference day and your baseline. Measure: (1) first dispatches by worker tier,
cost per worker by tier, opus-medium entries escalated (flag above 25%); (2) cost per closed ledger entry and entries
closed; (3) Sonnet entries escalated and whether more kinds could start on Sonnet; (4) the pool: rewrites per bench
event, rejections reaching the client, refused startup quota checks as a count; (5) worker length: median/p90 calls
and share reaching 200k; (6) any waste category above 2% of spend or growing, including supervisor compaction and
expiry (`spend-report.py expiry`); (7) supervisor cost: `spend-report.py tokens` (cache hit, 1h vs 5m writes, top
sessions) and `spend-report.py ctxsize` (spend by context size), judged against CLAUDE_CODE_AUTO_COMPACT_WINDOW;
(8) account sizing: `spend-report.py points`, the last 7 days' points (100 = one full account-week) against live
capacity, and how many full accounts the coming week needs with about 15% headroom (`spend-report.py accounts`);
(9) startup context: `$KIT_BIN/ctxprobe.sh` in an empty folder and a main project, flag a rise above 1k and find what
came back (plugins, denied tools, MCP denies, a duplicate worker-rules feed; `$KIT_BIN/usage-audit.py`). Analyze, do
not just list: what moved, the likely cause, one recommendation at most. A bug in the report scripts goes to the kit;
brief the owning session for the rest; a change to the operator's rules or settings is proposed, not made. Report in
a short table plus a few lines; a quiet day in two lines. Session crons expire after 7 days: recreate it on the last
run.
