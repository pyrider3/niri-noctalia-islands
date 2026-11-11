--!nonstrict
local state = noctalia.expandPath("~/.local/state/media-capsule/")
local input = {spectrum = {}, stamp = 0, hovered = false, command_serial = 0}
local lastWidth, lastTip, lastStart, lastSkin = nil, nil, 0, 0
local function send()
    noctalia.writeFile(state .. "input.json", noctalia.json.encode(input))
end
local function start()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/media_canvas.py"})
    lastStart = noctalia.nowMs()
end
function onAudioSpectrum(values, status)
    local bands = {}
    if noctalia.getConfig("audio_spectrum") == false then values = "" end
    local configuredBands = noctalia.getConfig("audio_spectrum_bands") or 20
    for value in string.gmatch(values or "", "[^,]+") do
        local number = tonumber(value)
        if number and #bands < configuredBands then table.insert(bands, math.max(0, math.min(1, number))) end
    end
    input.spectrum = bands
    input.stamp = noctalia.nowMs() / 1000
    send()
end
function titleHover()
    if not input.hovered then input.hovered = true send() end
end
function titleLeave()
    if input.hovered then input.hovered = false send() end
end
local function command(action)
    input.command_serial = input.command_serial + 1
    input.command = action
    send()
end
local lastIsland = 0
local function startIsland()
    noctalia.runAsync({"python3", noctalia.pluginDir() .. "/media_island.py"})
    lastIsland = noctalia.nowMs()
end
-- the player panel is now a dynamic island (media_island.py): a click sends it a command
function onClick()
    noctalia.writeFile(state .. "island-cmd.json", noctalia.json.encode({seq = noctalia.nowMs(), cmd = "toggle"}))
end
function onMiddleClick() command("Next") end
function onRightClick() command("PlayPause") end
function update()
    local now = noctalia.nowMs()
    if now-lastSkin > 1000 then
        input.accent = noctalia.getColor("primary") or "#edb69b"
        input.text = noctalia.getColor("on_surface") or "#e9e9e6"
        input.max_width = math.max(96, math.min(720, tonumber(noctalia.getConfig("max_width")) or 360))
        input.title_scroll = noctalia.getConfig("title_scroll") or "hover"
        input.scroll_speed = math.max(8, math.min(60, tonumber(noctalia.getConfig("scroll_speed")) or 22))
        lastSkin = now
        send()
    end
    local raw = noctalia.readFile(state .. "status.json")
    local value = raw and noctalia.json.decode(raw) or {}
    if type(value) ~= "table" then value = {} end
    if now-(value.updated or 0)*1000>3000 and now-lastStart>5000 then start() end
    local araw = noctalia.readFile(state .. "island-alive.json")
    local alive = araw and noctalia.json.decode(araw) or {}
    if type(alive) ~= "table" then alive = {} end
    if now-(alive.t or 0)*1000>4000 and now-lastIsland>6000 then startIsland() end
    local width = value.available == false and 0 or math.max(96, math.min(720, tonumber(value.width) or 220))
    barWidget.setVisible(width > 0)
    if width ~= lastWidth then
        barWidget.render(ui.row({key = "media-capsule", gap = -width, align = "center"}, width > 0 and {
            ui.pixelStream({key = "media-image", path = state .. "canvas.sock", width = width, height = 28}),
            -- Transparent graph tracks hover above the stream without taking clicks.
            ui.graph({key = "media-hover", width = width, height = 28, values = {}, color = "#00000000", fillOpacity = 0,
                onPointerMove = "titleHover", onPointerLeave = "titleLeave"}),
        } or {}))
        lastWidth = width
    end
    local tip = (value.tooltip or "读取播放器…") .. "\n点击打开播放面板 · 中键下一首 · 右键播放/暂停"
    if tip ~= lastTip then barWidget.setTooltip(tip) lastTip=tip end
end
start()
noctalia.setUpdateInterval(16)
update()
