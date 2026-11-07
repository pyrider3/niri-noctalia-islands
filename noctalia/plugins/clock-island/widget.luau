--!nonstrict
-- Bar clock (animated, drawn by clock_canvas.py). A click asks clock_island.py to expand the calendar island.
local state = noctalia.expandPath("~/.local/state/clock-island/")
local H = 28
local curW = 70
local lastStart, lastIsland, seq = 0, 0, 0
local lastCfg = nil
local lastCfgCheck = 0
local function render(w)
    curW = w
    barWidget.render(ui.pixelStream({key = "clock-pixels", path = state .. "canvas.sock", width = w, height = H}))
end
local function startCanvas()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/clock_canvas.py"})
    lastStart = noctalia.nowMs()
end
local function startIsland()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/clock_island.py"})
    lastIsland = noctalia.nowMs()
end
local function send(cmd)
    seq = noctalia.nowMs()
    noctalia.writeFile(state .. "cmd.json", noctalia.json.encode({seq = seq, cmd = cmd}))
end
function onClick() send("toggle") end
function onRightClick() send("today") end
local function syncConfig(now)
    if now - lastCfgCheck < 700 then return end
    lastCfgCheck = now
    local function num(k, d)
        local v = tonumber(noctalia.getConfig(k))
        if v == nil then return d end
        return math.floor(v)
    end
    local sec = noctalia.getConfig("show_seconds")
    local auto = noctalia.getConfig("pomo_auto")
    local cfg = {
        show_seconds = (sec == true or sec == "true"),
        pomo_focus = num("pomo_focus", 25),
        pomo_short = num("pomo_short", 5),
        pomo_long = num("pomo_long", 15),
        pomo_auto = not (auto == false or auto == "false"),
    }
    local enc = noctalia.json.encode(cfg)
    if enc ~= lastCfg then
        lastCfg = enc
        noctalia.writeFile(state .. "config.json", enc)
    end
end
function update()
    local now = noctalia.nowMs()
    syncConfig(now)
    local raw = noctalia.readFile(state .. "status.json")
    local v = raw and noctalia.json.decode(raw) or {}
    if type(v) ~= "table" then v = {} end
    if now - (v.updated or 0) * 1000 > 3000 and now - lastStart > 5000 then startCanvas() end
    local w = math.floor(tonumber(v.width) or 70)
    if w ~= curW and w >= 40 then render(w) end
    local araw = noctalia.readFile(state .. "alive.json")
    local a = araw and noctalia.json.decode(araw) or {}
    if type(a) ~= "table" then a = {} end
    if now - (a.t or 0) * 1000 > 4000 and now - lastIsland > 6000 then startIsland() end
end
render(70)
startCanvas()
startIsland()
noctalia.setUpdateInterval(16)
update()
