-- Ledger Stats view (init.lua) against Prosper's Lua extension harness: the JSON-to-view mapping and every
-- empty and error state. The harness lives in the Prosper repo (scripts/ext-test/harness.lua):
--   LUA_PATH="<prosper>/scripts/ext-test/?.lua;;" lua kit/init.test.lua
-- The JSON below is real `todo.py stats --all --json` output (schema 1) from a two-project fixture ledger
-- (alpha, beta: 6 entries, 4 closed, 6 review verdicts, 2 PRs and 2 commits, 2 open questions); only
-- "database" was rewritten.
local h = require("harness")

local TIER30 = [==[{"schema":1,"generated_at":"2026-11-27T06:49:44+00:00","database":"/tmp/fixture/ledger.sqlite3","scope":{"projects":"all","since":"2026-10-28T06:49:44+00:00","until":"2026-11-27T06:49:44+00:00","days":30.0,"by":"tier"},"totals":{"counts":{"entries":{"DONE":4,"IN PROGRESS":2},"questions":{"OPEN":2}},"closed":4,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":4,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":4,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":6,"fail":2,"fail_rate":0.333,"estimated":0,"source":"structured","entries_reviewed":6,"entries_with_fail":2,"reviews_before_close":{"n":4,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":6,"fail":2,"fail_rate":0.333}],"by_tier":[{"tier":"opus/medium","verdicts":5,"fail":2,"fail_rate":0.4},{"tier":"sonnet/high","verdicts":1,"fail":0,"fail_rate":0.0}]},"parked":{"now":0,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":2,"per_day":0.1,"per_100_closed":50.0,"open_now":2,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":31,"p50":0,"p90":0,"mean":0.13},"wip_now":2},"prs":{"landed":2,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.06},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"commits":{"landed":2,"commit_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.06},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"idle":{"max_gap_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":4,"p50":0,"p90":0,"mean":0.0}},"spend":null},"groups":[{"key":"opus/medium","closed":3,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":3,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":3,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":3,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":3,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":3,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":3,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":5,"fail":2,"fail_rate":0.4,"estimated":0,"source":"structured","entries_reviewed":5,"entries_with_fail":2,"reviews_before_close":{"n":3,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":5,"fail":2,"fail_rate":0.4}],"by_tier":[{"tier":"opus/medium","verdicts":5,"fail":2,"fail_rate":0.4}]},"parked":{"now":null,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":0,"per_day":0.0,"per_100_closed":0.0,"open_now":null,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":31,"p50":0,"p90":0,"mean":0.1},"wip_now":null},"prs":{"landed":2,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.06},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"commits":{"landed":2,"commit_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.06},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"idle":{"max_gap_h":{"n":3,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":3,"p50":0,"p90":0,"mean":0.0}},"spend":null},{"key":"sonnet/high","closed":1,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":1,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":1,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":1,"fail":0,"fail_rate":0.0,"estimated":0,"source":"structured","entries_reviewed":1,"entries_with_fail":0,"reviews_before_close":{"n":1,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":1,"fail":0,"fail_rate":0.0}],"by_tier":[{"tier":"sonnet/high","verdicts":1,"fail":0,"fail_rate":0.0}]},"parked":{"now":null,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":0,"per_day":0.0,"per_100_closed":0.0,"open_now":null,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":31,"p50":0,"p90":0,"mean":0.03},"wip_now":null},"prs":{"landed":1,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.03},"gap_h":{"n":0,"p50":null,"p90":null,"mean":null}},"commits":{"landed":1,"commit_share":1.0,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.03},"gap_h":{"n":0,"p50":null,"p90":null,"mean":null}},"idle":{"max_gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":1,"p50":0,"p90":0,"mean":0.0}},"spend":null}],"daily":[{"day":"2026-10-28","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-29","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-30","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-31","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-01","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-02","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-03","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-04","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-05","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-06","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-07","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-08","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-09","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-10","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-11","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-12","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-13","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-14","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-15","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-16","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-17","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-18","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-19","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-20","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-21","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-22","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-23","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-24","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-25","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-26","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-27","closed":4,"closed_sweep":0,"wip":2,"parked":0,"prs":2,"commits":2,"asked":2,"verdicts":6,"fail":2,"estimated":false}],"hud":"30d 4 closed | cycle 0h | review fail 33% | 2 PRs + 2 commits | WIP 2 | parked 0 | OQ 2"}]==]
local PROJECT7 = [==[{"schema":1,"generated_at":"2026-11-27T06:49:45+00:00","database":"/tmp/fixture/ledger.sqlite3","scope":{"projects":"all","since":"2026-11-20T06:49:45+00:00","until":"2026-11-27T06:49:45+00:00","days":7.0,"by":"project"},"totals":{"counts":{"entries":{"DONE":4,"IN PROGRESS":2},"questions":{"OPEN":2}},"closed":4,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":4,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":4,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":6,"fail":2,"fail_rate":0.333,"estimated":0,"source":"structured","entries_reviewed":6,"entries_with_fail":2,"reviews_before_close":{"n":4,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":6,"fail":2,"fail_rate":0.333}],"by_tier":[{"tier":"opus/medium","verdicts":5,"fail":2,"fail_rate":0.4},{"tier":"sonnet/high","verdicts":1,"fail":0,"fail_rate":0.0}]},"parked":{"now":0,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":2,"per_day":0.3,"per_100_closed":50.0,"open_now":2,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":8,"p50":0,"p90":4,"mean":0.5},"wip_now":2},"prs":{"landed":2,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"commits":{"landed":2,"commit_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"idle":{"max_gap_h":{"n":4,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":4,"p50":0,"p90":0,"mean":0.0}},"spend":null},"groups":[{"key":"alpha","closed":2,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":2,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":2,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":3,"fail":1,"fail_rate":0.333,"estimated":0,"source":"structured","entries_reviewed":3,"entries_with_fail":1,"reviews_before_close":{"n":2,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":3,"fail":1,"fail_rate":0.333}],"by_tier":[{"tier":"opus/medium","verdicts":3,"fail":1,"fail_rate":0.333}]},"parked":{"now":null,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":1,"per_day":0.1,"per_100_closed":50.0,"open_now":1,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"wip_now":1},"prs":{"landed":2,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"commits":{"landed":2,"commit_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"idle":{"max_gap_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":2,"p50":0,"p90":0,"mean":0.0}},"spend":null},{"key":"beta","closed":2,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"lead_h_all":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"cycle_h_all":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"dispatches_per_closed":{"n":2,"p50":0,"p90":0,"mean":0.0},"rounds_per_closed":{"n":2,"p50":0,"p90":0,"mean":0.0},"review":{"verdicts":3,"fail":1,"fail_rate":0.333,"estimated":0,"source":"structured","entries_reviewed":3,"entries_with_fail":1,"reviews_before_close":{"n":2,"p50":1,"p90":1,"mean":1.0},"by_round":[{"round":"1","verdicts":3,"fail":1,"fail_rate":0.333}],"by_tier":[{"tier":"opus/medium","verdicts":2,"fail":1,"fail_rate":0.5},{"tier":"sonnet/high","verdicts":1,"fail":0,"fail_rate":0.0}]},"parked":{"now":null,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":1,"per_day":0.1,"per_100_closed":50.0,"open_now":1,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"wip_now":1},"prs":{"landed":2,"estimated":0,"source":"structured","pr_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"commits":{"landed":2,"commit_share":1.0,"per_day":{"n":8,"p50":0,"p90":2,"mean":0.25},"gap_h":{"n":1,"p50":0.0,"p90":0.0,"mean":0.0}},"idle":{"max_gap_h":{"n":2,"p50":0.0,"p90":0.0,"mean":0.0},"idle_h":{"n":2,"p50":0,"p90":0,"mean":0.0}},"spend":null}],"daily":[{"day":"2026-11-20","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-21","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-22","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-23","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-24","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-25","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-26","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-27","closed":4,"closed_sweep":0,"wip":2,"parked":0,"prs":2,"commits":2,"asked":2,"verdicts":6,"fail":2,"estimated":false}],"hud":"7d 4 closed | cycle 0h | review fail 33% | 2 PRs + 2 commits | WIP 2 | parked 0 | OQ 2"}]==]
local EMPTY = [==[{"schema":1,"generated_at":"2026-11-27T06:48:59+00:00","database":"/tmp/fixture/ledger.sqlite3","scope":{"projects":"all","since":"2026-10-28T06:48:59+00:00","until":"2026-11-27T06:48:59+00:00","days":30.0,"by":"tier"},"totals":{"counts":{"entries":{},"questions":{}},"closed":0,"closed_sweep":0,"closed_imported":0,"closed_without_progress":0,"reopened":0,"dropped":0,"lead_h":{"n":0,"p50":null,"p90":null,"mean":null},"lead_h_all":{"n":0,"p50":null,"p90":null,"mean":null},"cycle_h":{"n":0,"p50":null,"p90":null,"mean":null},"cycle_h_all":{"n":0,"p50":null,"p90":null,"mean":null},"dispatches_per_closed":{"n":0,"p50":null,"p90":null,"mean":null},"rounds_per_closed":{"n":0,"p50":null,"p90":null,"mean":null},"review":{"verdicts":0,"fail":0,"fail_rate":null,"estimated":0,"source":null,"entries_reviewed":0,"entries_with_fail":0,"reviews_before_close":{"n":0,"p50":null,"p90":null,"mean":null},"by_round":[],"by_tier":[]},"parked":{"now":0,"events":0,"dwell_d_resolved":{"n":0,"p50":null,"p90":null,"mean":null},"dwell_d_ongoing":{"n":0,"p50":null,"p90":null,"mean":null}},"questions":{"asked":0,"per_day":0.0,"per_100_closed":null,"open_now":0,"ask_to_rule_h":{"n":0,"p50":null,"p90":null,"mean":null}},"flow":{"closes_per_day":{"n":31,"p50":0,"p90":0,"mean":0.0},"wip_now":0},"prs":{"landed":0,"estimated":0,"source":null,"pr_share":null,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.0},"gap_h":{"n":0,"p50":null,"p90":null,"mean":null}},"commits":{"landed":0,"commit_share":null,"per_day":{"n":31,"p50":0,"p90":0,"mean":0.0},"gap_h":{"n":0,"p50":null,"p90":null,"mean":null}},"idle":{"max_gap_h":{"n":0,"p50":null,"p90":null,"mean":null},"idle_h":{"n":0,"p50":null,"p90":null,"mean":null}},"spend":null},"groups":[],"daily":[{"day":"2026-10-28","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-29","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-30","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-10-31","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-01","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-02","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-03","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-04","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-05","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-06","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-07","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-08","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-09","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-10","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-11","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-12","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-13","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-14","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-15","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-16","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-17","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-18","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-19","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-20","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-21","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-22","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-23","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-24","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-25","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-26","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false},{"day":"2026-11-27","closed":0,"closed_sweep":0,"wip":null,"parked":null,"prs":0,"commits":0,"asked":0,"verdicts":0,"fail":0,"estimated":false}],"hud":"30d 0 closed | cycle - | review fail - | 0 PRs | WIP 0 | parked 0 | OQ 0"}]==]
local DB = "/tmp/fixture/ledger.sqlite3"
local HOME = "/tmp/fixture/home"
local TODO = HOME .. "/.config/prosper/kits/io.github.ventsislav-georgiev.prosper-agentkit/bin/todo.py"

-- The real host stamps `type` (ExtensionHostAPI tag()); the harness's uiNode sets `kind`, which would clobber
-- the chart's own kind = "line", so these mirror the host.
local function tag(t) return function(o) o = o or {}; o.type = t; return o end end

-- opts: runs = list of results host.process.run answers in turn; mtimes = { [path] = n }.
local function setup(opts)
    local host, env = h.makeHost{ now = opts.now or 100000 }
    env.runs, env.argvs, env.mtimes = opts.runs or {}, {}, opts.mtimes or { [DB] = 1, [DB .. "-wal"] = 2 }
    for k, v in pairs(opts.prefs or {}) do env.prefs[k] = v end
    host.env = { get = function(k) return k == "HOME" and HOME or nil end }
    host.process.run = function(o)
        env.argvs[#env.argvs + 1] = o.argv
        h.eq(o.timeout, 10, "timeout"); h.eq(o.max_bytes, 1048576, "max_bytes")
        return assert(table.remove(env.runs, 1), "unexpected todo.py run")
    end
    host.fs.attributes = function(p)
        local m = env.mtimes[p]
        return m and { exists = true, mtime = m } or { exists = false }
    end
    for _, k in ipairs({ "detail", "grid", "loading", "chart", "list" }) do host.ui[k] = tag(k) end
    host.window.open = function(node) env.opened = (env.opened or 0) + 1; env.window = node end
    h.load(h.dir() .. "init.lua", host)
    return host, env
end

local function ok(json) return { ok = true, status = 0, stdout = json, stderr = "", timed_out = false, truncated = false } end
local function exit(n, err) return { ok = false, status = n, stdout = "", stderr = err or "", timed_out = false, truncated = false } end
local function titles(node)
    local t = {}
    for _, it in ipairs(node.items or {}) do t[#t + 1] = it.title .. "=" .. tostring(it.subtitle) end
    return table.concat(t, "\n")
end
local function has(s, needle, msg)
    if not tostring(s):find(needle, 1, true) then error((msg or "has") .. ": no '" .. needle .. "' in:\n" .. tostring(s), 2) end
end
local function hasnt(s, needle, msg)
    if tostring(s):find(needle, 1, true) then error((msg or "hasnt") .. ": '" .. needle .. "' in:\n" .. tostring(s), 2) end
end

-- 1. First open, 30d by tier: one run with the exact argv, the KPI grid, the cache written.
do
    local _, env = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    h.eq(#env.argvs, 1, "one run")
    h.eq(table.concat(env.argvs[1], " "), TODO .. " stats --all --since 30d --by tier --json", "argv")
    h.eq(env.opened, 2, "loading first, then the stats")
    local g = env.window
    h.eq(g.type, "grid", "overview is a grid")
    local t = titles(g)
    has(t, "Closed per day=4 closed · 0 (0)", "closed tile")
    has(t, "Cycle time=0 h (0 h)", "cycle tile")
    has(t, "Review fail rate=33.3% (2/6)", "fail tile")
    has(t, "PRs landed per day=0 (0) · 2 PRs + 2 commits", "prs tile")
    has(t, "OQ per 100 closed=50 · ruling -", "oq tile")
    has(t, "WIP now=2", "wip tile")
    has(t, "Parked now=0", "parked tile")
    hasnt(t, "~", "no estimate in structured data")
    hasnt(t, "stats failed", "no error line")
    assert(env.prefs["stats.cache.30d.tier"], "cache written")
    -- the tables: one row per tier, from the same run
    local tv = stats_show("table")
    h.eq(tv.type, "detail", "table is a detail")
    has(tv.markdown, "`opus/medium     3", "opus row")
    has(tv.markdown, "`sonnet/high     1", "sonnet row")
    has(tv.markdown, "not assigned at random", "selection-bias caveat")
    h.eq(#env.argvs, 1, "navigation runs nothing")
end

-- 2. Estimated values carry ~ and the footnote tile.
do
    local est = TIER30:gsub('"review":{"verdicts":6,"fail":2,"fail_rate":0.333,"estimated":0', '"review":{"verdicts":6,"fail":2,"fail_rate":0.333,"estimated":3', 1)
    assert(est ~= TIER30, "fixture edit applied")
    local _, env = setup{ runs = { ok(est) } }
    ledger_stats()
    local t = titles(env.window)
    has(t, "Review fail rate=~33.3% (2/6)", "~ on the estimated tile")
    has(t, "~ estimated from free text", "footnote")
end

-- 3. Trends: one line chart, 8 series, one point per day (31 for 30d; WIP null days dropped).
do
    local _, env = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    local c = stats_show("trends")
    h.eq(c.type, "chart", "trends is a chart"); h.eq(c.kind, "line", "line chart")
    h.eq(#c.series, 8, "series count")
    for _, s in ipairs(c.series) do
        if s.name ~= "WIP" then h.eq(#s.points, 31, s.name .. " points") end
        h.le(#s.points, 90, s.name .. " under the cap")
    end
    h.eq(c.series[1].name, "Closed"); h.eq(c.series[1].points[31].y, 4, "today's closes")
    h.eq(c.series[1].points[31].x, h.decode(TIER30).daily[31].day:sub(6), "x is MM-DD")
    -- 90 rows of a 91-day window keep the last 90
    local d = h.decode(TIER30)
    for i = 1, 60 do table.insert(d.daily, 1, { day = "2026-01-01", closed = 0 }) end
    local _, env2 = setup{ runs = { ok(h.encode(d)) } }
    ledger_stats()
    h.eq(#stats_show("trends").series[1].points, 90, "capped at 90 points")
end

-- 4. Per project, 7d: the group action runs with --by project, the window action with --since.
do
    local _, env = setup{ runs = { ok(TIER30), ok(PROJECT7), ok(PROJECT7) } }
    ledger_stats()
    local tv = stats_group("project")
    h.eq(table.concat(env.argvs[2], " "), TODO .. " stats --all --since 30d --by project --json", "group argv")
    has(tv.markdown, "`alpha ", "alpha row"); has(tv.markdown, "`beta ", "beta row")
    stats_window("7d")
    h.eq(env.argvs[3][5], "7d", "window argv")
end

-- 5. Refresh policy: unchanged ledger, -wal and settings = no run; any mtime change = one run.
do
    local _, env = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    ledger_stats(); stats_refresh("overview")
    h.eq(#env.argvs, 1, "cache hit: no rerun")
    env.mtimes[DB .. "-wal"] = 3; env.runs[1] = ok(TIER30)
    stats_refresh("overview")
    h.eq(#env.argvs, 2, "-wal changed: rerun")
    env.mtimes[HOME .. "/.config/prosper-agentkit/.settings.env"] = 9; env.runs[1] = ok(TIER30)
    ledger_stats()
    h.eq(#env.argvs, 3, "settings changed: rerun")
end

-- 6. Exit 4: the no-ledger message with an Open Settings action that opens the kit tab.
do
    local _, env = setup{ runs = { exit(4, "error: no ledger at /x/ledger.sqlite3\n") } }
    ledger_stats()
    h.eq(env.window.type, "detail")
    has(env.window.markdown, "No ledger at /x/ledger.sqlite3. Set the ledger path in the kit's Settings.")
    h.eq(env.window.actions[1].id, "stats_settings")
    env.runs[1] = exit(4, "error: no ledger at /x/ledger.sqlite3\n")
    stats_settings()
    h.eq(env.settingsOpened, "kit", "kit settings tab")
    assert(env.prefs["stats.cache.30d.tier"] == nil, "nothing cached")
end

-- 7. No System Access: the line, alone or over the cache with its age.
local REFUSED = { ok = false, stdout = "", stderr = "", timed_out = false, truncated = false,
                  error = "host.process.run: restricted to system extensions" }
do
    local _, env = setup{ runs = { REFUSED } }
    ledger_stats()
    has(env.window.markdown, "Stats need System Access for the kit (Settings > Extensions)")
    local _, env2 = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    env2.now = env2.now + 3 * 3600; env2.mtimes[DB] = 5; env2.runs[1] = REFUSED
    ledger_stats()
    local t = titles(env2.window)
    has(t, "Stats need System Access", "line over the cache")
    has(t, "showing stats from 3 h ago", "cache age")
    has(t, "Closed per day=4 closed", "cached tiles stay")
end

-- 8. No closes in the window: "-" tiles, the since date, a longer-window action.
do
    local _, env = setup{ runs = { ok(EMPTY) } }
    ledger_stats()
    local t = titles(env.window)
    has(t, "Cycle time=-"); has(t, "Review fail rate=-"); has(t, "Closed per day=-")
    has(t, "no closed entries since " .. h.decode(EMPTY).scope.since:sub(1, 10))
    local none
    for _, it in ipairs(env.window.items) do if it.id == "none" then none = it end end
    h.eq(none.actions[1].id, "stats_window"); h.eq(none.actions[1].value, "90d", "suggests 90d")
    has(stats_show("table").markdown, "no closed entries, reviews or parks")
    h.eq(#stats_show("trends").series[1].points, 31, "zeros still chart")
end

-- 9. Timeout, non-zero exit, undecodable JSON, newer schema: never blank; the cache stays under the line.
for _, case in ipairs{
    { { ok = false, status = 143, stdout = "", stderr = "", timed_out = true, truncated = false }, "stats failed: timed out after 10 s" },
    { exit(1, "\nTraceback (most recent call last):\n  boom\n"), "stats failed: Traceback (most recent call last):" },
    { exit(2, ""), "stats failed: exit 2" },
    { ok("{not json"), "stats failed: the JSON did not decode" },
    { ok((TIER30:gsub('"schema":1', '"schema":2', 1))), "Update the kit" },
} do
    local _, env = setup{ runs = { case[1] } }
    ledger_stats()
    h.eq(env.window.type, "detail", case[2] .. " without a cache")
    has(env.window.markdown, case[2])
    assert(env.prefs["stats.cache.30d.tier"] == nil, "a failure caches nothing")
    local _, env2 = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    env2.mtimes[DB] = 7; env2.runs[1] = case[1]
    stats_refresh("table")
    local tv = stats_show("table")
    has(tv.markdown, case[2] .. "**", "bold line over the cached table")
    has(tv.markdown, "`opus/medium", "cached rows stay")
    has(tv.markdown, "showing stats from", "age")
end

-- 10. Copy JSON copies the raw stdout; the nav carries every action of the design.
do
    local _, env = setup{ runs = { ok(TIER30) } }
    ledger_stats()
    stats_copy("overview")
    h.eq(env.clipboard, TIER30, "raw JSON on the clipboard")
    local ids = {}
    for _, it in ipairs(env.window.items) do
        if it.actions then ids[#ids + 1] = it.actions[1].id .. ":" .. tostring(it.actions[1].value) end
    end
    h.eq(table.concat(ids, " "), "stats_show:trends stats_show:table stats_window:7d stats_window:90d "
        .. "stats_refresh:overview stats_copy:overview", "overview actions")
end

print("init.test.lua: all passed")
