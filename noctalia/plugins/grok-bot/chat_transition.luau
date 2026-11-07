local T={}
function T.toggle(current,id)
    if current==id then return nil end
    return id
end
function T.progress(now,from,target,at)
    local t=math.clamp((now-at)/260,0,1)
    local ease=t*t*(3-2*t)
    return from+(target-from)*ease
end
return T
