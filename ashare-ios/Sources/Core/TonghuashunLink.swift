import Foundation

/// Verified 同花顺 stock-page URL. The prior amihexin scheme only launched the
/// iOS app and did not honor the desktop client.html stock parameters.
enum TonghuashunLink {
    static func url(tsCode: String) -> URL? {
        guard let raw = urlString(tsCode: tsCode) else { return nil }
        return URL(string: raw)
    }

    static func urlString(tsCode: String) -> String? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ)$", options: .regularExpression) != nil else { return nil }
        let code = String(tsCode.prefix(6))
        let market = String(tsCode.suffix(2))
        guard (market == "SH" && code.hasPrefix("6")) ||
              (market == "SZ" && (code.hasPrefix("0") || code.hasPrefix("3"))) else { return nil }
        return "https://stockpage.10jqka.com.cn/\(code)/"
    }
}
