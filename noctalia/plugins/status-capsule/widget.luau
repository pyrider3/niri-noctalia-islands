--!nonstrict
local state = noctalia.expandPath("~/.local/state/status-capsule/")
local W, H = 152, 28
local input = {hovered = false, x = 0, scroll = 0, mclicks = 0, rclicks = 0}
local lastStart, lastSkin, lastTip, lastX = 0, 0, nil, -1
local dirty = false
local function send()
    noctalia.writeFile(state .. "input.json", noctalia.json.encode(input))
    dirty = false
end
local function start()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/capsule_canvas.py"})
    lastStart = noctalia.nowMs()
end
function capsuleMove(nx, ny)
    local x = tonumber(nx) or 0
    if not input.hovered or math.abs(x - lastX) > 0.004 then
        input.hovered = true
        input.x = x
        lastX = x
        dirty = true
    end
end
function capsuleLeave()
    if input.hovered then input.hovered = false lastX = -1 dirty = true end
end
function onScroll(axis, steps, startsGesture)
    input.scroll = input.scroll + (steps or 0)
    dirty = true
end
local lastCell = "wifi"
local lastIsland = 0
local function startIsland()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/status_island.py"})
    lastIsland = noctalia.nowMs()
end
function onClick()
    -- The render daemon publishes which cell the pointer is over.
    local raw = noctalia.readFile(state .. "cell.json")
    local v = raw and noctalia.json.decode(raw)
    if type(v) == "table" and type(v.cell) == "string" then lastCell = v.cell end
    -- the four panels are one dynamic island now (status_island.py); it opens on the clicked cell
    noctalia.writeFile(state .. "island-cmd.json", noctalia.json.encode({seq = noctalia.nowMs(), cmd = "open", cell = lastCell}))
end
function onMiddleClick() input.mclicks = input.mclicks + 1 dirty = true end
function onRightClick() input.rclicks = input.rclicks + 1 dirty = true end
function update()
    local now = noctalia.nowMs()
    if now - lastSkin > 1000 then
        input.accent = noctalia.getColor("primary") or "#edb69b"
        input.text = noctalia.getColor("on_surface") or "#e9e9e6"
        input.surface = noctalia.getColor("surface_container") or "#1a1a1f"
        input.bg = noctalia.getColor("surface") or "#101014"
        input.style = noctalia.getConfig("icon_style") or "line"
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
    local tip = value.tooltip or "状态胶囊"
    if tip ~= lastTip then barWidget.setTooltip(tip) lastTip = tip end
end
barWidget.render(ui.row({key = "status-capsule", gap = -W, align = "center"}, {
    ui.pixelStream({key = "status-pixels", path = state .. "canvas.sock", width = W, height = H}),
    -- Transparent graph tracks the pointer above the stream without taking clicks.
    ui.graph({key = "status-hover", width = W, height = H, values = {}, color = "#00000000", fillOpacity = 0,
        onPointerMove = "capsuleMove", onPointerLeave = "capsuleLeave"}),
}))
start()
noctalia.setUpdateInterval(16)
update()
