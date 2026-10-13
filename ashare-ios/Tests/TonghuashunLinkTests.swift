import Foundation

@main struct TonghuashunLinkTests {
    static func main() {
        for (stock,code) in [("600519.SH","600519"),("300857.SZ","300857"),("920489.BJ","920489")] {
            assert(TonghuashunLink.searchCode(tsCode:stock)==code)
        }
        for rejected in ["600519", "600519.sh", "600519.HK", "000001.SHX", "../600519.SH", "", "000001.SH", "600519.SZ", "920489.SH"] {
            assert(TonghuashunLink.searchCode(tsCode:rejected)==nil,rejected)
        }
        assert(TonghuashunLink.nativeQuoteURL(tsCode:"600519.SH")?.absoluteString=="amihexin://url=https%3A%2F%2Fm.10jqka.com.cn%2Fclient.html%3Faction%3Dymtz%5Ewebid%3D2205%5Estockcode%3D600519%5Emarketid%3D17")
        assert(TonghuashunLink.nativeQuoteURL(tsCode:"300857.SZ")?.absoluteString.hasSuffix("stockcode%3D300857%5Emarketid%3D33")==true)
        assert(TonghuashunLink.nativeQuoteURL(tsCode:"920489.BJ")==nil)
        for rejected in ["600519","600519.SZ","../600519.SH",""] { assert(TonghuashunLink.nativeQuoteURL(tsCode:rejected)==nil,rejected) }
        print("Tonghuashun native-search code validation passed")
    }
}
