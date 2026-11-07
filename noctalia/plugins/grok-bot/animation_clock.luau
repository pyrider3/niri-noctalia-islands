--!nonstrict
local C={}
function C.step(clock,now,paused)
    local delta=math.clamp(now-(clock.last or now),0,100)
    -- The resume frame must be exactly the frozen frame, including on reopen.
    if not paused and not clock.paused then clock.phase=clock.phase+delta end
    clock.last=now
    clock.paused=paused
    return clock.phase
end
return C
