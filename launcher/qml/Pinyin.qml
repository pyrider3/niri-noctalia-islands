pragma Singleton
import Quickshell
import "pinyin_table.js" as PinyinTable

/**
 * Pinyin keys for searching Chinese names with Latin letters:
 *   keys("微信")  ->  "weixin wx"   (full pinyin and initials; Latin letters and digits pass through)
 */
Singleton {
    property var _cache: ({})

    function _convert(text) {
        let full = "", init = ""
        for (const ch of String(text ?? "")) {
            const py = PinyinTable.TABLE[ch]
            if (py) {
                full += py
                init += py[0]
            } else if (/[A-Za-z0-9]/.test(ch)) {
                full += ch.toLowerCase()
                init += ch.toLowerCase()
            }
            // anything else (spaces, punctuation) is skipped, so "微 信" still gives "weixin"
        }
        return { full: full, init: init }
    }

    function get(text) {
        const key = String(text ?? "")
        if (this._cache[key] === undefined) this._cache[key] = this._convert(key)
        return this._cache[key]
    }

    function keys(text) {
        const p = get(text)
        return p.full === "" ? "" : (p.full === p.init ? p.full : p.full + " " + p.init)
    }

    function hasCjk(text) {
        return /[一-鿿]/.test(String(text ?? ""))
    }
}
