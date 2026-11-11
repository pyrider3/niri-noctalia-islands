pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

/**
 * Clipboard history (";") and window switcher ("@") data, plus use-count ranking shared by apps/files/windows.
 * Data comes from launcher_extra.py (clipboard db filled by the launcher-clip user service, niri windows).
 */
Singleton {
    id: root

    readonly property string script: Quickshell.env("HOME") + "/.local/share/codex-iris-launcher/files/launcher_extra.py"
    readonly property string usageFile: Quickshell.env("HOME") + "/.local/state/launcher-files/usage.json"

    property var results: []
    property string resultsMode: ""
    property string _wantedMode: ""
    property string _wanted: "\u0000"
    property string _ran: "\u0000"
    property string _ranMode: ""

    // ---- use-count ranking -------------------------------------------------------------------------------------
    property var usage: ({})
    FileView {
        path: root.usageFile
        watchChanges: true
        onFileChanged: reload()
        onLoaded: { try { root.usage = JSON.parse(text()) } catch (e) { root.usage = ({}) } }
    }
    function boost(key: string): real {
        const e = root.usage[key]
        if (!e) return 0
        const days = (Date.now() / 1000 - e.t) / 86400
        return 9000 * Math.min(1, Math.log(1 + e.n) / Math.log(21)) + (days < 7 ? 3000 * (1 - days / 7) : 0)
    }
    function use(key: string): void {
        Quickshell.execDetached(["/usr/bin/systemd-run", "--user", "--quiet", "--collect",
            "--description=iRiS launcher: usage", "--", "/usr/bin/python3", root.script, "use", key])
    }

    // ---- queries -------------------------------------------------------------------------------------------------
    function query(mode: string, text: string): void {
        const t = String(text ?? "").trim()
        if (mode === root._wantedMode && t === root._wanted) return
        root._wantedMode = mode
        root._wanted = t
        if (!proc.running) root._next()
    }
    function _next(): void {
        if (root._wanted === root._ran && root._wantedMode === root._ranMode) return
        root._ran = root._wanted
        root._ranMode = root._wantedMode
        const sub = root._ranMode === "clip" ? ["clip", "query"] : ["win", "query"]
        proc.command = ["/usr/bin/python3", root.script].concat(sub, root._ran.split(/\s+/).filter(w => w.length > 0))
        proc.running = true
    }
    function focusWindow(id): void {
        Quickshell.execDetached(["/usr/bin/systemd-run", "--user", "--quiet", "--collect",
            "--description=iRiS launcher: focus window", "--", "/usr/bin/python3", root.script, "win", "focus", String(id)])
    }
    function openFolderOf(path: string): void {
        const dir = path.substring(0, path.lastIndexOf("/")) || "/"
        Quickshell.execDetached(["/usr/bin/systemd-run", "--user", "--quiet", "--collect",
            "--description=iRiS launcher: open folder", "--", "/usr/bin/xdg-open", dir])
    }
    function ago(ts): string {
        const s = Math.max(0, Date.now() / 1000 - ts)
        if (s < 60) return "刚刚"
        if (s < 3600) return Math.floor(s / 60) + " 分钟前"
        if (s < 86400) return Math.floor(s / 3600) + " 小时前"
        return Math.floor(s / 86400) + " 天前"
    }

    Process {
        id: proc
        running: false
        stdout: StdioCollector {
            id: collector
            onStreamFinished: {
                const list = []
                for (const line of collector.text.split("\n")) {
                    if (line.length === 0) continue
                    try { list.push(JSON.parse(line)) } catch (e) { /* half-written line */ }
                }
                root.resultsMode = root._ranMode
                root.results = list
                if (root._wanted !== root._ran || root._wantedMode !== root._ranMode) root._next()
            }
        }
    }
}
