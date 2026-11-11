--!nonstrict
local face=require("./face.luau")
local P={}
local layout=require("./layout.luau")
local actors={}
local dir=noctalia.pluginDataDir().."/peek"
noctalia.mkdirAll(dir)
local sourceCache={}
local lastKey,lastPath,lastWidth="",nil,26
local STEP=20   -- original pitch: faces overlap slightly, leader on top
local function easeOutBack(t) t=math.clamp(t,0,1) return 1+2.2*(t-1)^3+1.2*(t-1)^2 end
-- A small badge that belongs to one face: dark disc, ring in the face's colour, count (or ! when it waits for you).
local function badge(x,count,waiting,ring)
    if count<=0 and not waiting then return "" end
    local text=waiting and "!" or (count>9 and "9+" or tostring(count))
    local r=text=="9+" and 6.4 or 5.4
    local cx,cy=x+21.5,20.5
    return '<g><circle cx="'..string.format("%.2f",cx)..'" cy="'..string.format("%.2f",cy)..'" r="'..tostring(r)..'" fill="#050507" stroke="'..ring..'" stroke-width="1.3"/>'
        ..'<text x="'..string.format("%.2f",cx)..'" y="'..string.format("%.2f",cy+3.1)..'" font-size="8.5" font-weight="700" font-family="sans-serif" text-anchor="middle" fill="#ffffff">'..text..'</text></g>'
end
local function ringOf(a) return a.waiting and "#FF3E51" or "#8FB4FF" end
local function source(path,tag,x)
    local svg=sourceCache[path]
    if not svg then
        svg=noctalia.readFile(path) or ""
        sourceCache[path]=svg
    end
    svg=string.gsub(svg,'id="eyes"','id="eyes'..tag..'"')
    svg=string.gsub(svg,'#eyes','#eyes'..tag)
    svg=string.gsub(svg,'width="80" height="80"','width="26" height="26"')
    local result = string.gsub(svg,'<svg ','<svg x="'..string.format("%.2f",x)..'" y="0" ',1)
    return result
end
function P.render(s,now,mainImage)
    local pins=require("./pins.luau")
    local desired,overflow=pins.members(s,pins.get(),layout.barLimit)
    local targets={}
    for slot,a in ipairs(desired) do
        targets[a.id]=true
        if not actors[a.id] then
            local seed=0
            for n=1,#a.id do seed=(seed*31+string.byte(a.id,n))%36000 end
            actors[a.id]={agent=a,p=0,last=now,start=now+(slot-1)*65,offset=seed}
        end
        actors[a.id].agent=a
    end
    local all={}
    for id,actor in pairs(actors) do
        local delta=math.min(60,math.max(0,now-actor.last))/300
        actor.last=now
        if now>=actor.start or not targets[id] then actor.p=math.clamp(actor.p+(targets[id] and delta or -delta),0,1) end
        if actor.p<=0 and not targets[id] then actors[id]=nil else table.insert(all,actor) end
    end
    table.sort(all,function(a,b)
        if a.agent.waiting~=b.agent.waiting then return a.agent.waiting end
        return a.agent.id<b.agent.id
    end)
    -- Retiring members may share the three slots briefly, but never grow the bar unbounded.
    while #all>layout.barLimit do table.remove(all) end
    -- the leader's badge counts whatever needs you that no face on the strip shows
    local lead,shown=nil,{}
    for _,actor in ipairs(all) do shown[actor.agent.id]=true end
    local hidden,leadOwn,leadWaiting=0,0,false
    for _,a in ipairs(s.agents or {}) do
        local need=a.waiting or (a.unread or 0)>0
        if a.name=="Grok Bot" and a.avatarShape=="blob" then lead=a leadOwn=a.unread or 0 leadWaiting=a.waiting
        elseif need and not shown[a.id] then hidden=hidden+1 end
    end
    if not s.running then hidden,leadOwn,leadWaiting=0,0,false end
    local leadCount=leadOwn+hidden
    local leadBadge=badge(0,leadCount,leadWaiting,leadWaiting and "#FF3E51" or "#8FB4FF")
    if #all==0 then
        if leadBadge=="" then return mainImage,26,overflow,0 end
        local hash=5381
        local k=mainImage..leadBadge
        for n=1,#k do hash=(hash*33+string.byte(k,n))%2147483647 end
        local path=dir.."/"..tostring(hash)..".svg"
        if not noctalia.fileExists(path) then
            noctalia.writeFile(path,'<svg xmlns="http://www.w3.org/2000/svg" width="29" height="26" viewBox="0 0 29 26">'..source(mainImage,"lead",0)..leadBadge..'</svg>')
        end
        return path,29,overflow,0
    end
    local parts,key={},mainImage..leadBadge
    local extent=0
    for i,actor in ipairs(all) do
        local p=actor.p*actor.p*(3-2*actor.p)
        extent=extent+STEP*p
        local a=actor.agent
        local path=face.path(s.running and a.state or "asleep",now+actor.offset,a.avatarShape,a.avatarColor)
        local bd=badge(extent,a.waiting and 1 or (a.unread or 0),a.waiting,ringOf(a))
        key=key..path..":"..tostring(math.floor(extent*4))..bd
        table.insert(parts,{path=path,x=extent,p=p,tag=tostring(i),badge=bd})
    end
    local width=26+extent+3
    if key==lastKey then return lastPath,lastWidth,overflow,#all end
    local body={}
    -- Draw the leader last: members emerge from behind its silhouette.
    for i=#parts,1,-1 do
        local part=parts[i]
        table.insert(body,'<g opacity="'..string.format("%.3f",part.p)..'">'..source(part.path,part.tag,part.x)..part.badge..'</g>')
    end
    table.insert(body,source(mainImage,"lead",0))
    table.insert(body,leadBadge)
    local hash=5381
    for n=1,#key do hash=(hash*33+string.byte(key,n))%2147483647 end
    local path=dir.."/"..tostring(hash)..".svg"
    if not noctalia.fileExists(path) then
        noctalia.writeFile(path,'<svg xmlns="http://www.w3.org/2000/svg" width="'..string.format("%.2f",width)..'" height="26" viewBox="0 0 '..string.format("%.2f",width)..' 26">'..table.concat(body)..'</svg>')
    end
    lastKey,lastPath,lastWidth=key,path,width
    return path,width,overflow,#all
end
return P
