--!nonstrict
-- SVG geometry follows the original MIT-licensed Face.qml; transparent eye cutouts.
local F = {}
local cache = {}
local dir = noctalia.pluginDataDir() .. "/faces"
noctalia.mkdirAll(dir)
local palette = {black="#F0F0F2",blue="#1686FA",cyan="#12B3A3",orange="#FF780A",violet="#8B50FA",green="#13BC78",red="#FF3E51",pink="#EE95C3",yellow="#FFAF38",brown="#A27952",magenta="#FF5EB1",white="#EEECE7",gray="#96999F",grey="#96999F",purple="#8B50FA",teal="#12B3A3"}
local silhouettes = {
    blob='<ellipse cx="20" cy="20" rx="17" ry="17.5"/>',
    heart='<path d="M20 36 C16 32 3 23 3 13 C3 2 16 1 20 10 C24 1 37 2 37 13 C37 23 24 32 20 36Z"/>',
    hex='<path d="M12 4 Q10 4 9 6 L2 18 Q1 20 2 22 L9 34 Q10 36 12 36 H28 Q30 36 31 34 L38 22 Q39 20 38 18 L31 6 Q30 4 28 4Z"/>',
    pumpkin='<path d="M20 8 C5 1 -1 16 4 29 C7 39 16 36 20 35 C24 36 33 39 36 29 C41 16 35 1 20 8Z"/><path d="M19 9 Q17 3 23 2" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>',
    star='<path d="M20 2 Q21 2 24 11 L26 13 L36 14 Q39 14 36 18 L29 25 L31 35 Q32 39 28 36 L20 31 L12 36 Q8 39 9 35 L11 25 L4 18 Q1 14 4 14 L14 13 L16 11 Q19 2 20 2Z"/>',
    sparkle='<path d="M20 2 C25 2 26 10 28 12 C30 14 38 15 38 20 C38 25 30 26 28 28 C26 30 25 38 20 38 C15 38 14 30 12 28 C10 26 2 25 2 20 C2 15 10 14 12 12 C14 10 15 2 20 2Z"/>',
    clover='<path d="M20 9 C10 -3 -2 11 9 20 C-2 29 10 43 20 31 C30 43 42 29 31 20 C42 11 30 -3 20 9Z"/>',
    tablet='<rect x="2" y="7" width="36" height="26" rx="13"/>',

}
silhouettes.pebble='<path d="M6 10 C12 0 29 2 35 12 C42 24 32 37 18 37 C3 37 -1 23 6 10Z"/>'
silhouettes.bean='<path d="M10 4 C20 -1 38 8 37 19 C36 27 27 22 25 29 C23 41 7 39 3 29 C-1 19 3 8 10 4Z"/>'
silhouettes.egg='<path d="M20 2 C28 2 37 21 35 28 C32 41 8 41 5 28 C3 21 12 2 20 2Z"/>'
silhouettes.squircle='<path d="M20 3 C35 3 37 5 37 20 C37 35 35 37 20 37 C5 37 3 35 3 20 C3 5 5 3 20 3Z"/>'
silhouettes.capsule='<rect x="7" y="2" width="26" height="36" rx="13"/>'
silhouettes.cylinder='<path d="M5 10 C5 0 35 0 35 10 V30 C35 40 5 40 5 30Z"/>'
silhouettes.gem='<path d="M13 3 Q20 0 27 3 L37 16 Q39 20 36 24 L24 37 Q20 40 16 37 L4 24 Q1 20 3 16Z"/>'
silhouettes.crystal='<path d="M19 1 Q20 0 22 2 L33 12 L36 28 L21 39 L5 28 L8 12Z"/>'
silhouettes.wedge='<path d="M5 7 Q3 3 8 4 L34 10 Q38 11 36 16 L24 35 Q21 39 18 35Z"/>'
silhouettes.shield='<path d="M5 5 Q20 0 35 5 V21 C35 29 26 36 20 39 C14 36 5 29 5 21Z"/>'
silhouettes.dome='<path d="M3 23 C3 -4 37 -4 37 23 V31 Q37 37 31 37 H9 Q3 37 3 31Z"/>'
silhouettes.arch='<path d="M3 37 V20 C3 -4 37 -4 37 20 V37 H26 V21 C26 12 14 12 14 21 V37Z"/>'
silhouettes.cloud='<path d="M9 35 C-1 35 -2 20 7 17 C4 5 18 -2 25 8 C34 3 42 14 35 22 C44 32 31 40 24 34 C20 39 13 39 9 35Z"/>'
silhouettes.teardrop='<path d="M20 1 C18 11 3 18 4 27 C5 43 35 43 36 27 C37 18 22 11 20 1Z"/>'
silhouettes.leaf='<path d="M35 3 C39 23 31 38 17 37 C-2 35 0 16 12 9 C19 5 27 5 35 3Z"/>'
local petals={}
for i=0,5 do
    local a=i*math.pi/3
    table.insert(petals,string.format('<circle cx="%.2f" cy="%.2f" r="8.5"/>',20+10*math.cos(a),20+10*math.sin(a)))
end
silhouettes.flower=table.concat(petals)..'<circle cx="20" cy="20" r="12"/>'

-- A rounded six-point star, rather than the previous sharp five-point mark.
local points={}
for i=0,11 do
    local a=-math.pi/2+i*math.pi/6
    local r=i%2==0 and 18 or 12
    table.insert(points,{20+r*math.cos(a),20+r*math.sin(a)})
end
local star={}
for i=1,#points do
    local a=points[i]
    local b=points[i%#points+1]
    local x,y=(a[1]+b[1])/2,(a[2]+b[2])/2
    if i==1 then table.insert(star,string.format("M%.2f %.2f",x,y))
    else table.insert(star,string.format("Q%.2f %.2f %.2f %.2f",a[1],a[2],x,y)) end
end
local a,b=points[1],points[2]
table.insert(star,string.format("Q%.2f %.2f %.2f %.2fZ",a[1],a[2],(a[1]+b[1])/2,(a[2]+b[2])/2))
silhouettes.star='<path d="'..table.concat(star,' ')..'"/>'

-- Additional shapes used by the mobile avatar picker.
silhouettes.house='<path d="M5 18 Q5 15 8 12 L17 3 Q20 0 23 3 L33 12 Q36 15 36 19 V32 Q36 37 31 37 H9 Q4 37 4 32Z"/>'
silhouettes.square='<rect x="3" y="3" width="34" height="34" rx="5.5"/>'
silhouettes.wedge='<path d="M8 4 C12 1 32 13 36 19 Q40 24 33 28 L12 37 Q4 40 4 31 L4 12 Q4 6 8 4Z"/>'
silhouettes.triangle=silhouettes.wedge
local poses = {
            {0, 0, 0, -22}, {1.1, 4.8, -2.8, -12}, {2.7, -4.6, -1.5, -40},
            {4.1, -2.4, 3.1, -18}, {5.8, 3.8, 2.4, -32}, {7.2, 0, -3.6, -6},
            {9.3, -4.8, .6, -42}, {11.0, 4.4, -2.5, -14}, {12.4, 0, 0, -28},
            {14.5, 3.6, 3.0, -38}, {16.1, -3.8, -3.2, -8}, {18.4, 0, 1.5, -30},
            {20.1, 4.9, 0, -16}, {21.5, -4.8, 2.2, -40}, {23.7, 1.7, -3.7, -4},
            {25.2, -4.2, -1.8, -34}, {27.6, 4.4, 2.7, -15}, {29.0, 0, 0, -28},
            {31.2, -3.6, 3.0, -42}, {32.9, 4.5, -2.6, -10}, {34.6, 0, 0, -22},
            {36, 0, 0, -22},
        }

function F.path(mood, elapsed, shape, avatarColor)
    local animate = noctalia.getConfig("animate") ~= false
    local period = 36
    local frame = (animate and mood ~= "asleep") and math.floor((elapsed / 1000 % period) / period * 1080) or 0
    local role = mood == "waiting" and "error" or ((mood == "working" or mood == "unread") and "primary") or "on_surface"
    local literalColor = type(avatarColor)=="string" and string.match(avatarColor,"^#%x%x%x%x%x%x$") and avatarColor or nil
    local color = palette[avatarColor] or literalColor or noctalia.getColor(role) or "#e5dfd4"
    shape = silhouettes[shape] and shape or "blob"
    local dark = false
    local arrival = animate and mood == "unread" and elapsed < 650
    local key = "avatar-v7-" .. shape .. "-" .. mood .. "-" .. string.sub(color, 2) .. "-" .. tostring(frame) .. (arrival and "-arrival" or "")
    local path = dir .. "/" .. key .. ".svg"
    if cache[key] then return path end
    if noctalia.fileExists(path) then cache[key]=true return path end
    local phase = frame / 1080
    local t = phase * period
    local gaze, breath, angle, hop = 0, 1, 0, 0
    local openness = ({asleep = .66, idle = 1, working = .74, unread = .9, waiting = 1.22})[mood] or 1
    local tilt = ({asleep = -72, waiting = -8, working = -34})[mood] or -28
    local gazeY = 0
    if animate and mood ~= "asleep" then
        -- Unequal shot lengths and eased gaze changes make a long, varied loop.
        for i = 1, #poses - 1 do
            local a, b = poses[i], poses[i+1]
            if t >= a[1] and t < b[1] then
                local blend = math.clamp((t - a[1] - .25) / .48, 0, 1)
                blend = blend * blend * (3 - 2 * blend)
                gaze = a[2] + (b[2] - a[2]) * blend
                gazeY = a[3] + (b[3] - a[3]) * blend
                tilt = a[4] + (b[4] - a[4]) * blend
                break
            end
        end
        angle = math.sin(t * 1.37) * 6 + math.sin(t * .63) * 2
        hop = math.sin(t * 2.3) * .9
        breath = 1 + .025 * math.sin(t * 2.1)
        openness = openness * (1 + .17 * math.sin(t * 1.8))
        if mood == "working" then
            gaze = gaze * .65 + math.sin(t * 4.2) * 1.5
            tilt = tilt - 8
        elseif mood == "waiting" then
            angle = angle + math.sin(t * 7) * 4
            hop = hop - math.max(0, math.sin(t * 3)) * 1.1
        end
        -- Short single and double blinks, plus occasional inquisitive winks.
        for _, at in ipairs({1.9, 4.8, 5.15, 8.6, 12.0, 15.7, 16.05, 20.0, 24.1, 27.3, 27.65, 31.5, 34.8}) do
            local distance = math.abs(t - at)
            if distance < .15 then openness = openness * (.12 + .88 * distance / .15) end
        end
        if arrival then hop = hop - 2 * math.sin(elapsed / 650 * math.pi) end
    end
    if shape ~= "blob" then gaze = gaze * .65 gazeY = gazeY * .65 end
    if shape ~= "blob" then angle=angle+(shape=="tablet" and -18 or -12) end
    local height = math.max(2.2, 9.8 * openness)
    local eyes = {}
    for i = 1, 2 do
        local x = 20 + (i == 1 and -4 or 4) + gaze
        local y = 20 + gazeY + (i == 1 and 1 or -1) + (mood == "working" and -.6 or .5)
        table.insert(eyes, string.format('<rect x="%.2f" y="%.2f" width="4.2" height="%.2f" rx="2.1" transform="rotate(%.2f %.2f %.2f)" fill="black"/>', x-2.1, y-height/2, height, tilt, x, y))
    end
    local body = '<g fill="'..color..'" color="'..color..'"'..(dark and ' stroke="#8A8A94" stroke-width="0.8"' or '')..'>'..silhouettes[shape]..'</g>'
    -- solid eyes (no cut-out): cream on the dark variant, near-black on the light ones
    body = body .. '<g>'..string.gsub(table.concat(eyes),'fill="black"','fill="'..(dark and '#F5F2EB' or '#16161C')..'"')..'</g>'
    local svg = string.format('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 40 40"><defs><mask id="eyes"><rect width="40" height="40" fill="white"/>%s</mask></defs><g transform="translate(20 %.2f) rotate(%.2f) scale(%.3f) translate(-20 -20)" opacity="%.2f">%s</g></svg>',table.concat(eyes),20+hop,angle,breath,mood == "asleep" and .4 or 1,body)
    noctalia.writeFile(path, svg)
    cache[key] = true
    return path
end
return F
