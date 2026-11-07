--!nonstrict
local face=require("./face.luau")
local P={}
local layout=require("./layout.luau")
local actors={}
local dir=noctalia.pluginDataDir().."/peek"
noctalia.mkdirAll(dir)
local sourceCache={}
local lastKey,lastPath,lastWidth="",nil,26
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
    if #all==0 then return mainImage,26,overflow,0 end
    local parts,key={},mainImage
    local extent=0
    for i,actor in ipairs(all) do
        local p=actor.p*actor.p*(3-2*actor.p)
        extent=extent+20*p
        local a=actor.agent
        local path=face.path(s.running and a.state or "asleep",now+actor.offset,a.avatarShape,a.avatarColor)
        key=key..path..":"..tostring(math.floor(extent*4))
        table.insert(parts,{path=path,x=extent,p=p,tag=tostring(i)})
    end
    local width=26+extent
    if key==lastKey then return lastPath,lastWidth,overflow,#all end
    local body={}
    -- Draw the leader last: members emerge from behind its silhouette.
    for i=#parts,1,-1 do
        local part=parts[i]
        table.insert(body,'<g opacity="'..string.format("%.3f",part.p)..'">'..source(part.path,part.tag,part.x)..'</g>')
    end
    table.insert(body,source(mainImage,"lead",0))
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
