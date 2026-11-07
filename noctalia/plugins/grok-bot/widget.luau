--!nonstrict
local model = require("./model.luau")
local face = require("./face.luau")
local actions = require("./actions.luau")
local peek = require("./peek.luau")
local mood, since, lastTip, lastFrame = "", 0, "", ""
local dir = noctalia.pluginDataDir()
local healthAt = 0
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
    local badge = s.running and (s.counts.waiting > 0 and s.counts.waiting or s.counts.unread) or 0
    local image = face.path(mood, now - since)
    local imageWidth, overflow, peeking
    image,imageWidth,overflow,peeking=peek.render(s,now,image)
    local identity = image .. label .. tostring(badge)..":"..tostring(overflow)
    if identity ~= lastFrame then
        local nodes = {ui.image({key = "face", path = image, width = imageWidth, height = 26})}
        if overflow>0 then table.insert(nodes,ui.label({key="more",text="+"..tostring(overflow),fontSize=10,color="primary"})) end
        if label ~= "" and not barWidget.isVertical() then
            table.insert(nodes, ui.label({key = "name", text = label, fontSize = 12, color = "error", maxLines = 1}))
        end
        if badge > 0 then
            table.insert(nodes, ui.column({key = "badge", paddingH = 5, paddingV = 1, radius = 8,
                fill = mood == "waiting" and "error/0.18" or "primary/0.18"}, {
                ui.label({text = badge > 9 and "9+" or tostring(badge), fontSize = 10, fontWeight = "bold",
                    color = mood == "waiting" and "error" or "primary"}),
            }))
        end
        barWidget.render((barWidget.isVertical() and ui.column or ui.row)({gap = 5, align = "center"}, nodes))
        lastFrame = identity
    end
    local tip = model.summary(s) .. "\n左键：展开 BOT 小队 · 右键：打开 Grok Bot · 中键：刷新"
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
function onMiddleClick()
    noctalia.runAsync({"noctalia", "msg", "plugin", "local/grok-bot:monitor", "all", "refresh"})
end
function onIpc(event) if event == "health" or event == "refresh" then update() end end
noctalia.setUpdateInterval(33)
update()
