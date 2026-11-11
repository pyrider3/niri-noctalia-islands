--!nonstrict
local model = require("./model.luau")
local face = require("./face.luau")
local actions = require("./actions.luau")
local peek = require("./peek.luau")
local mood, since, lastTip, lastFrame = "", 0, "", ""
local dir = noctalia.pluginDataDir()
local healthAt = 0
-- hover: the strip unfolds a short status line to its right (spring-driven, never a hard pop)
local hoverOn, hover = false, {x = 0, v = 0}
local lastStep = 0
local function stepHover(now)
    local dt = math.min(60, math.max(0, now - lastStep)) / 1000
    lastStep = now
    local t = hoverOn and 1 or 0
    local n = math.max(1, math.ceil(dt / 0.004))
    local h = dt / n
    for _ = 1, n do
        hover.v = hover.v + (-2 * 0.72 * 16 * hover.v - 16 * 16 * (hover.x - t)) * h
        hover.x = hover.x + hover.v * h
    end
    if math.abs(hover.x - t) < 0.004 and math.abs(hover.v) < 0.02 then hover.x, hover.v = t, 0 end
end
function onHover(value) hoverOn = (value == true or value == "true") end
local function statusLine(s)
    if not s.running then return "未运行" end
    local parts = {}
    if s.counts.waiting > 0 then table.insert(parts, tostring(s.counts.waiting) .. " 等你") end
    if s.counts.working > 0 then table.insert(parts, tostring(s.counts.working) .. " 工作中") end
    if s.counts.unread > 0 then table.insert(parts, tostring(s.counts.unread) .. " 未读") end
    if #parts == 0 then return "待命" end
    return table.concat(parts, " · ")
end
function update()
    local s = noctalia.state.get("snapshot")
    if type(s) ~= "table" then
        barWidget.setTooltip("Grok Bot · 正在读取状态")
        return
    end
    local now = noctalia.nowMs()
    if mood ~= s.mood then mood, since = s.mood, now end
    barWidget.setVisible(s.installed or noctalia.getConfig("hide_missing") == false)
    local label = ""
    if s.running and s.counts.waiting > 0 and noctalia.getConfig("show_name") ~= false then
        label = model.clean(s.agents[1].name, 12)
        if s.counts.waiting > 1 then label = label .. " +" .. tostring(s.counts.waiting - 1) end
    end
    stepHover(now)
    local line = statusLine(s)
    local hv = math.floor(hover.x * 40 + 0.5)
    -- the leader keeps its own colour (white by default) whatever the state; only its expression changes
    local leadShape, leadColor = "blob", "black"
    for _, a in ipairs(s.agents or {}) do
        if a.name == "Grok Bot" and a.avatarShape == "blob" then
            leadShape, leadColor = a.avatarShape, (a.avatarColor ~= "" and a.avatarColor or "black")
            break
        end
    end
    local image = face.path(mood, now - since, leadShape, leadColor)
    local imageWidth, overflow, peeking
    image,imageWidth,overflow,peeking=peek.render(s,now,image)
    local identity = image .. label .. ":" .. tostring(overflow) .. ":" .. tostring(hv) .. line
    if identity ~= lastFrame then
        local nodes = {ui.image({key = "face", path = image, width = imageWidth, height = 26})}
        if overflow>0 then table.insert(nodes,ui.label({key="more",text="+"..tostring(overflow),fontSize=10,color="primary"})) end
        if label ~= "" and not barWidget.isVertical() then
            table.insert(nodes, ui.label({key = "name", text = label, fontSize = 12, color = "error", maxLines = 1}))
        end
        if hover.x > 0.01 and not barWidget.isVertical() then
            local w = math.max(1, math.floor(#line * 5.2 * math.clamp(hover.x, 0, 1.1)))
            table.insert(nodes, ui.column({key = "hover", width = w, height = 26, align = "start", justify = "center",
                opacity = math.clamp(hover.x * 1.6 - 0.2, 0, 1)}, {
                ui.label({text = line, fontSize = 11, maxLines = 1, color = mood == "waiting" and "error" or "on_surface"}),
            }))
        end
        barWidget.render((barWidget.isVertical() and ui.column or ui.row)({gap = 5, align = "center"}, nodes))
        lastFrame = identity
    end
    local tip = model.summary(s) .. "\n左键：展开 BOT 小队 · 右键：打开 Grok Bot · 中键：全部标为已读"
    if s.error ~= "" then tip = tip .. "\n" .. s.error end
    if tip ~= lastTip then barWidget.setTooltip(tip) lastTip = tip end
    if now - healthAt > 10000 then
        noctalia.writeFile(dir .. "/widget-health.json", noctalia.json.encode({ok = true, updated = now,
            output = barWidget.outputName(), mood = mood, image = image, peeking = peeking, overflow = overflow}))
        healthAt = now
    end
end
function onClick()
    -- an open panel folds itself back into a pill (its own animation) instead of the host's slide-up
    if noctalia.state.get("squad_open") == true then
        noctalia.runAsync({"noctalia", "msg", "plugin", "local/grok-bot:squad", "all", "toggle"})
    else
        noctalia.togglePanel("local/grok-bot:squad")
    end
end
function onRightClick() actions.open() end
-- Middle click: mark every unread reply as read (same receipts the squad panel writes), then refresh.
function onMiddleClick()
    local snap = noctalia.state.get("snapshot")
    if type(snap) == "table" then
        local readState = require("./read_state.luau")
        local receipts = table.clone(noctalia.state.get("read_receipts") or {})
        local changed = false
        for _, a in ipairs(snap.agents or {}) do
            if (a.unread or 0) > 0 or a.hasUnread then receipts[a.id] = readState.token(a) changed = true end
        end
        if changed then
            noctalia.state.set("read_receipts", receipts)
            noctalia.writeFile(dir .. "/read-receipts.json", noctalia.json.encode(receipts))
        end
    end
    noctalia.runAsync({"noctalia", "msg", "plugin", "local/grok-bot:monitor", "all", "refresh"})
end
function onIpc(event) if event == "health" or event == "refresh" then update() end end
noctalia.setUpdateInterval(33)
update()
