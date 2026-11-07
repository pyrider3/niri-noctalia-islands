--!nonstrict
local face = require("./face.luau")
local gridLayout=require("./layout.luau")
local model = require("./model.luau")
local animationClock = require("./animation_clock.luau")
local chat = require("./chat.luau")
local readState=require("./read_state.luau")
local chatTransition=require("./chat_transition.luau")
local chatProgress,chatFrom,chatTarget,chatStarted=0,0,0,0
-- Island morph: the shell is a pill under the bar that springs open to the full panel (and back when closing).
local PW,W0,H0,CHAT_H=560,124,36,466
local function newSpring(x) return {x=x,v=0,t=x} end
local function stepSpring(sp,dtMs,omega,zeta)
    local dt=math.min(dtMs,50)/1000
    local n=math.max(1,math.ceil(dt/0.004))
    local h=dt/n
    for _=1,n do
        sp.v=sp.v+(-2*zeta*omega*sp.v-omega*omega*(sp.x-sp.t))*h
        sp.x=sp.x+sp.v*h
    end
    if math.abs(sp.x-sp.t)<0.02 and math.abs(sp.v)<0.05 then sp.x=sp.t sp.v=0 end
end
local function springMoving(sp) return sp.x~=sp.t or sp.v~=0 end
local function easeOutBack(t)
    t=math.clamp(t,0,1)
    return 1+2.7*(t-1)^3+1.7*(t-1)^2
end
local function easeOut(t) t=math.clamp(t,0,1) return 1-(1-t)^3 end
local shW,shH=newSpring(W0),newSpring(H0)
local hoverSp={}
local contentAt=nil
local lastStep=0
local moving=false
local seenAt={}
local chatOpenAt=0
local pending={}
local scrollRev=0
local lastMessageCount=-1
local chatMode=false
local selectedId=nil
local drafts={}
local sendBusy={}
local chatNotice=""
local composeRevision=0
local bubbleNodes={}
local bubbleIdentity=nil
local chatAt=0
local messages={}
local transcriptError=""
local opened, closing, started, closeAt, last = false, false, 0, 0, 0
local hover = ""
local pinMode=false
local pins=require("./pins.luau")
local clocks = {}
local renders = 0
local healthAt = 0
local transitioning = false
local portraitCache = {}
local cachedSnapshot = nil
local snapshotAt = 0
local measuredAt, measuredFrames = 0, 0
function dismissBlank() collapse() end
local function renderShell(height,children)
    local pw=math.clamp((shW.x-W0)/(PW-W0),0,1.2)
    local radius=math.min(shH.x/2,16+8*math.min(1,pw))
    local unused=math.max(0,890-shH.x)
    panel.render(ui.column({key="panel-host",height=890,gap=0,align="end"},{
        ui.column({key="shell",width=math.max(W0,shW.x),height=math.max(H0,shH.x),padding=12,gap=8,radius=radius,fill="#050507",border="#ffffff1a",borderWidth=1},children),
        ui.box({key="outside-chat",height=unused,visible=unused>0,fill="surface/0",onClick="dismissBlank"}),
    }))
end
local function animateChat(target)
    chatTarget=target
end
local function choose(id)
    local nextId=chatTransition.toggle(selectedId,id)
    if nextId==nil then
        chatMode=false animateChat(0)
    else
        selectedId=nextId chatMode=true animateChat(1)
        chatAt=0 chatNotice="" chatOpenAt=noctalia.nowMs() seenAt={} lastMessageCount=-1
    end
    update()
end
function collapse()
    closing=true closeAt=noctalia.nowMs() chatMode=false chatTarget=0
end
local function updateInner()
    if not opened then return end
    local now = noctalia.nowMs()
    local dtMs = math.clamp(now-lastStep,0,60)
    if lastStep==0 then dtMs=16 end
    lastStep=now
    if not cachedSnapshot or now-snapshotAt>=250 then
        cachedSnapshot=noctalia.state.get("snapshot")
        snapshotAt=now
    end
    local s = cachedSnapshot
    if type(s)~="table" then return end
    local selectedAgent=nil
    for _,a in ipairs(s.agents) do if a.id==selectedId then selectedAgent=a end end
    if chatMode and not selectedAgent then selectedId=nil chatMode=false chatTarget=0 end
    if selectedId and now-chatAt>=1000 then messages,transcriptError=chat.messages(selectedId,now) chatAt=now end
    local page = math.max(0,tonumber(noctalia.state.get("squad_page")) or 0)
    local pages = math.max(1,math.ceil(#s.agents/gridLayout.pageLimit))
    if page>=pages then page=0 end
    local visibleCount=math.min(gridLayout.pageLimit,math.max(0,#s.agents-page*gridLayout.pageLimit))
    local rowCount=gridLayout.rows(visibleCount)
    local compactHeight=154+(rowCount-1)*90
    -- ---- island morph springs
    if closing then
        shW.t=W0 shH.t=H0
    else
        shW.t=PW shH.t=compactHeight+CHAT_H*(chatTarget>0 and 1 or 0)
    end
    stepSpring(shW,dtMs,15,closing and .9 or .62)
    stepSpring(shH,dtMs,12.5,closing and .9 or .66)
    local pw=math.clamp((shW.x-W0)/(PW-W0),0,1.2)
    local ph=math.clamp((shH.x-H0)/math.max(1,compactHeight-H0),0,1.2)
    chatProgress=(selectedId~=nil or chatMode) and math.clamp((shH.x-compactHeight)/CHAT_H,0,1.08) or 0
    if chatTarget==0 and chatProgress<=0.001 then selectedId=nil end
    -- the avatars pop in only once the shell is (nearly) open, and vanish first when closing
    local contentA=math.clamp((math.min(pw,ph)-.86)/.1,0,1)
    if closing then contentA=math.min(contentA,1-math.clamp((now-closeAt)/130,0,1)) end
    if contentA>0 and not contentAt then contentAt=now end
    if closing and (now-closeAt>240 and math.abs(shW.x-W0)<5 and math.abs(shH.x-H0)<4 or now-closeAt>900) then panel.close() return end
    -- A list preview or a closing/partially revealed chat is not a read.
    if chatMode and not closing and chatProgress>=.95 and transcriptError=="" then
        readState.mark(selectedAgent,messages)
    end
    moving=springMoving(shW) or springMoving(shH) or closing or (contentAt~=nil and now-contentAt<900)
    transitioning = moving
    local members = {}
    for index=page*gridLayout.pageLimit+1,math.min(#s.agents,page*gridLayout.pageLimit+gridLayout.pageLimit) do
        local a=s.agents[index]
        local slot=index-page*gridLayout.pageLimit
        local reveal=0
        if contentAt then reveal=math.clamp((now-contentAt-(math.floor((slot-1)/8)*70+((slot-1)%8)*34))/420,0,1) end
        local pop=easeOutBack(reveal)
        local memberPaused=closing or reveal<=0
        local state=s.running and a.state or "asleep"
        if not clocks[a.id] or clocks[a.id].mood~=state then
            local seed=0
            for n=1,#a.id do seed=(seed*31+string.byte(a.id,n))%36000 end
            clocks[a.id]={mood=state,phase=seed,last=now,paused=memberPaused}
        end
        local clock=clocks[a.id]
        local phase=animationClock.step(clock,now,memberPaused)
        local id=a.id
        local color=a.waiting and "error" or "primary"
        local portrait=portraitCache[id]
        if not portrait or (not memberPaused and now-portrait.at>=30) then
            portrait={path=face.path(state,phase,a.avatarShape,a.avatarColor),at=now}
            portraitCache[id]=portrait
        end
        -- hover / selection / state each add a little spring to the avatar size
        local hs=hoverSp[id]
        if not hs then hs=newSpring(0) hoverSp[id]=hs end
        hs.t=(hover==id and 1 or 0)+((selectedId==id and chatMode) and .7 or 0)
        stepSpring(hs,dtMs,18,.45)
        if springMoving(hs) then moving=true end
        local pulse=0
        if state=="working" then pulse=.05*math.sin(phase/260)
        elseif state=="waiting" then pulse=.09*math.abs(math.sin(phase/320)) end
        local dim=(chatMode and selectedId~=id) and .45 or 1
        local size=math.max(2,44*pop*(1+.2*hs.x+pulse))
        local fillAlpha=a.waiting and string.format("error/%.2f",.06+.1*math.abs(math.sin(phase/320))) or ((hover==id or selectedId==id) and "primary/0.15" or "surface/0")
        table.insert(members,ui.column({key=id,width=60,height=82,align="center",justify="center",gap=4,
            opacity=math.clamp(reveal*2.5,0,1)*dim,radius=12,fill=fillAlpha,
            onClick=function() if pinMode then pins.toggle(id) else choose(id) end end,
            onHover=function(value) if value=="true" then hover=id elseif hover==id then hover="" end end,
            tooltip=a.name.." · "..(model.labels[state] or "待命")..(a.waiting and ("\n"..a.reason) or "")}, {
            ui.column({key="slot-"..id,width=48,height=48,align="center",justify="center"},{
                ui.image({key="face-"..id,path=portrait.path,width=size,height=size}),
            }),
            ui.label({text=(pinMode and (pins.get()[id] and "✓ " or "○ ") or "")..model.clean(a.name,7),fontSize=10,maxLines=1,color=hover==id and "primary" or "on_surface"}),
            ui.label({text=a.waiting and "等你处理" or (a.unread>0 and tostring(a.unread).." 未读" or ""),fontSize=9,color=color}),
        }))
    end
    if #members==0 then table.insert(members,ui.label({text="还没有 BOT，先打开 Grok Bot 开始聊天",fontSize=12})) end
    local memberRows={}
    for start=1,#members,gridLayout.columns do
        local row={}
        for i=start,math.min(#members,start+gridLayout.columns-1) do table.insert(row,members[i]) end
        table.insert(memberRows,ui.row({key="member-row-"..tostring(start),gap=6,align="center",justify="center",height=84},row))
    end
    local gridHeight=rowCount*84+(rowCount-1)*6
    local grid=ui.column({key="members",gap=6,height=gridHeight},memberRows)
    local footer={ui.label({text=hover~="" and "点击成员查看消息" or model.summary(s),fontSize=10,color="on_surface_variant",flexGrow=1}),
        ui.button({glyph="chevron-up",variant="ghost",onClick="collapse",tooltip="收起小队"})}
    table.insert(footer,ui.button({glyph=pinMode and "check" or "settings",tooltip=pinMode and "完成常驻设置" or "常驻设置",variant="ghost",onClick=function()
        pinMode=not pinMode
        if pinMode then chatMode=false animateChat(0) end
        update()
    end}))
    if pinMode then footer[1]=ui.label({text="点击头像切换常驻 · 最多显示 10 位",fontSize=10,color="primary",flexGrow=1}) end
    if pages>1 then table.insert(footer,ui.button({text=tostring(page+1).."/"..tostring(pages),variant="ghost",onClick=function() noctalia.state.set("squad_page",(page+1)%pages) contentAt=noctalia.nowMs() end})) end
    local function shellChildren(inner)
        if contentA<=0.001 then return {} end
        return {ui.column({key="content",width=PW-24,gap=8,opacity=contentA,height=compactHeight-24+(chatProgress>0 and CHAT_H*chatProgress or 0)},inner)}
    end
    if chatProgress<=0.001 and not chatMode then
        renderShell(compactHeight,shellChildren({
            grid,
            ui.row({key="footer",gap=8,align="center"},footer),
        }))
        return
    end
    table.insert(footer,ui.button({text="收起聊天",glyph="chevron-up",variant="ghost",onClick=function()
        chatMode=false animateChat(0) update()
    end}))
    -- ---- chat: bubbles slide in one after another, a pending bubble for what you just sent, typing dots
    local count=#messages
    if selectedId and count~=lastMessageCount then
        lastMessageCount=count
        scrollRev=scrollRev+1
    end
    local bubbles={}
    local animating=false
    local firstShow=now-chatOpenAt<500
    for i,message in ipairs(messages) do
        local mid=message.id
        if seenAt[mid]==nil then
            if firstShow then seenAt[mid]=(i>count-6) and (now+(i-(count-6))*80) or (now-2000)
            else seenAt[mid]=now end
        end
        local p=easeOut((now-seenAt[mid])/380)
        if p<1 then animating=true end
        local mine=message.role=="你"
        local indent=(1-p)*40
        local bubble=ui.column({key="message-"..mid,flexGrow=1,padding=12,gap=5,radius=12,opacity=p,fill=mine and "primary/0.14" or "surface_container"},{
            ui.label({text=mine and "你" or (selectedAgent and selectedAgent.name or "BOT"),fontSize=10,color="on_surface_variant"}),
            ui.markdown({text=message.text}),
        })
        table.insert(bubbles,ui.row({key="mrow-"..mid,gap=0,align="stretch"},{
            ui.box({key="ml-"..mid,width=(mine and 0 or indent),height=1,visible=(not mine) and indent>0.5}),
            bubble,
            ui.box({key="mr-"..mid,width=(mine and indent or 0),height=1,visible=mine and indent>0.5}),
        }))
    end
    local pend=pending[selectedId or ""]
    if pend then
        local delivered=false
        for i=math.max(1,count-4),count do if messages[i] and messages[i].role=="你" and messages[i].text==pend.text then delivered=true end end
        if delivered or now-pend.at>15000 then pending[selectedId]=nil
        else
            local p=easeOutBack((now-pend.at)/420)
            if p<1.05 then animating=true end
            table.insert(bubbles,ui.row({key="pending",gap=0,align="stretch"},{
                ui.column({key="pending-b",flexGrow=1,padding=12,gap=5,radius=12,opacity=math.clamp(p*2,0,1),fill="primary/0.10"},{
                    ui.label({text="你 · 发送中…",fontSize=10,color="primary"}),
                    ui.markdown({text=pend.text}),
                }),
                ui.box({key="pending-r",width=math.max(0.01,(1-math.min(1,p))*50),height=1}),
            }))
        end
    end
    local working=selectedAgent and (selectedAgent.state=="working")
    if working then
        local dots={}
        for k=0,2 do
            local b=.5+.5*math.sin(now/180-k*0.9)
            table.insert(dots,ui.box({key="dot-"..k,width=7,height=5+7*b,radius=4,fill="primary/"..string.format("%.2f",.45+.5*b)}))
        end
        table.insert(bubbles,ui.row({key="typing",gap=8,align="center",height=22},{
            ui.row({key="typing-dots",gap=4,align="center",height=14},dots),
            ui.label({text=(selectedAgent and selectedAgent.name or "BOT").." 正在工作…",fontSize=10,color="on_surface_variant"}),
        }))
    end
    if #bubbles==0 then table.insert(bubbles,ui.label({text=transcriptError~="" and transcriptError or "还没有消息",fontSize=13,color="on_surface_variant"})) end
    if animating or working then moving=true end
    local title=selectedAgent and selectedAgent.name or "BOT 小队"
    local currentId=selectedId
    local draft=currentId and drafts[currentId] or ""
    local function submitCurrent(value)
        if not currentId or sendBusy[currentId] then return end
        if not s.bridgeConnected then chatNotice="桥接未连接，草稿已保留" update() return end
        if type(value)=="string" then drafts[currentId]=value noctalia.state.set("drafts",drafts) end
                if sendBusy[currentId] then return end
                local submitted=drafts[currentId] or ""
                sendBusy[currentId]=true
                local ok,notice=chat.send(currentId,submitted,function(reply)
                    sendBusy[currentId]=nil
                    if reply.ok then
                        pending[currentId]={text=submitted,at=noctalia.nowMs()}
                        scrollRev=scrollRev+1
                        if drafts[currentId]==submitted then drafts[currentId]="" noctalia.state.set("drafts",drafts) end
                        if selectedId==currentId then composeRevision=composeRevision+1 chatNotice="已提交应用发送队列，等待回复" end
                    elseif selectedId==currentId then chatNotice=reply.error or "发送失败，草稿已保留" end
                    chatAt=0 update()
                end)
                if not ok then sendBusy[currentId]=nil end
                chatNotice=notice update()
    end
    local headPortrait=currentId and portraitCache[currentId]
    local headState=selectedAgent and selectedAgent.state or ""
    local headPulse=(headState=="working") and (.5+.5*math.sin(now/300)) or 0
    local chatChildren={
        ui.separator(),
        ui.row({gap=8,align="center",height=34},{
            headPortrait and ui.image({key="head-face",path=headPortrait.path,width=math.max(2,30*easeOutBack((now-chatOpenAt)/380)),height=math.max(2,30*easeOutBack((now-chatOpenAt)/380))}) or ui.spacer({}),
            ui.label({text=title,fontSize=16,fontWeight="bold",flexGrow=1}),
            ui.label({text=selectedAgent and model.labels[selectedAgent.state] or "",fontSize=11,color=(headState=="working" or headState=="waiting") and "primary" or "on_surface_variant",opacity=.65+.35*headPulse}),
        }),
        ui.scroll({key="chat-"..tostring(currentId),flexGrow=1,gap=10,stickToBottom=true,scrollToBottomRev=scrollRev},bubbles),
        ui.input({key="compose-"..tostring(currentId).."-"..tostring(composeRevision),height=72,multiline=true,submitOnEnter=true,onSubmit=function(value) submitCurrent(value) end,value=draft or "",placeholder="给 "..title.." 写消息…（Enter 发送，Shift+Enter 换行）",onChange=function(value) if currentId then drafts[currentId]=value noctalia.state.set("drafts",drafts) end end}),
        ui.row({gap=8,align="center"},{ui.label({text=chatNotice~="" and chatNotice or (s.bridgeConnected and "本机桥接已连接 · 消息交由应用发送" or "桥接未连接，草稿会保留"),fontSize=10,color="on_surface_variant",flexGrow=1,maxLines=2}),
            ui.button({text=sendBusy[currentId] and "提交中…" or "发送",glyph="send",variant="primary",enabled=currentId~=nil and s.bridgeConnected==true and not sendBusy[currentId],onClick=function() submitCurrent() end})}),
    }
    local layout={grid,ui.row({key="footer",gap=8,align="center"},footer),ui.scroll({key="chat-reveal",height=math.max(1,CHAT_H*math.min(1,chatProgress)),opacity=math.clamp(chatProgress*1.4-.1,0,1)},{
        ui.column({key="chat-content",height=450,gap=8},chatChildren),
    })}
    renderShell(compactHeight+CHAT_H*chatProgress,shellChildren(layout))
    renders=renders+1
    if not transitioning and now-healthAt>2000 then
        noctalia.writeFile(noctalia.pluginDataDir().."/squad-health.json",noctalia.json.encode({ok=true,frames=renders,members=#members,updated=now,renderFps=math.floor((renders-measuredFrames)*1000/math.max(1,now-measuredAt))}))
        healthAt=now
        measuredAt=now measuredFrames=renders
    end
end
function update()
    local ok,err=pcall(updateInner)
    if not ok then
        noctalia.writeFile(noctalia.pluginDataDir().."/squad-error.txt",tostring(err))
    end
end
function onOpen(context)
    drafts=noctalia.state.get("drafts") or drafts
    selectedId=nil chatMode=false pinMode=false
    chatProgress=0 chatFrom=0 chatTarget=0 chatStarted=noctalia.nowMs()
    shW.x,shW.v,shW.t=W0,0,W0 shH.x,shH.v,shH.t=H0,0,H0 contentAt=nil lastStep=0 hoverSp={} seenAt={} pending={}
    noctalia.state.set("squad_open",true)
    measuredAt=noctalia.nowMs() measuredFrames=renders cachedSnapshot=nil opened=true closing=false started=noctalia.nowMs()-((chatMode or context=="return") and 1000 or 0) hover="" panel.setNeedsFrameTick(true) update() end
function onClose() opened=false closing=false noctalia.state.set("squad_open",false)
    for _,clock in pairs(clocks) do clock.paused=true end
    panel.setNeedsFrameTick(false)
end
function onFrameTick()
    local now=noctalia.nowMs()
    local interval = moving and 15 or 33
    if now-last>=interval then last=now update() end
end
function onIpc(event)
    if event=="toggle" then
        if opened then collapse() else noctalia.togglePanel("local/grok-bot:squad") end
    elseif event=="health" then update() end
end
panel.setNeedsFrameTick(true)
