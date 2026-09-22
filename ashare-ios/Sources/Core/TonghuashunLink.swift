import Foundation

/// iOS link into 同花顺. Scheme `amihexin` is from the app's own backWash script;
/// the stock path matches thsc-f10-utils `client://client.html?action=ymtz^webid=2205…`,
/// with SH/SZ/BJ mapped to market ids 17/33/151.
enum TonghuashunLink {
    static let scheme = "amihexin"

    static func url(tsCode: String) -> URL? {
        guard let raw = urlString(tsCode: tsCode) else { return nil }
        if let url = URL(string: raw) { return url }
        let encoded = raw.replacingOccurrences(of: "^", with: "%5E")
        return URL(string: encoded)
    }

    static func urlString(tsCode: String) -> String? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ|BJ)$", options: .regularExpression) != nil else { return nil }
        let parts = tsCode.split(separator: ".")
        guard parts.count == 2, let market = marketID(String(parts[1])) else { return nil }
        let code = String(parts[0])
        return "\(scheme)://client.html?action=ymtz^webid=2205^stockcode=\(code)^marketid=\(market)^tabid=14^fontzoom=no"
    }

    private static func marketID(_ suffix: String) -> String? {
        switch suffix {
        case "SH": return "17"
        case "SZ": return "33"
        case "BJ": return "151"
        default: return nil
        }
    }
}
