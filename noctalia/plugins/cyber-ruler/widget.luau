--!nonstrict
-- One companion and stream per output; monitor-local workspace IDs are authoritative.
local output = barWidget.outputName() or "default"
local safe = string.gsub(output, "[^%w_-]", "_")
local dir = noctalia.pluginDataDir() .. "/" .. safe
noctalia.mkdirAll(dir)
local input = {session = tostring(noctalia.nowMs()), serial = 0, hover = -1, hover_y = 0}
local visualScale = 1
local lastStart, lastSend, lastSize, lastTip = 0, 0, nil, nil
local evDir = dir .. "/events"
local evOn, evStart, evSkin, evSent = false, 0, 0, ""
local evInput = {width = 300, height = 42, text = "#ffffff", accent = "#3584e4"}
local function singleLane() return input.theme == "islands" or input.theme == "filmstrip" or input.theme == "merged" end
local function send()
    input.heartbeat = noctalia.nowMs() / 1000
    noctalia.writeFile(dir .. "/input.json", noctalia.json.encode(input))
end
local function configure()
    input.width = math.clamp(tonumber(noctalia.getConfig("width")) or 300, 180, 520)
    input.theme = noctalia.getConfig("theme") or "classic"
    visualScale = input.theme ~= "classic" and math.clamp(tonumber(noctalia.getConfig("size_percent")) or 100, 80, 160) / 100 or 1
    input.dot_size_percent = math.clamp(tonumber(noctalia.getConfig("dot_size_percent")) or 100, 50, 200)
    input.tick_width_percent = math.clamp(tonumber(noctalia.getConfig("tick_width_percent")) or 125, 50, 250)
    input.accent = noctalia.getConfig("accent") or "#63f5e3"
    input.accent_source = noctalia.getConfig("accent_source") or "default"
    input.accent_custom = noctalia.getConfig("accent_custom") or "#ff8fb8"
    input.show_windows = noctalia.getConfig("show_windows") ~= false
    input.animate = noctalia.getConfig("animate") ~= false
    input.show_app = noctalia.getConfig("show_app") ~= false
    input.events = noctalia.getConfig("events") == true
    input.panel = noctalia.getConfig("panel") == true and (noctalia.getConfig("theme") or "classic") == "merged"
    input.island = noctalia.getConfig("island") == true and input.theme == "merged"
    evOn = input.events and input.theme ~= "merged"
    input.duration = math.clamp(tonumber(noctalia.getConfig("duration")) or 320, 120, 800)
    send()
end
local function evWrite()
    local raw = noctalia.json.encode(evInput)
    if raw ~= evSent then noctalia.writeFile(evDir .. "/input.json", raw) evSent = raw end
end
local panelStart, panelAlive = 0, noctalia.expandPath("~/.local/state/cyber-ruler/panel-alive.json")
local function ensurePanel(now)
    if not input.panel or now - panelStart < 6000 then return end
    local raw = noctalia.readFile(panelAlive)
    local v = raw and noctalia.json.decode(raw) or {}
    if type(v) ~= "table" then v = {} end
    if now / 1000 - (v.t or 0) > 4 then
        noctalia.runAsync({"python3", noctalia.pluginDir() .. "/ruler_panel.py"})
        panelStart = now
    end
end
local function startEvents()
    noctalia.mkdirAll(evDir)
    evWrite()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/events_overlay.py", "--state", evDir})
    evStart = noctalia.nowMs()
end
local function start()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/ruler.py", "--state", dir, "--output", output})
    lastStart = noctalia.nowMs()
end
function pointer(normX, normY)
    input.hover = tonumber(normX) or -1
    input.hover_y = tonumber(normY) or 0
    send()
end
function leave()
    input.hover = -1
    send()
end
local function command(kind, value)
    input.serial += 1
    input.command = {kind = kind, value = value, at = noctalia.nowMs() / 1000}
    send()
end
local function windowLane(axis)
    return input.show_windows and (input.hover_y >= (input.theme == "aviation" and 13/42 or 14/38) or axis == "horizontal")
end
function onClick()
    if singleLane() then
        if input.hover >= 0 then command((input.show_windows or input.theme == "merged") and "window-click" or "click", input.hover) end
        return
    end
    if input.hover >= 0 then command(windowLane() and "window-click" or "click", input.hover) end
end
function onScroll(axis, steps, startsGesture)
    if singleLane() then
        if startsGesture and steps ~= 0 then command(axis == "horizontal" and input.show_windows and "window-step" or "step", steps > 0 and 1 or -1) end
        return
    end
    if startsGesture and steps ~= 0 then command(windowLane(axis) and "window-step" or "step", steps > 0 and 1 or -1) end
end
function onRightClick() noctalia.openSettings() end
function onConfigChanged() configure() end
function onExit()
    input.heartbeat = 0
    noctalia.writeFile(dir .. "/input.json", noctalia.json.encode(input))
end
function update()
    local now = noctalia.nowMs()
    ensurePanel(now)
    if now-lastSend > 1000 then send() lastSend = now end
    local raw = noctalia.readFile(dir .. "/status.json")
    local status = raw and noctalia.json.decode(raw) or {}
    if type(status) ~= "table" then status = {} end
    if now - (status.updated or 0)*1000 > 4000 and now-lastStart > 6000 then start() end
    local width = input.width
    local height = input.show_windows and (input.theme == "classic" and 38 or 42) or 30
    local displayWidth, displayHeight = width * visualScale, height * visualScale
    if evOn then
        if now - evSkin > 1000 then
            evInput.text = noctalia.getColor("on_surface") or "#ffffff"
            evInput.accent = noctalia.getColor("primary") or "#3584e4"
            evSkin = now
        end
        evInput.width, evInput.height = displayWidth, displayHeight
        evWrite()
        local er = noctalia.readFile(evDir .. "/status.json")
        local es = er and noctalia.json.decode(er) or {}
        if type(es) ~= "table" then es = {} end
        if now - (es.updated or 0) * 1000 > 4000 and now - evStart > 6000 then startEvents() end
    elseif evSent ~= "off" then
        noctalia.mkdirAll(evDir)
        noctalia.writeFile(evDir .. "/input.json", '{"off": true}')
        evSent = "off"
    end
    local size = tostring(displayWidth) .. ":" .. tostring(displayHeight) .. (evOn and ":e" or "")
    if size ~= lastSize then
        local layers = {ui.pixelStream({key = "ruler-pixels", path = dir .. "/canvas.sock", width = displayWidth, height = displayHeight})}
        if evOn then
            layers[#layers + 1] = ui.pixelStream({key = "ruler-events", path = evDir .. "/canvas.sock", width = displayWidth, height = displayHeight})
        end
        layers[#layers + 1] = ui.graph({key = "ruler-pointer", width = displayWidth, height = displayHeight, values = {}, color = "#00000000", fillOpacity = 0,
                onPointerMove = "pointer", onPointerLeave = "leave"})
        barWidget.render(ui.row({key = "ruler", gap = -displayWidth, align = "center"}, layers))
        lastSize = size
    end
    local help = (singleLane()) and "点击窗口缩影切换 · 纵向滚轮切工作区 · 横向滚轮切窗口 · 右键设置" or "上排切工作区 · 下排切窗口 · 滚轮随所在行切换 · 右键设置"
    local tip = (status.tooltip or "连接 Niri 工作区…") .. "\n" .. help
    if tip ~= lastTip then barWidget.setTooltip(tip) lastTip = tip end
end
configure()
start()
if evOn then startEvents() end
noctalia.setUpdateInterval(250)
update()
