--!nonstrict
local preferences = require("./preferences.luau")
local state = noctalia.expandPath("~/.local/state/notion-now/")
local input = {session = noctalia.nowMs(), wheel = 0, hovered = false}
local lastWidth, lastColor, lastTooltip = nil, nil, nil
local lastSkin, lastStart = 0, 0
local color = "on_surface"
local function sendInput()
    noctalia.writeFile(state .. "bar-input.json", noctalia.json.encode(input))
end
local function start()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/bar_canvas.py"})
    lastStart = noctalia.nowMs()
end
local lastIsland = 0
local function startIsland()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/notion_island.py"})
    lastIsland = noctalia.nowMs()
end
function barHover(value)
    input.hovered = value == "true" or value == true
    sendInput()
end
function onHover(value)
    barHover(value)
end
function onScroll(axis, steps, startsGesture)
    input.wheel = input.wheel + (tonumber(steps) or 0)
    sendInput()
end
function update()
    local now = noctalia.nowMs()
    if now - lastSkin > 1000 then
        local prefs = preferences.read()
        local foreground = noctalia.getColor("on_surface") or "#e9e9e6"
        local accent = noctalia.getColor("primary") or "#edb69b"
        noctalia.writeFile(state .. "bar-skin.json", noctalia.json.encode({text = foreground, accent = accent}))
        color = prefs.accent_color and "primary" or "on_surface"
        lastSkin = now
    end
    local raw = noctalia.readFile(state .. "bar-status.json")
    local status = raw and noctalia.json.decode(raw) or {}
    if type(status) ~= "table" then status = {} end
    if now - (status.updated or 0) * 1000 > 3000 and now - lastStart > 5000 then start() end
    local araw = noctalia.readFile(state .. "island-alive.json")
    local alive = araw and noctalia.json.decode(araw) or {}
    if type(alive) ~= "table" then alive = {} end
    if now - (alive.t or 0) * 1000 > 4000 and now - lastIsland > 6000 then startIsland() end
    local width = math.max(86, math.min(760, tonumber(status.width) or 122))
    if width ~= lastWidth or color ~= lastColor then
        -- the calendar icon is drawn inside the canvas now (it carries the island's position marker)
        barWidget.render(ui.row({key = "primary-activity", gap = 0, align = "center"}, {
            ui.pixelStream({key = "bar-canvas", path = state .. "bar.sock", width = width, height = 28}),
        }))
        lastWidth, lastColor = width, color
    end
    local tooltip = (status.tooltip or "正在连接 Notion 日程") .. "\n滚轮切换活动 · 点击查看时间轴 · 右键设置"
    if tooltip ~= lastTooltip then barWidget.setTooltip(tooltip) lastTooltip = tooltip end
end
-- the agenda "panel" is now the dynamic island (notion_island.py): a click sends it a command
function onClick()
    noctalia.writeFile(state .. "island-cmd.json", noctalia.json.encode({seq = noctalia.nowMs(), cmd = "toggle"}))
end
-- right-click opens the island straight on its settings page
function onRightClick()
    noctalia.writeFile(state .. "island-cmd.json", noctalia.json.encode({seq = noctalia.nowMs(), cmd = "settings"}))
end
function onIpc(event)
    if event == "health" then
        update()
        noctalia.writeFile(state .. "widget-health.json", noctalia.json.encode({ok = true, timestamp = noctalia.nowMs()}))
    end
end
sendInput()
start()
noctalia.setUpdateInterval(16)
update()
