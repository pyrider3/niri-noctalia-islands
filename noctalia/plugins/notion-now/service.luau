--!nonstrict
-- Route plugin messages through the desktop notification daemon (notifd) instead of Noctalia's own toast.
local function notifyViaDaemon(title, body)
    noctalia.runAsync({"notify-send", "-a", "Notion Now", tostring(title or ""), tostring(body or "")})
end

local preferences = require("./preferences.luau")
local cache = noctalia.expandPath("~/.local/state/notion-now/events.json")
if noctalia.readFile(noctalia.expandPath("~/.config/systemd/user/notion-now-alarm.service")) then
    noctalia.runAsync({"systemctl", "--user", "start", "notion-now-alarm.service"})
else
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/alarm_service.py"})
end
local previousTime = nil
local previousEvents = {}
function update()
    local now = noctalia.nowMs() / 1000
    local raw = noctalia.readFile(cache)
    local data = raw and noctalia.json.decode(raw)
    if type(data) ~= "table" then previousTime = nil return end
    local starts, ends = {}, {}
    local healthy = now - (data.updated or 0) <= 600
    local events = {}
    for _, e in ipairs(data.events or {}) do
        events[e.id] = e
        local status = (data.sources or {})[e.provider] or {}
        if previousTime and now >= previousTime and now - previousTime <= 60
            and healthy and status.ok and not e.stale and not e.all_day and not e.point then
            local old = previousEvents[e.id]
            -- Only a clock crossing a known unchanged boundary triggers a reminder.
            if old and old.start == e.start and old["end"] == e["end"] then
                if previousTime < e.start and e.start <= now then table.insert(starts, e.title) end
                if previousTime < e["end"] and e["end"] <= now then table.insert(ends, e.title) end
            end
        end
    end
    -- Event start/end is announced by the Notion island's own banner; no separate desktop notification.
    previousTime, previousEvents = now, events
end
function onIpc(event)
    if event == "health" then
        update()
        noctalia.writeFile(noctalia.expandPath("~/.local/state/notion-now/service-health.json"),
            noctalia.json.encode({ok = true, timestamp = noctalia.nowMs()}))
    end
end
noctalia.setUpdateInterval(5000)
update()
