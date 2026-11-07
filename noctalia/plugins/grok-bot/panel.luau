--!nonstrict
local model = require("./model.luau")
local face = require("./face.luau")
local actions = require("./actions.luau")
local opened, selected = false, 1
local mood, since = "", 0
local agentClocks = {}
local lastAnimation = 0
local renderedFrames = 0
local lastHealth = 0
local dir = noctalia.pluginDataDir()
local notice = ""
local function snapshot()
    local source = noctalia.state.get("snapshot") or {agents = {}, counts = {waiting=0,working=0,unread=0,total=0},
        mood = "asleep", running = false, installed = true, version = "", error = "正在读取状态"}
    local id = noctalia.state.get("selected_agent")
    if type(id) == "string" and id ~= "" then
        local copy = table.clone(source)
        copy.agents = {}
        for _, a in ipairs(source.agents) do if a.id == id then table.insert(copy.agents,a) end end
        return copy
    end
    return source
end
function showSquad() noctalia.togglePanel("local/grok-bot:squad") end
function openApp()
    actions.open()
    panel.close()
end
function appSettings()
    noctalia.runAsync({"grok-bot", "grokbot://app/v1/settings"})
    panel.close()
end
function refresh()
    noctalia.runAsync({"noctalia", "msg", "plugin", "local/grok-bot:monitor", "all", "refresh"})
    notice = "已请求刷新"
    update()
end
function pluginSettings() noctalia.openSettings() end
function update()
    if not opened then return end
    local s, now = snapshot(), noctalia.nowMs()
    renderedFrames = renderedFrames + 1
    if now - lastHealth > 2000 then
        noctalia.writeFile(dir.."/panel-animation-health.json",noctalia.json.encode({updated=now,frames=renderedFrames,ok=true}))
        lastHealth = now
    end
    if s.mood ~= mood then mood, since = s.mood, now end
    local children = {
        ui.row({gap = 12, align = "center"}, {
            ui.button({glyph="arrow-left",variant="ghost",onClick="showSquad",tooltip="返回 BOT 小队"}),
            ui.image({key="hero-face",path = face.path(s.mood, now - since),width = 48,height = 48}),
            ui.column({gap = 4, flexGrow = 1}, {
                ui.label({text = "Grok Bot",fontSize = 23,fontWeight = "bold"}),
                ui.label({text = model.summary(s),fontSize = 12,
                    color = s.mood == "waiting" and "error" or "on_surface_variant"}),
            }),
            ui.button({key="refresh",glyph = "refresh",variant = "ghost",onClick = "refresh",tooltip = "刷新状态 · R"}),
        }),
        ui.row({gap = 8}, {
            ui.label({text = "●  " .. (s.running and "运行中" or "未运行"),fontSize=11,
                color=s.running and "primary" or "on_surface_variant"}),
            ui.label({text = s.version ~= "" and "v" .. s.version or "",fontSize = 11,color="on_surface_variant",flexGrow=1}),
            ui.label({text = tostring(s.counts.total) .. " 个代理",fontSize=11,color="on_surface_variant"}),
        }),
        ui.separator(),
    }
    if s.error ~= "" then table.insert(children, ui.label({text=s.error,color="error",fontSize=12,maxLines=2})) end
    local cards = {}
    local section = ""
    selected = math.clamp(selected, 1, math.max(1,#s.agents))
    for index, a in ipairs(s.agents) do
        local heading = a.waiting and "等你处理" or "代理"
        if heading ~= section then
            table.insert(cards, ui.label({key="heading-"..heading,text=heading,fontSize=11,fontWeight="bold",
                color=a.waiting and "error" or "on_surface_variant"}))
            section = heading
        end
        local stateColor = a.state == "waiting" and "error" or (a.state == "idle" and "on_surface_variant" or "primary")
        local preview = a.waiting and a.reason or (a.lastText ~= "" and a.lastText or a.description)
        local indexCopy = index
        local agentMood = s.running and a.state or "asleep"
        local clock = agentClocks[a.id]
        if not clock or clock.mood ~= agentMood then
            local seed = 0
            for n = 1, #a.id do seed = (seed * 31 + string.byte(a.id, n)) % 36000 end
            clock = {mood = agentMood, since = now, offset = seed}
            agentClocks[a.id] = clock
        end
        local portrait = face.path(agentMood, now - clock.since + clock.offset, a.avatarShape, a.avatarColor)
        table.insert(cards, ui.column({key="agent-"..a.id,gap=6,padding=12,radius=12,
            fill = index == selected and "primary/0.10" or "surface_container",
            border = index == selected and "primary/0.4" or "outline/0.12",borderWidth=1,
            onClick=function() selected=indexCopy openApp() end,
            tooltip = "点击打开 Grok Bot"}, {
            ui.row({gap=8,align="center"}, {
                ui.image({key="portrait-"..a.id,path=portrait,width=30,height=30}),
                ui.label({text=a.name ~= "" and a.name or "Agent",fontSize=14,fontWeight="semibold",maxLines=1,flexGrow=1}),
                ui.label({text=model.labels[a.state],fontSize=10,color=stateColor}),
                ui.label({text=a.unread > 0 and tostring(a.unread) or "",fontSize=11,fontWeight="bold",color="primary"}),
            }),
            ui.label({text=preview ~= "" and preview or "暂无最近消息",fontSize=12,maxLines=2,color=a.waiting and "error" or "on_surface_variant"}),
            ui.row({gap=8}, {
                ui.label({text=a.title,fontSize=10,maxLines=1,flexGrow=1,color="on_surface_variant"}),
                ui.label({text=model.relative(a.lastActivityAt,now),fontSize=10,color="on_surface_variant"}),
            }),
        }))
    end
    if #s.agents == 0 then
        table.insert(cards, ui.column({paddingV=36,gap=12,align="center"}, {
            ui.glyph({name="robot",size=38,color="on_surface_variant"}),
            ui.label({text=s.running and "还没有代理" or "Grok Bot 正在休息",fontSize=16}),
            ui.label({text="打开 Grok Bot 后，代理状态会自动出现在这里。",fontSize=12,maxLines=2,color="on_surface_variant"}),
        }))
    end
    table.insert(children,ui.scroll({key="agents-scroll",flexGrow=1,gap=8,revealKey="agent-"..(s.agents[selected] and s.agents[selected].id or "")},cards))
    table.insert(children,ui.separator())
    table.insert(children,ui.row({gap=8,align="center"}, {
        ui.button({key="open",text=s.running and "打开 Grok Bot" or "启动 Grok Bot",glyph="external-link",variant="primary",onClick="openApp",flexGrow=1}),
        ui.button({key="app-settings",glyph="settings",variant="secondary",onClick="appSettings",tooltip="Grok Bot 设置 · S"}),
        ui.button({key="plugin-settings",glyph="adjustments",variant="ghost",onClick="pluginSettings",tooltip="挂件设置"}),
    }))
    table.insert(children,ui.label({text=notice ~= "" and notice or "J/K 选择 · Enter 打开 · R 刷新 · Esc 关闭",fontSize=10,color="on_surface_variant"}))
    panel.render(ui.column({gap=10,padding=18,height=560,fill=noctalia.getColor("surface") or "#202024",radius=16},children))
end
function onOpen() opened=true notice="" panel.setNeedsFrameTick(true) update()
    noctalia.writeFile(dir.."/panel-health.json",noctalia.json.encode({ok=true,updated=noctalia.nowMs(),agents=#snapshot().agents}))
end
function onClose() opened=false panel.setNeedsFrameTick(false) end
function onFrameTick(deltaMs)
    local now = noctalia.nowMs()
    if opened and now - lastAnimation >= 30 then
        lastAnimation = now
        update()
    end
end
function onKey(chord,pressed)
    if not pressed then return end
    if chord=="j" then selected=math.min(#snapshot().agents,selected+1)
    elseif chord=="k" then selected=math.max(1,selected-1)
    elseif chord=="Return" or chord=="o" then openApp() return
    elseif chord=="r" then refresh() return
    elseif chord=="s" then appSettings() return end
    update()
end
function onIpc(event) if event=="refresh" or event=="health" then update() end end
panel.setNeedsFrameTick(true)
