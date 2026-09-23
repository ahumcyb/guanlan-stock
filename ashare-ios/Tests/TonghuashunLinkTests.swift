import Foundation

@main struct TonghuashunLinkTests {
    static func main() {
        for (stock,code) in [("600519.SH","600519"),("300857.SZ","300857"),("920489.BJ","920489")] {
            assert(TonghuashunLink.searchCode(tsCode:stock)==code)
        }
        for rejected in ["600519", "600519.sh", "600519.HK", "000001.SHX", "../600519.SH", "", "000001.SH", "600519.SZ", "920489.SH"] {
            assert(TonghuashunLink.searchCode(tsCode:rejected)==nil,rejected)
        }
        print("Tonghuashun native-search code validation passed")
    }
}
