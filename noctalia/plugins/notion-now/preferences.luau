--!nonstrict
local M = {}
function M.boolean(value)
    return value == true or value == "true"
end
local function enabled(value)
    return value == nil or M.boolean(value)
end
local path = noctalia.expandPath("~/.local/state/notion-now/preferences.json")
function M.read()
    local raw = noctalia.readFile(path)
    local value = raw and noctalia.json.decode(raw) or {}
    if type(value) ~= "table" then value = {} end
    return { max_visible = math.max(1, math.min(5, math.floor(tonumber(value.max_visible) or 2))),
        notify_switch = enabled(value.notify_switch),
        display_mode = value.display_mode == "rotate" and "rotate" or ((value.display_mode == "parallel" or value.display_mode == "dual") and "parallel" or "pinned"),
        accent_color = enabled(value.accent_color),
        pinned_event_id = type(value.pinned_event_id) == "string" and value.pinned_event_id or "",
        title_limit = math.max(8, math.min(28, math.floor(tonumber(value.title_limit) or 18))),
        show_progress = enabled(value.show_progress),
        end_warning = enabled(value.end_warning),
        end_warning_minutes = math.max(1, math.min(30, math.floor(tonumber(value.end_warning_minutes) or 5))),
        fixed_width = math.max(140, math.min(420, tonumber(value.fixed_width) or 260)),
        rotate_seconds = math.max(2, math.min(15, tonumber(value.rotate_seconds) or 5)) }
end
function M.save(value)
    return noctalia.writeFile(path, noctalia.json.encode(value))
end
return M
