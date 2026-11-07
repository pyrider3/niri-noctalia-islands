--!nonstrict
local A={}
local function mul(a,b)
    return (bit32.band(a,65535)*bit32.band(b,65535)+
        (bit32.rshift(a,16)*bit32.band(b,65535)+bit32.band(a,65535)*bit32.rshift(b,16))*65536)%4294967296
end
function A.resolve(id)
    local h=2166136261
    for i=1,#id do h=mul(bit32.bxor(h,string.byte(id,i)),16777619) end
    local shapeHash=mul(bit32.bxor(h,bit32.rshift(h,16)),73244475)
    shapeHash=mul(bit32.bxor(shapeHash,bit32.rshift(shapeHash,13)),3266489909)
    shapeHash=bit32.bxor(shapeHash,bit32.rshift(shapeHash,16))
    local shapes={"blob","pebble","squircle","tablet","wedge","hex","cloud","teardrop"}
    local t=(bit32.bxor(bit32.bxor(h,2654435769),2654435769)+1831565813)%4294967296
    local e=mul(bit32.bxor(t,bit32.rshift(t,15)),bit32.bor(t,1))
    e=bit32.bxor(e,(e+mul(bit32.bxor(e,bit32.rshift(e,7)),bit32.bor(e,61)))%4294967296)
    local random=bit32.bxor(e,bit32.rshift(e,14))/4294967296
    local colors={"brown","red","orange","yellow","green","cyan","blue","violet","magenta","gray"}
    return shapes[shapeHash%#shapes+1],colors[math.floor(random*#colors)+1]
end
return A
