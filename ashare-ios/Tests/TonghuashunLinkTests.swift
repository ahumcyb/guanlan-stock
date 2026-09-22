import Foundation

@main struct TonghuashunLinkTests {
    static func main() {
        func require(_ code: String) -> String {
            guard let value = TonghuashunLink.urlString(tsCode: code) else { fatalError("missing \(code)") }
            return value
        }
        let shanghai = require("600519.SH")
        assert(shanghai == "amihexin://client.html?action=ymtz^webid=2205^stockcode=600519^marketid=17^tabid=14^fontzoom=no")
        assert(require("688981.SH").contains("stockcode=688981^marketid=17"))
        assert(require("000001.SZ") == "amihexin://client.html?action=ymtz^webid=2205^stockcode=000001^marketid=33^tabid=14^fontzoom=no")
        assert(require("300750.SZ").contains("marketid=33"))
        assert(require("920000.BJ").contains("stockcode=920000^marketid=151"))
        assert(require("000001.SH").contains("marketid=17"))
        assert(require("000001.SZ").contains("marketid=33"))
        for rejected in ["600519", "600519.sh", "600519.HK", "000001.SHX", "../600519.SH", ""] {
            assert(TonghuashunLink.urlString(tsCode: rejected) == nil, rejected)
            assert(TonghuashunLink.url(tsCode: rejected) == nil, rejected)
        }
        for code in ["600519.SH", "000001.SZ", "920489.BJ"] {
            let raw = require(code)
            guard let url = TonghuashunLink.url(tsCode: code) else { fatalError("url \(code)") }
            assert(url.scheme == "amihexin")
            let decoded = url.absoluteString.removingPercentEncoding ?? url.absoluteString
            assert(decoded == raw, decoded)
        }
        print("Tonghuashun link tests passed")
    }
}
