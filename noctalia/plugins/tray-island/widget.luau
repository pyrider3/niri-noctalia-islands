--!nonstrict
local state = noctalia.expandPath("~/.local/state/tray-island/")
local W, H = 38, 28
local input = {hovered = false, x = 0, text = "#e9e9e6", press = ""}
local lastStart, lastSkin, lastIsland, lastX = 0, 0, 0, -1
local dirty = false
local pressSeq = 0
local function send()
    noctalia.writeFile(state .. "input.json", noctalia.json.encode(input))
    dirty = false
end
local function start()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/tray_canvas.py"})
    lastStart = noctalia.nowMs()
end
local function startIsland()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/tray_island.py"})
    lastIsland = noctalia.nowMs()
end
function trayMove(nx, ny)
    local x = tonumber(nx) or 0
    if not input.hovered or math.abs(x - lastX) > 0.004 then
        input.hovered = true
        input.x = x
        lastX = x
        dirty = true
    end
end
function trayLeave()
    if input.hovered then input.hovered = false lastX = -1 dirty = true end
end
function onClick()
    pressSeq = pressSeq + 1
    if input.x * W < W / 2 then
        input.press = "c" .. pressSeq
        noctalia.writeFile(state .. "island-cmd.json", noctalia.json.encode({seq = noctalia.nowMs(), cmd = "toggle"}))
    else
        input.press = "i" .. pressSeq
        noctalia.runAsync({"fcitx5-remote", "-t"})
    end
    dirty = true
end
function onRightClick() end
function update()
    local now = noctalia.nowMs()
    if now - lastSkin > 1000 then
        input.text = noctalia.getColor("on_surface") or "#e9e9e6"
        lastSkin = now
        dirty = true
    end
    if dirty then send() end
    local raw = noctalia.readFile(state .. "status.json")
    local value = raw and noctalia.json.decode(raw) or {}
    if type(value) ~= "table" then value = {} end
    if now - (value.updated or 0) * 1000 > 3000 and now - lastStart > 5000 then start() end
    local araw = noctalia.readFile(state .. "island-alive.json")
    local alive = araw and noctalia.json.decode(araw) or {}
    if type(alive) ~= "table" then alive = {} end
    if now - (alive.t or 0) * 1000 > 4000 and now - lastIsland > 6000 then startIsland() end
end
barWidget.render(ui.row({key = "tray-island", gap = -W, align = "center"}, {
    ui.pixelStream({key = "tray-pixels", path = state .. "canvas.sock", width = W, height = H}),
    ui.graph({key = "tray-hover", width = W, height = H, values = {}, color = "#00000000", fillOpacity = 0,
        onPointerMove = "trayMove", onPointerLeave = "trayLeave"}),
}))
barWidget.setTooltip("托盘 · 点 ∨ 展开，点输入法切换中英")
start()
noctalia.setUpdateInterval(16)
update()
