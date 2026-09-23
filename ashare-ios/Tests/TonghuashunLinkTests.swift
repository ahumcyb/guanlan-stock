import Foundation

@main struct TonghuashunLinkTests {
    static func main() {
        for (code,stock) in [("603019.SH","603019"),("600519.SH","600519"),("000001.SZ","000001")] {
            let page="https://m.10jqka.com.cn/stockpage/hs_\(stock)/"
            assert(TonghuashunLink.pageURL(tsCode:code)?.absoluteString==page)
            guard let link=TonghuashunLink.url(tsCode:code),
                  let parts=URLComponents(url:link,resolvingAgainstBaseURL:false) else { fatalError("missing \(code)") }
            assert(parts.scheme=="https" && parts.host=="backwash.10jqka.com.cn")
            assert(parts.path=="/universalLink/sjcg.html")
            assert(parts.queryItems?.count==1 && parts.queryItems?.first?.name=="url")
            assert(parts.queryItems?.first?.value==page)
            assert(link.absoluteString==TonghuashunLink.urlString(tsCode:code))
        }
        for code in ["600519", "600519.sh", "600519.HK", "000001.SHX", "../600519.SH", "", "920489.BJ", "000001.SH", "600519.SZ"] {
            assert(TonghuashunLink.pageURL(tsCode:code)==nil,code)
            assert(TonghuashunLink.url(tsCode:code)==nil,code)
        }
        print("Tonghuashun verified universal-link tests passed")
    }
}
