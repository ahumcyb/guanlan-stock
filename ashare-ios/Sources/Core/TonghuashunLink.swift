import Foundation

/// Verify an A-share code before handing it to 同花顺 native search.
enum TonghuashunLink {
    static func searchCode(tsCode: String) -> String? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ|BJ)$", options:.regularExpression) != nil else { return nil }
        let code=String(tsCode.prefix(6)), market=String(tsCode.suffix(2))
        guard (market=="SH" && code.hasPrefix("6")) ||
              (market=="SZ" && (code.hasPrefix("0") || code.hasPrefix("3"))) ||
              (market=="BJ" && (code.hasPrefix("8") || code.hasPrefix("9"))) else { return nil }
        return code
    }
}
