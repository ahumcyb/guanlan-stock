import Foundation

/// Verified links into 同花顺 for A-share stocks.
enum TonghuashunLink {
    static func searchCode(tsCode: String) -> String? {
        guard tsCode.range(of: "^\\d{6}\\.(SH|SZ|BJ)$", options:.regularExpression) != nil else { return nil }
        let code=String(tsCode.prefix(6)), market=String(tsCode.suffix(2))
        guard (market=="SH" && code.hasPrefix("6")) ||
              (market=="SZ" && (code.hasPrefix("0") || code.hasPrefix("3"))) ||
              (market=="BJ" && (code.hasPrefix("8") || code.hasPrefix("9"))) else { return nil }
        return code
    }

    /// Same character set as JavaScript encodeURIComponent, which 同花顺's own backwash script uses.
    private static let component=CharacterSet.alphanumerics.union(CharacterSet(charactersIn:"-_.!~*'()"))

    /// Opens the native quote page. 同花顺 loads `url` in its web view and intercepts
    /// same-domain `client.html?action=…` requests, as its own H5 pages do; verified on
    /// iPhone 2026-10-13. Beijing listings have no verified market id and return nil.
    static func nativeQuoteURL(tsCode: String) -> URL? {
        guard let code=searchCode(tsCode:tsCode) else { return nil }
        let market:String
        switch tsCode.suffix(2) { case "SH":market="17"; case "SZ":market="33"; default:return nil }
        let command="https://m.10jqka.com.cn/client.html?action=ymtz^webid=2205^stockcode=\(code)^marketid=\(market)"
        guard let encoded=command.addingPercentEncoding(withAllowedCharacters:component) else { return nil }
        return URL(string:"amihexin://url="+encoded)
    }
}
