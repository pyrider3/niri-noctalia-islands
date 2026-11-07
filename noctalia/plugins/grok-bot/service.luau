--!nonstrict
-- Route plugin messages through the desktop notification daemon (notifd) instead of Noctalia's own toast.
local function notifyViaDaemon(title, body)
    noctalia.runAsync({"notify-send", "-a", "Grok Bot", tostring(title or ""), tostring(body or "")})
end

local model = require("./model.luau")
local base = noctalia.expandPath("~/.config/Grok Bot/")
local directory = base .. "sand-client-persistence/"
local rows, mtimes, activity, previous = {}, {}, {}, nil
local rosterStamp, rosterPath, lastGood = "", "", 0
local dataDir = noctalia.pluginDataDir()
local ticks = 0
local readState=require("./read_state.luau")
local savedReads=noctalia.readFile(dataDir.."/read-receipts.json")
local receipts=savedReads and noctalia.json.decode(savedReads)
noctalia.state.set("read_receipts",type(receipts)=="table" and receipts or {})
function update()
    local now = noctalia.nowMs()
    local files = noctalia.listDir(directory) or {}
    local newest, chosen = -1, ""
    for _, name in ipairs(files) do
        local key = model.key(name)
        if string.match(key, "%.roster%.last%-roster$") then
            local info = noctalia.fileInfo(directory .. name)
            if info and info.mtime > newest then newest, chosen = info.mtime, directory .. name end
        elseif string.find(key, ".transcript.replicas.", 1, true) then
            local id = string.match(key, "%.transcript%.replicas%.([%x%-]+)$")
            local info = id and noctalia.fileInfo(directory .. name)
            if info then
                local stamp = tostring(info.mtime) .. ":" .. tostring(info.size)
                if mtimes[name] and mtimes[name] ~= stamp then activity[id] = now end
                mtimes[name] = stamp
            end
        end
    end
    local error = ""
    if chosen ~= "" then
        local info = noctalia.fileInfo(chosen)
        local stamp = chosen .. ":" .. tostring(newest) .. ":" .. tostring(info and info.size)
        if stamp ~= rosterStamp then
            local raw = info and info.size <= 2097152 and noctalia.readFile(chosen)
            local parsed, err = model.parse(raw and noctalia.json.decode(raw))
            if parsed then rows, rosterStamp, rosterPath, lastGood = parsed, stamp, chosen, now
            else error = err or "暂时无法读取代理状态" end
        end
    else rows, rosterStamp, rosterPath = {}, "", "" end
    -- Never keep another account's rows after its roster has disappeared.
    if rosterPath ~= "" and not noctalia.fileExists(rosterPath) then rows = {} end
    if error ~= "" and now - lastGood > 15000 then rows = {} end
    local rawMarker = noctalia.readFile(base .. "desktop-status.json") or noctalia.readFile(base .. "sand-session-marker.json")
    local marker = rawMarker and noctalia.json.decode(rawMarker) or {}
    if type(marker) ~= "table" then marker = {} end
    local pid = tonumber(marker.pid)
    local process = pid and pid > 0 and noctalia.readFile("/proc/" .. tostring(math.floor(pid)) .. "/comm") or ""
    local running = string.find(process or "", "grok-bot", 1, true) ~= nil
    -- A fresh heartbeat is a fallback for builds without a PID in the marker.
    if not pid then running = (tonumber(marker.aliveAtMs) or 0) > now - 150000 end
    local bridgeRaw=noctalia.readFile(noctalia.expandPath("~/.local/state/noctalia-grok-bridge/status.json"))
    local bridge=bridgeRaw and noctalia.json.decode(bridgeRaw)
    local bridgeConnected=type(bridge)=="table" and bridge.ok==true and bridge.complete==true and now-(tonumber(bridge.updated) or 0)<6000
    local live={}
    if bridgeConnected then for _,a in ipairs(bridge.agents or {}) do live[a.id]=a end end
    for _,row in ipairs(rows) do
        row.runtimeKnown=live[row.id]~=nil
        row.runtimeRunning=live[row.id] and live[row.id].isRunning==true or false
    end
    local agents, counts, mood = model.decorate(readState.apply(rows,noctalia.state.get("read_receipts") or {}), activity, now,
        math.clamp(tonumber(noctalia.getConfig("working_window")) or 12, 3, 120) * 1000, running)
    local snapshot = {agents = agents, counts = counts, mood = mood, running = running,
        version = model.clean(marker.appVersion, 24), error = error, updated = now,
        bridgeConnected = bridgeConnected, schema = 4, installed = noctalia.commandExists("grok-bot")}
    noctalia.state.set("snapshot", snapshot)
    local current = {}
    for _, a in ipairs(agents) do
        current[a.id] = a.state .. ":" .. a.reason
        if previous and running and a.notify and noctalia.getConfig("notify_waiting") ~= false
            and a.waiting and previous[a.id] ~= current[a.id] then
            notifyViaDaemon("Grok Bot · " .. a.name .. " 等你处理", a.reason)
        end
    end
    previous = current
    ticks = ticks + 1
    if ticks == 1 or ticks % 10 == 0 then
        noctalia.writeFile(dataDir .. "/health.json", noctalia.json.encode({ok = true, updated = now,
            agents = counts.total, mood = mood, running = running, bridgeConnected = bridgeConnected, error = error}))
    end
end
function onIpc(event)
    if event == "focus" then
        require("./actions.luau").open()
    elseif event == "selftest" then
        local result = require("./tests.luau")()
        noctalia.writeFile(dataDir .. "/selftest.json", noctalia.json.encode(result))
    elseif event == "refresh" or event == "health" then rosterStamp = "" update() end
end
function onConfigChanged() update() end
-- Start once per service load. ensure does not focus or duplicate an existing app.
if noctalia.getConfig("autostart_bridge") ~= false then
    noctalia.runAsync({"node",noctalia.pluginDir().."/bridge.mjs","ensure"})
end
noctalia.setUpdateInterval(1000)
update()
