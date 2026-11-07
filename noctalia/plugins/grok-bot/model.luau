--!nonstrict
-- Port of hmarquez-solutions/omarchy-grok-bot's MIT-licensed Model.js.
local M = {}
local avatarDefaults=require("./avatar_defaults.luau")
local alphabet = "abcdefghijklmnopqrstuvwxyz234567"
function M.key(file)
    local stem = string.match(file, "^([a-z2-7]+)%.blob$")
    if not stem then return "" end
    local bits, value, out = 0, 0, {}
    for i = 1, #stem do
        local n = string.find(alphabet, string.sub(stem, i, i), 1, true)
        if not n then return "" end
        value = value * 32 + n - 1
        bits = bits + 5
        if bits >= 8 then
            bits = bits - 8
            table.insert(out, string.char(math.floor(value / 2 ^ bits) % 256))
            value = value % 2 ^ bits
        end
    end
    return noctalia.string.urlDecode(table.concat(out))
end
function M.clean(value, limit)
    if type(value) ~= "string" then return "" end
    local s = string.gsub(value, "[%c]", " ")
    local length = utf8.len(s)
    if not length then return "" end
    if length > limit then s = string.sub(s, 1, utf8.offset(s, limit + 1) - 1) .. "…" end
    return s
end
function M.preview(value)
    if type(value) ~= "string" then return "" end
    local s = string.match(value, "[^\r\n]+") or ""
    s = string.gsub(s, "^%s*[%-%*>#]+%s*", "")
    s = string.gsub(s, "[*`_]", "")
    return M.clean(s, 160)
end
local reasons = {
    permission_request = "请求你的许可", approval_required = "需要你批准",
    local_tool_permission = "请求运行本地工具", secret_request = "需要你提供凭据",
    widget_options = "有问题等你回答", cursor_agent = "正在等待 Cursor 代理",
    email_draft = "邮件草稿等待审核", slack_draft = "消息草稿等待审核",
}
function M.parse(raw)
    if type(raw) ~= "table" or type(raw.value) ~= "table" or type(raw.value.rows) ~= "table" then
        return nil, "状态格式无法识别，请更新插件"
    end
    local out = {}
    for _, row in ipairs(raw.value.rows) do
        if type(row) == "table" and type(row.id) == "string" and row.id ~= ""
            and not row.isHiddenFromSidebar and not row.isRemovedFromSidebar then
            local waiting = type(row.awaitingUserResponse) == "table" and row.awaitingUserResponse or nil
            local reason = waiting and M.clean(waiting.reasonCopy, 180) or ""
            if reason == "" and waiting then reason = M.clean(waiting.reason, 180) end
            reason = reasons[reason] or reason
            if waiting and reason == "" then reason = "等待你的回答或批准" end
            local defaultShape,defaultColor=avatarDefaults.resolve(row.id)
            table.insert(out, {
                id = M.clean(row.id, 80), name = M.clean(row.name, 48),
                avatarShape = M.clean(row.avatarShape, 24)~="" and M.clean(row.avatarShape,24) or defaultShape, avatarColor = M.clean(row.avatarColor,24)~="" and M.clean(row.avatarColor,24) or defaultColor,
                title = M.clean(row.title, 80), description = M.clean(row.description, 160),
                unread = math.max(0, math.floor(tonumber(row.unreadCount) or 0)),
                hasUnread = row.hasUnread == true, waiting = waiting ~= nil, reason = reason,
                lastText = M.preview(type(row.lastEntry) == "table" and row.lastEntry.text or ""),
                lastActivityAt = tonumber(row.lastActivityAt) or 0,
                notify = row.notifyOnUpdatesEnabled ~= false and row.notificationsEnabled ~= false,
            })
        end
        if #out >= 96 then break end
    end
    return out, ""
end
function M.pendingTask(agent, now)
    local text = agent.lastText or ""
    if #text > 600 or now - (agent.lastActivityAt or 0) > 1800000 then return false end
    for _, phrase in ipairs({"已停止", "已经停", "已取消", "已完成", "已经完成", "跑完了", "工作已终止", "任务已结束"}) do
        if string.find(text, phrase, 1, true) then return false end
    end
    for _, phrase in ipairs({"有结果马上", "有结果就", "查完发你", "查完告诉你", "完成后通知", "完成后告诉", "正在处理中", "正在查询", "正在查", "已经开始查", "正在运行", "正在执行", "I'll report back", "will report back"}) do
        if string.find(text, phrase, 1, true) then return true end
    end
    return false
end
local rank = {waiting = 1, working = 2, unread = 3, idle = 4}
function M.decorate(rows, activity, now, window, running)
    local out, counts = {}, {waiting = 0, working = 0, unread = 0, idle = 0, total = 0, messages = 0}
    for _, original in ipairs(rows) do
        local a = table.clone(original)
        if a.waiting then a.state="waiting"
        elseif a.runtimeKnown then
            if a.runtimeRunning then a.state="working"
            elseif a.hasUnread or a.unread>0 then a.state="unread"
            else a.state="idle" end
        else
            a.state=((activity[a.id] or 0)>now-window and "working") or (M.pendingTask(a,now) and "working") or ((a.hasUnread or a.unread>0) and "unread") or "idle"
        end
        table.insert(out, a)
        counts[a.state] = counts[a.state] + 1
        counts.total = counts.total + 1
        counts.messages = counts.messages + a.unread
    end
    table.sort(out, function(a,b)
        if rank[a.state] ~= rank[b.state] then return rank[a.state] < rank[b.state] end
        if a.lastActivityAt ~= b.lastActivityAt then return a.lastActivityAt > b.lastActivityAt end
        return a.id < b.id
    end)
    local mood = not running and "asleep" or (counts.waiting > 0 and "waiting")
        or (counts.working > 0 and "working") or (counts.unread > 0 and "unread") or "idle"
    return out, counts, mood
end
M.labels = {asleep = "未运行", idle = "待命", working = "工作中", unread = "有新回复", waiting = "等你处理"}
function M.summary(s)
    if not s.running then return "Grok Bot 未运行" end
    local c = s.counts
    if c.waiting > 0 then return tostring(c.waiting) .. " 个代理等你处理" end
    if c.working > 0 then return tostring(c.working) .. " 个代理正在工作" end
    if c.unread > 0 then return tostring(c.unread) .. " 个代理有未读回复" end
    return c.total == 0 and "还没有代理" or "一切就绪，随时待命"
end
function M.relative(at, now)
    if not at or at <= 0 then return "" end
    local seconds = math.max(0, (now - at) / 1000)
    if seconds < 60 then return "刚刚" end
    if seconds < 3600 then return tostring(math.floor(seconds / 60)) .. " 分钟前" end
    if seconds < 86400 then return tostring(math.floor(seconds / 3600)) .. " 小时前" end
    return tostring(math.floor(seconds / 86400)) .. " 天前"
end
return M
