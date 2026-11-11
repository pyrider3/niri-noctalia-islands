pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

/**
 * File search for the launcher's "." mode. The heavy lifting (index, pinyin matching) is done by launcher_files.py,
 * which reads an SQLite index rebuilt in the background by a systemd user timer.
 * One query runs at a time; when typing outpaces it, only the latest text is queried next.
 */
Singleton {
    id: root

    property var results: []
    property string _wanted: "\u0000"
    property string _ran: "\u0000"
    readonly property string script: Quickshell.env("HOME") + "/.local/share/codex-iris-launcher/files/launcher_files.py"

    function query(text: string): void {
        const t = String(text ?? "").trim()
        if (t === root._wanted) return          // same text again (the list refreshing itself): do nothing, no loop
        root._wanted = t
        if (!proc.running) root._next()
    }

    function _next(): void {
        if (root._wanted === root._ran) return
        root._ran = root._wanted
        proc.command = ["/usr/bin/python3", root.script, "query"].concat(root._ran.split(/\s+/).filter(w => w.length > 0))
        proc.running = true
    }

    function open(path: string): void {
        LauncherExtra.use("file:" + path)
        Quickshell.execDetached(["/usr/bin/systemd-run", "--user", "--quiet", "--collect",
            "--description=iRiS launcher: open file", "--", "/usr/bin/xdg-open", path])
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
                    try { list.push(JSON.parse(line)) } catch (e) { /* skip a half-written line */ }
                }
                root.results = list
                if (root._wanted !== root._ran) root._next()      // the user kept typing: ask again with the latest text
            }
        }
    }
}
