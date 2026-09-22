import Foundation

@main struct TonghuashunLinkTests {
    static func main() {
        func require(_ code: String) -> String {
            guard let value = TonghuashunLink.urlString(tsCode: code) else { fatalError("missing \(code)") }
            return value
        }
        assert(require("600519.SH") == "https://stockpage.10jqka.com.cn/600519/")
        assert(require("000001.SZ") == "https://stockpage.10jqka.com.cn/000001/")
        for rejected in ["600519", "600519.sh", "600519.HK", "000001.SHX", "../600519.SH", "", "920489.BJ", "000001.SH", "600519.SZ"] {
            assert(TonghuashunLink.urlString(tsCode: rejected) == nil, rejected)
            assert(TonghuashunLink.url(tsCode: rejected) == nil, rejected)
        }
        for code in ["600519.SH", "000001.SZ"] {
            let raw = require(code)
            guard let url = TonghuashunLink.url(tsCode: code) else { fatalError("url \(code)") }
            assert(url.scheme == "https" && url.host == "stockpage.10jqka.com.cn")
            assert(url.absoluteString == raw)
        }
        print("Tonghuashun link tests passed")
    }
}
