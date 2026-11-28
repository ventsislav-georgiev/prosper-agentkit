-- Ledger Stats: one window over `todo.py stats --all --json` (schema 1). The kit's pieces need no Lua; this is
-- only the stats view. Screens: KPI grid (overview), Trends (one chart), Per tier / Per project (monospaced table).
-- Each button's id names the global below that builds the next screen.

local EXT_ID = "io.github.ventsislav-georgiev.prosper-agentkit"
local SCHEMA = 1
local WINDOWS = { "7d", "30d", "90d" }
local MAX_DAYS = 90 -- chart points per series

local function home() return host.env.get("HOME") or "" end
-- The ledger-tools shim: it runs todo.py through prosper-kit-run, which loads the kit settings (KIT_LEDGER_DB).
local function todo_path() return home() .. "/.config/prosper/kits/" .. EXT_ID .. "/bin/todo.py" end
-- Saving the kit settings rewrites this file, so a new ledger_db path invalidates the cache too.
local function settings_path() return home() .. "/.config/prosper-agentkit/.settings.env" end

local function pref(k, ok, default)
    local v = host.prefs.get(k)
    for _, o in ipairs(ok) do if v == o then return v end end
    return default
end
local function since() return pref("stats.since", WINDOWS, "30d") end
local function by() return pref("stats.by", { "tier", "project" }, "tier") end
local function cache_key() return "stats.cache." .. since() .. "." .. by() end

local function num(x) return type(x) == "number" and x == x and x ~= math.huge and x ~= -math.huge end
local function fmt(x)
    if not num(x) then return "-" end
    if x == math.floor(x) and math.abs(x) < 1e9 then return string.format("%d", x) end
    local s = string.format(math.abs(x) < 10 and "%.2f" or "%.1f", x)
    return (s:gsub("0+$", ""):gsub("%.$", ""))
end
local function dist(d, unit)
    d = type(d) == "table" and d or {}
    if not num(d.p50) then return "-" end
    unit = unit or ""
    return fmt(d.p50) .. unit .. " (" .. fmt(d.p90) .. unit .. ")"
end
local function tbl(x) return type(x) == "table" and x or {} end

local function mtime(p)
    local a = host.fs.attributes(p)
    return (type(a) == "table" and a.exists) and tostring(a.mtime) or "-"
end
local function stamp(db) return mtime(db) .. "|" .. mtime(db .. "-wal") .. "|" .. mtime(settings_path()) end

local function age(at)
    local s = math.max(0, host.time() - (tonumber(at) or 0))
    if s < 60 then return "under a minute" end
    if s < 3600 then return math.floor(s / 60) .. " min" end
    if s < 86400 then return math.floor(s / 3600) .. " h" end
    return math.floor(s / 86400) .. " d"
end

local function read_cache()
    local s = host.prefs.get(cache_key())
    local c = type(s) == "string" and s ~= "" and host.json.decode(s) or nil
    if type(c) ~= "table" or type(c.raw) ~= "string" then return nil end
    c.data = host.json.decode(c.raw)
    if type(c.data) ~= "table" then return nil end
    return c
end

local function first_line(s) return (tostring(s or ""):match("[^\n]*%S[^\n]*") or ""):gsub("^%s+", "") end

-- The current stats: the cache when the ledger (and its -wal, and the kit settings) did not change since it was
-- made, else one todo.py run. Returns { kind = "ok"|"noledger"|"noaccess"|"failed"|"schema", line =, cache = }.
local function stats_load()
    local c = read_cache()
    local pre = c and type(c.db) == "string" and stamp(c.db) or nil
    if c and pre == c.stamp then return { kind = "ok", cache = c } end
    local r = host.process.run{ argv = { todo_path(), "stats", "--all", "--since", since(), "--by", by(), "--json" },
                                timeout = 10, max_bytes = 1048576 }
    local function fail(kind, line) return { kind = kind, line = line, cache = c, stale = c ~= nil } end
    if r.error then
        if r.error:find("restricted to system extensions", 1, true) then return fail("noaccess") end
        return fail("failed", r.error)
    end
    if r.timed_out then return fail("failed", "timed out after 10 s") end
    if r.status == 4 then
        return fail("noledger", tostring(r.stderr or ""):match("no ledger at ([^\n]+)") or "the configured path")
    end
    if not r.ok then
        local l = first_line(r.stderr)
        return fail("failed", l ~= "" and l or ("exit " .. tostring(r.status)))
    end
    if r.truncated then return fail("failed", "the output passed 1 MiB") end
    local d = host.json.decode(r.stdout or "")
    if type(d) ~= "table" or type(d.totals) ~= "table" then return fail("failed", "the JSON did not decode") end
    if not num(d.schema) or d.schema > SCHEMA then return fail("schema") end
    local db = type(d.database) == "string" and d.database or ""
    local n = { raw = r.stdout, at = host.time(), db = db,
                stamp = (pre and c.db == db) and pre or stamp(db) }
    host.prefs.set(cache_key(), host.json.encode(n))
    n.data = d
    return { kind = "ok", cache = n }
end

-- One line per problem, shown above whatever cached data there is.
local function notes(st)
    local out = {}
    if st.kind == "noaccess" then
        out[#out + 1] = "Stats need System Access for the kit (Settings > Extensions)"
    elseif st.kind == "failed" then
        out[#out + 1] = "stats failed: " .. st.line
    elseif st.kind == "schema" then
        out[#out + 1] = "These stats are newer than this view: Update the kit"
    end
    if st.stale then out[#out + 1] = "showing stats from " .. age(st.cache.at) .. " ago" end
    return out
end

local function act(id, title, value, icon) return { id = id, title = title, value = value, icon = icon } end

local function nav(screen)
    local a = {}
    if screen ~= "overview" then a[#a + 1] = act("stats_show", "Overview", "overview", "square.grid.2x2") end
    if screen ~= "trends" then a[#a + 1] = act("stats_show", "Trends", "trends", "chart.xyaxis.line") end
    local other = by() == "tier" and "project" or "tier"
    if screen == "table" then
        a[#a + 1] = act("stats_group", "Per " .. other, other, "tablecells")
    else
        a[#a + 1] = act("stats_show", "Per " .. by(), "table", "tablecells")
    end
    for _, w in ipairs(WINDOWS) do
        if w ~= since() then a[#a + 1] = act("stats_window", "Last " .. w, w, "calendar") end
    end
    a[#a + 1] = act("stats_refresh", "Refresh", screen, "arrow.clockwise")
    a[#a + 1] = act("stats_copy", "Copy JSON", screen, "doc.on.doc")
    return a
end

-- A whole-window message (no data at all): never a blank view.
local function message(lines, extra)
    local a = extra or {}
    a[#a + 1] = act("stats_refresh", "Refresh", "overview", "arrow.clockwise")
    return host.ui.detail{ title = "Ledger stats", markdown = table.concat(lines, "\n\n"), actions = a }
end

local function header(d)
    local sc = tbl(d.scope)
    return "Ledger stats · " .. since() .. " since " .. tostring(sc.since or ""):sub(1, 10)
end

local function estimated(t)
    return (num(tbl(t.review).estimated) and t.review.estimated > 0) or (num(tbl(t.prs).estimated) and t.prs.estimated > 0)
end
local function tilde(x) return num(x) and x > 0 and "~" or "" end

local function overview(st)
    local d = st.cache.data
    local t = tbl(d.totals)
    local r, pr, cm, q, fl = tbl(t.review), tbl(t.prs), tbl(t.commits), tbl(t.questions), tbl(t.flow)
    local closed = num(t.closed) and t.closed or 0
    local none = closed == 0
    local function v(s) return none and "-" or s end
    local fail = num(r.fail_rate) and (tilde(r.estimated) .. fmt(100 * r.fail_rate) .. "% (" .. fmt(r.fail) .. "/" .. fmt(r.verdicts) .. ")") or "-"
    local items = {}
    for _, line in ipairs(notes(st)) do
        items[#items + 1] = { id = "note" .. #items, title = line, icon = "exclamationmark.triangle" }
    end
    local function tile(id, title, sub, icon) items[#items + 1] = { id = id, title = title, subtitle = sub, icon = icon } end
    tile("closed", "Closed per day", v(fmt(closed) .. " closed · " .. dist(fl.closes_per_day)), "checkmark.circle")
    tile("cycle", "Cycle time", v(dist(t.cycle_h, " h")), "timer")
    tile("lead", "Lead time", v(dist(t.lead_h, " h")), "hourglass")
    tile("fail", "Review fail rate", v(fail), "xmark.seal")
    tile("dispatch", "Dispatches per closed", v(dist(t.dispatches_per_closed)), "arrow.triangle.branch")
    tile("prs", "PRs landed per day", v(tilde(pr.estimated) .. dist(pr.per_day) .. " · " .. fmt(pr.landed) .. " PRs + "
        .. fmt(cm.landed) .. " commits"), "arrow.triangle.merge")
    tile("oq", "OQ per 100 closed", v(fmt(q.per_100_closed) .. " · ruling " .. dist(q.ask_to_rule_h, " h")), "questionmark.bubble")
    tile("wip", "WIP now", fmt(fl.wip_now), "hammer")
    tile("parked", "Parked now", fmt(tbl(t.parked).now), "parkingsign.circle")
    if none then
        local longer = since() == "7d" and "30d" or "90d"
        items[#items + 1] = { id = "none", title = "no closed entries since " .. tostring(tbl(d.scope).since or ""):sub(1, 10),
            subtitle = since() ~= "90d" and ("try the last " .. longer) or nil, icon = "calendar.badge.exclamationmark",
            actions = since() ~= "90d" and { act("stats_window", "Last " .. longer, longer) } or nil }
    end
    if estimated(t) then
        items[#items + 1] = { id = "estimated", title = "~ estimated from free text",
            subtitle = "entries closed before structured review events", icon = "info.circle" }
    end
    for _, a in ipairs(nav("overview")) do
        items[#items + 1] = { id = "nav." .. a.title, title = a.title, icon = a.icon, actions = { a } }
    end
    return host.ui.grid{ title = header(d), columns = 3, items = items }
end

local SERIES = { { "closed", "Closed" }, { "closed_sweep", "Sweeps" }, { "wip", "WIP" }, { "prs", "PRs" },
                 { "commits", "Commits" }, { "verdicts", "Verdicts" }, { "fail", "Fails" }, { "asked", "OQ asked" } }

local function trends(st)
    local daily = tbl(st.cache.data.daily)
    local from = math.max(1, #daily - MAX_DAYS + 1)
    local series = {}
    for _, s in ipairs(SERIES) do
        local pts = {}
        for i = from, #daily do
            local row = tbl(daily[i])
            if num(row[s[1]]) then pts[#pts + 1] = { x = tostring(row.day or ""):sub(6), y = row[s[1]] } end
        end
        series[#series + 1] = { name = s[2], points = pts }
    end
    local n = notes(st)
    local title = header(st.cache.data) .. (#n > 0 and (" · " .. table.concat(n, " · ")) or "")
    return host.ui.chart{ title = title, kind = "line", x_label = "Day", y_label = "Count", series = series,
                          empty_text = "No days in this window" }
end

local function cell(s, w) s = tostring(s):gsub("`", "'"); return s .. string.rep(" ", math.max(1, w - #s)) end

local function table_view(st)
    local d = st.cache.data
    local cols = { { by(), 16 }, { "closed", 8 }, { "cycle p50 (p90) h", 19 }, { "disp/closed", 13 },
                   { "fail", 7 }, { "reviews/close", 15 }, { "$/closed", 14 }, { "tokens/closed", 0 } }
    local function row(vals)
        local s = ""
        for i, c in ipairs(cols) do s = s .. cell(vals[i], c[2]) end
        return "`" .. s:gsub("%s+$", "") .. "`"
    end
    local hdr = {}
    for i, c in ipairs(cols) do hdr[i] = c[1] end
    local lines = {}
    for _, l in ipairs(notes(st)) do lines[#lines + 1] = "**" .. l .. "**" end
    lines[#lines + 1] = header(d)
    lines[#lines + 1] = ""
    lines[#lines + 1] = row(hdr)
    local groups = tbl(d.groups)
    for _, g in ipairs(groups) do
        g = tbl(g)
        local r, sp = tbl(g.review), g.spend
        local has = type(sp) == "table" and type(sp.usd_per_closed) == "table"
        lines[#lines + 1] = row{ g.key or "-", fmt(g.closed), dist(g.cycle_h), dist(g.dispatches_per_closed),
            num(r.fail_rate) and (tilde(r.estimated) .. fmt(100 * r.fail_rate) .. "%") or "-",
            dist(r.reviews_before_close), has and dist(sp.usd_per_closed) or "-", has and dist(sp.tokens_per_closed) or "-" }
    end
    if #groups == 0 then lines[#lines + 1] = "no closed entries, reviews or parks in this window" end
    lines[#lines + 1] = ""
    if by() == "tier" then
        lines[#lines + 1] = "Tiers are not assigned at random: harder entries go to stronger tiers, so a gap between rows is not the tier alone."
    else
        lines[#lines + 1] = "Projects differ in size and kind of work: compare a project with itself over time first."
    end
    if estimated(tbl(d.totals)) then lines[#lines + 1] = "~ estimated from free text" end
    return host.ui.detail{ title = "Per " .. by(), markdown = table.concat(lines, "\n"), actions = nav("table") }
end

local function screen(st, which)
    if st.kind == "noledger" then
        return message({ "No ledger at " .. st.line .. ". Set the ledger path in the kit's Settings." },
                       { act("stats_settings", "Open Settings", "", "gearshape") })
    end
    if not st.cache then
        local n = notes(st)
        return message(#n > 0 and n or { "No stats yet." })
    end
    if which == "trends" then return trends(st) end
    if which == "table" then return table_view(st) end
    return overview(st)
end

local last -- the state the current screen was built from, so navigation runs nothing

-- Command: open the window from the cache at once, then replace it once the stats are current.
function ledger_stats()
    local c = read_cache()
    host.window.open(c and overview({ kind = "ok", cache = c })
        or host.ui.loading{ title = "Ledger stats", subtitle = "Running todo.py stats" })
    last = stats_load()
    host.window.open(screen(last, "overview"))
end

-- Buttons. Each returns the next screen (the window shows a spinner meanwhile).
function stats_show(value)
    last = last or stats_load()
    return screen(last, value)
end
function stats_refresh(value)
    last = stats_load()
    return screen(last, value)
end
function stats_window(value)
    host.prefs.set("stats.since", value)
    last = stats_load()
    return screen(last, "overview")
end
function stats_group(value)
    host.prefs.set("stats.by", value)
    last = stats_load()
    return screen(last, "table")
end
function stats_copy(value)
    last = last or stats_load()
    if last.cache then host.clipboard.write(last.cache.raw) end
    return screen(last, value)
end
function stats_settings()
    host.settings.open("kit")
    last = last or stats_load()
    return screen(last, "overview")
end

return {}
