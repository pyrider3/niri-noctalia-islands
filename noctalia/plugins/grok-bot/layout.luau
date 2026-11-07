local L={barLimit=10,pageLimit=32,columns=8}
function L.rows(count) return math.max(1,math.ceil(math.min(count,L.pageLimit)/L.columns)) end
function L.rowSizes(count)
    local sizes={}
    local remaining=math.min(count,L.pageLimit)
    while remaining>0 do local n=math.min(L.columns,remaining) table.insert(sizes,n) remaining=remaining-n end
    return sizes
end
return L
