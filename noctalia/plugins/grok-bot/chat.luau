--!nonstrict
local model=require("./model.luau")
local C={}
local files={}
local listed=0
local cached={}
function C.messages(id,now)
    local directory=noctalia.expandPath("~/.config/Grok Bot/sand-client-persistence/")
    if now-listed>3000 or not files[id] then
        for _,name in ipairs(noctalia.listDir(directory) or {}) do
            local key=model.key(name)
            local agent=string.match(key,"%.transcript%.replicas%.([%x%-]+)$")
            if agent then files[agent]=directory..name end
        end
        listed=now
    end
    local path=files[id]
    if not path then return {},"暂无本地聊天记录" end
    local info=noctalia.fileInfo(path)
    if not info or info.size>4194304 then return {},"本地记录过大或暂不可读" end
    local stamp=tostring(info.mtime)..":"..tostring(info.size)
    if cached[id] and cached[id].stamp==stamp then return cached[id].messages,"" end
    local raw=noctalia.readFile(path)
    local data=raw and noctalia.json.decode(raw)
    local entries=type(data)=="table" and type(data.value)=="table" and data.value.entries or {}
    local messages={}
    for _,entry in ipairs(entries) do
        local text,role
        if entry.kind=="message" and entry.role=="user" and entry.channel==nil then
            text=entry.content role="你"
        elseif entry.kind=="send-message" and type(entry.message)=="table" and entry.message.type=="text" and entry.message.channel==nil then
            text=entry.message.content role="BOT"
        end
        if type(text)=="string" and text~="" then
            local clean=string.gsub(text,"[%c]",function(ch) return (ch=="\n" or ch=="\t") and ch or " " end)
            local length=utf8.len(clean)
            if length and length>12000 then clean=string.sub(clean,1,utf8.offset(clean,12001)-1).."…" end
            if length then table.insert(messages,{id=tostring(entry.id),role=role,text=clean}) end
        end
    end
    while #messages>60 do table.remove(messages,1) end
    cached[id]={stamp=stamp,messages=messages}
    return messages,""
end
function C.handoff(id,text)
    if type(text)~="string" or string.match(text,"^%s*$") then return false,"请输入消息" end
    local length=utf8.len(text)
    if not length or length>1000 then return false,"应用消息入口最多接收 1000 字，请缩短消息" end
    local url="grokbot://app/v1/prompt?id="..noctalia.string.urlEncode(id).."&text="..noctalia.string.urlEncode(text)
    if #url>2048 then return false,"消息超出应用链接长度限制，请缩短后重试" end
    return noctalia.runAsync({"grok-bot",url}),"已交给 Grok Bot，请在应用中确认发送；草稿已保留"
end
function C.send(id,text,callback)
    if type(text)~="string" or string.match(text,"^%s*$") then return false,"请输入消息" end
    if #text>36000 then return false,"消息过长，请分段发送" end
    local requestId="chat-"..tostring(math.floor(noctalia.nowMs())).."-"..tostring(math.random(100000,999999))
    local file=noctalia.expandPath("~/.local/state/noctalia-grok-bridge/")..requestId..".json"
    local written=noctalia.writeFile(file,noctalia.json.encode({method="send",agentId=id,text=text,requestId=requestId}))
    if not written then return false,"桥接未启动，草稿已保留" end
    local accepted=noctalia.runAsync({"node",noctalia.pluginDir().."/bridge.mjs","request","--file",file},function(result)
        noctalia.removeFile(file)
        local reply=noctalia.json.decode(result.stdout or "")
        if type(reply)~="table" then reply={ok=false,error="发送状态未确认，请检查聊天记录后再决定是否重发"} end
        callback(reply)
    end,30000)
    if not accepted then noctalia.removeFile(file) return false,"无法启动消息桥接，草稿已保留" end
    return true,"正在提交…"
end
return C
