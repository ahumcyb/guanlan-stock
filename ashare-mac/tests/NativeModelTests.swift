import Foundation

@main struct NativeModelTests {
    static func main() {
        assert(csvCell("=HYPERLINK(\"https://example.test\")").hasPrefix("\"'="))
        assert(csvCell("  +formula").hasPrefix("\"'"))
        assert(csvCell("-1.25") == "\"-1.25\"")
        assert(csvCell("名称\"测试") == "\"名称\"\"测试\"")
        print("Native CSV safety: 4 assertions passed")
    }
}
