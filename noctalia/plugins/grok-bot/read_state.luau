--!nonstrict
local model=require("./model.luau")
local R={}
-- Include the count so a new reply with identical text still becomes unread.
function R.token(a)
    return noctalia.json.encode({a.lastActivityAt or 0,a.lastText or "",a.unread or 0,a.hasUnread==true})
end
function R.apply(rows,receipts)
    local result={}
    for _,original in ipairs(rows) do
        local a=table.clone(original)
        if receipts[a.id]==R.token(a) then a.unread=0 a.hasUnread=false end
        table.insert(result,a)
    end
    return result
end
function R.matchesLatest(a,messages)
    local latest=messages[#messages]
    return latest~=nil and a.lastText~="" and model.preview(latest.text)==a.lastText
end
function R.mark(a,messages)
    if not a or (a.unread<=0 and not a.hasUnread) or not R.matchesLatest(a,messages) then return false end
    local receipts=noctalia.state.get("read_receipts") or {}
    local token=R.token(a)
    if receipts[a.id]==token then return false end
    receipts=table.clone(receipts)
    receipts[a.id]=token
    noctalia.state.set("read_receipts",receipts)
    noctalia.writeFile(noctalia.pluginDataDir().."/read-receipts.json",noctalia.json.encode(receipts))
    return true
end
return R
