--!nonstrict
local P={}
function P.get()
    local pins=noctalia.state.get("bar_pins")
    if type(pins)=="table" then return pins end
    local raw=noctalia.readFile(noctalia.pluginDataDir().."/bar-pins.json")
    pins=raw and noctalia.json.decode(raw)
    if type(pins)~="table" then pins={} end
    noctalia.state.set("bar_pins",pins)
    return pins
end
function P.toggle(id)
    local pins=table.clone(P.get())
    pins[id]=not pins[id] or nil
    noctalia.writeFile(noctalia.pluginDataDir().."/bar-pins.json",noctalia.json.encode(pins))
    noctalia.state.set("bar_pins",pins)
end
function P.members(s,pins,limit)
    local result,seen={},{}
    local function add(a)
        local lead=a.name=="Grok Bot" and a.avatarShape=="blob"
        if not lead and not seen[a.id] then table.insert(result,a) seen[a.id]=true end
    end
    -- Stable order for pinned members, regardless of activity-based roster sorting.
    local pinned={}
    for _,a in ipairs(s.agents) do if pins[a.id] then table.insert(pinned,a) end end
    table.sort(pinned,function(a,b) return a.id<b.id end)
    for _,a in ipairs(pinned) do add(a) end
    if s.running then for _,a in ipairs(s.agents) do
        if a.state=="working" or a.state=="waiting" then add(a) end
    end end
    local overflow=math.max(0,#result-limit)
    while #result>limit do table.remove(result) end
    return result,overflow
end
return P
