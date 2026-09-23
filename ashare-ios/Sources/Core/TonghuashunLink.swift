import Foundation

/// 同花顺官方手机个股页，经其关联域名的 Universal Link 在 iOS App 内打开。
enum TonghuashunLink {
    static func url(tsCode: String) -> URL? {
        guard let raw = urlString(tsCode: tsCode) else { return nil }
        return URL(string: raw)
    }

    static func urlString(tsCode: String) -> String? {
        guard let page = pageURL(tsCode: tsCode) else { return nil }
        var components = URLComponents()
        components.scheme = "https"
        components.host = "backwash.10jqka.com.cn"
        components.path = "/universalLink/sjcg.html"
        components.queryItems = [URLQueryItem(name: "url", value: page.absoluteString)]
        return components.url?.absoluteString
    }

    static func searchCode(tsCode: String) -> String? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ|BJ)$", options:.regularExpression) != nil else { return nil }
        let code=String(tsCode.prefix(6)), market=String(tsCode.suffix(2))
        guard (market=="SH" && code.hasPrefix("6")) ||
              (market=="SZ" && (code.hasPrefix("0") || code.hasPrefix("3"))) ||
              (market=="BJ" && (code.hasPrefix("8") || code.hasPrefix("9"))) else { return nil }
        return code
    }

    static func pageURL(tsCode: String) -> URL? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ)$", options: .regularExpression) != nil else { return nil }
        let code = String(tsCode.prefix(6))
        let market = String(tsCode.suffix(2))
        guard (market == "SH" && code.hasPrefix("6")) ||
              (market == "SZ" && (code.hasPrefix("0") || code.hasPrefix("3"))) else { return nil }
        return URL(string: "https://m.10jqka.com.cn/stockpage/hs_\(code)/")
    }
}
