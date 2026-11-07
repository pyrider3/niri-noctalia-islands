--!nonstrict
local A = {}
function A.open()
    -- Electron's singleton launch does not always activate an existing Wayland
    -- window. Focus it by compositor id; launch only when no window is present.
    noctalia.runAsync({"niri", "msg", "--json", "windows"}, function(result)
        local windows = noctalia.json.decode(result.stdout or "")
        if type(windows) == "table" then
            for _, window in ipairs(windows) do
                local app = string.lower(window.app_id or "")
                if app == "grok-bot" or app == "grok bot" or app == "sand" then
                    noctalia.runAsync({"niri", "msg", "action", "focus-window", "--id", tostring(window.id)})
                    return
                end
            end
        end
        noctalia.runAsync({"node",noctalia.pluginDir().."/bridge.mjs","serve"})
    end, 3000)
end
return A
