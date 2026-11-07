--!nonstrict
-- Center hub: niri workspace dots + column map; morphs briefly for volume / brightness / track / workspace changes.
local state = noctalia.expandPath("~/.local/state/center-hub/")
local H = 28
local input = {hovered = false, x = 0, accent = "#3584e4", text = "#ffffff"}
local lastWidth, lastStart, lastSkin, lastTip, lastX = 0, 0, 0, nil, -1
local dirty = false
local hits = {}
local function send()
    noctalia.writeFile(state .. "input.json", noctalia.json.encode(input))
    dirty = false
end
local function start()
    noctalia.mkdirAll(state)
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/hub_canvas.py"})
    lastStart = noctalia.nowMs()
end
local width = 120
function hubMove(nx, ny)
    local x = (tonumber(nx) or 0) * width
    if not input.hovered or math.abs(x - lastX) > 0.8 then
        input.hovered = true
        input.x = x
        lastX = x
        dirty = true
    end
end
function hubLeave()
    if input.hovered then input.hovered = false lastX = -1 dirty = true end
end
local function act(args)
    local cmd = {"niri", "msg", "action"}
    for _, a in ipairs(args) do cmd[#cmd + 1] = a end
    noctalia.runAsync(cmd)
end
function onClick()
    -- a click lands on a workspace dot or a column block (the canvas publishes their x ranges)
    for _, h in ipairs(hits) do
        if input.x >= h.x0 and input.x <= h.x1 then
            if h.kind == "ws" then act({"focus-workspace", tostring(h.idx)}) return end
            if h.kind == "col" then act({"focus-column", tostring(h.idx)}) return end
        end
    end
    act({"toggle-overview"})
end
function onRightClick() act({"toggle-overview"}) end
function onScroll(axis, steps, startsGesture)
    local s = tonumber(steps) or 0
    if s > 0 then act({"focus-workspace-down"}) elseif s < 0 then act({"focus-workspace-up"}) end
end
function update()
    local now = noctalia.nowMs()
    if now - lastSkin > 1000 then
        input.accent = noctalia.getColor("primary") or "#3584e4"
        input.text = noctalia.getColor("on_surface") or "#ffffff"
        input.style = noctalia.getConfig("style") or "columns"
        lastSkin = now
        dirty = true
    end
    if dirty then send() end
    local raw = noctalia.readFile(state .. "status.json")
    local v = raw and noctalia.json.decode(raw) or {}
    if type(v) ~= "table" then v = {} end
    if now - (v.updated or 0) * 1000 > 3000 and now - lastStart > 5000 then start() end
    hits = type(v.hits) == "table" and v.hits or {}
    local w = math.max(60, math.min(420, math.floor(tonumber(v.width) or 120)))
    if w ~= lastWidth then
        width = w
        barWidget.render(ui.row({key = "hub", gap = -w, align = "center"}, {
            ui.pixelStream({key = "hub-pixels", path = state .. "canvas.sock", width = w, height = H}),
            ui.graph({key = "hub-hover", width = w, height = H, values = {}, color = "#00000000", fillOpacity = 0,
                onPointerMove = "hubMove", onPointerLeave = "hubLeave"}),
        }))
        lastWidth = w
    end
    local tip = v.tooltip or "工作区"
    if tip ~= lastTip then barWidget.setTooltip(tip .. "\n点击：跳到该工作区/列 · 滚轮：切换工作区 · 右键：概览") lastTip = tip end
end
start()
noctalia.setUpdateInterval(16)
update()
