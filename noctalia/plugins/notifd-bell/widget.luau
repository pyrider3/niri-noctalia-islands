--!nonstrict
-- Notification bell for notifd (~/.config/notifd): custom-drawn and animated. In the "capsule" notification
-- style the bell stretches into a capsule that shows the notification; the width comes from the render daemon.
local state = noctalia.expandPath("~/.local/state/notifd-bell/")
local notifState = noctalia.expandPath("~/.local/state/notifd/state.json")
local H = 28
local curW = 28
local lastStart, lastTip, last = 0, nil, ""
local function call(method, sig, arg)
    local argv = {"busctl", "--user", "call", "dev.pr.Notifd", "/dev/pr/Notifd", "dev.pr.Notifd", method}
    if sig then argv[#argv + 1] = sig argv[#argv + 1] = arg end
    noctalia.runAsync(argv)
end
local function render(w)
    curW = w
    barWidget.render(ui.pixelStream({key = "bell-pixels", path = state .. "canvas.sock", width = w, height = H}))
end
local function start()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/bell_canvas.py"})
    lastStart = noctalia.nowMs()
end
function onClick() call("BellClick") end
function onRightClick() call("ToggleDND") end
function onHover(entered)
    call("BellHover", "b", (entered == true or entered == "true") and "true" or "false")
end
local themeFile = noctalia.expandPath("~/.local/state/notifd/theme.json")
local lastCfg = nil
local lastCfgCheck = 0
local function themeTable()
    local raw = noctalia.readFile(themeFile)
    local v = raw and noctalia.json.decode(raw)
    return type(v) == "table" and v or {}
end
-- The Noctalia settings are the source of truth: on start and whenever they change, hand them to notifd.
local function syncStyle(now)
    if now - lastCfgCheck < 700 then return end
    lastCfgCheck = now
    local style = noctalia.getConfig("style")
    if type(style) ~= "string" then return end
    local snd = noctalia.getConfig("sound")
    local eff = noctalia.getConfig("sound_effect")
    local want = {style = style, sound = not (snd == false or snd == "false"), effect = type(eff) == "string" and eff or "message"}
    local sig = noctalia.json.encode(want)
    if sig ~= lastCfg then
        lastCfg = sig
        local cur = themeTable()
        if cur.style ~= want.style or cur.sound ~= want.sound or cur.effect ~= want.effect then
            cur.style, cur.sound, cur.effect = want.style, want.sound, want.effect
            noctalia.writeFile(themeFile, noctalia.json.encode(cur))
        end
    end
end
function update()
    local now = noctalia.nowMs()
    syncStyle(now)
    local raw = noctalia.readFile(state .. "status.json")
    local v = raw and noctalia.json.decode(raw) or {}
    if type(v) ~= "table" then v = {} end
    if now - (v.updated or 0) * 1000 > 3000 and now - lastStart > 5000 then start() end
    local w = math.floor(tonumber(v.width) or 28)
    if w ~= curW and w >= 28 then render(w) end
    local nraw = noctalia.readFile(notifState)
    if nraw and nraw ~= last then
        last = nraw
        local s = noctalia.json.decode(nraw)
        if type(s) == "table" then
            local tip = "通知 " .. tostring(s.count or 0) .. " 条"
            if (tonumber(s.unread) or 0) > 0 then tip = tip .. "，未读 " .. tostring(s.unread) end
            if s.dnd then tip = tip .. " · 勿扰中" end
            if tip ~= lastTip then barWidget.setTooltip(tip .. "\n左键：通知中心 · 右键：勿扰") lastTip = tip end
        end
    end
end
render(28)
start()
noctalia.setUpdateInterval(16)
update()
