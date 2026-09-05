import Foundation

@main struct NativeModelTests {
    static func main() throws {
        assert(csvCell("=HYPERLINK(\"https://example.test\")").hasPrefix("\"'="))
        assert(csvCell("  +formula").hasPrefix("\"'"))
        assert(csvCell("-1.25") == "\"-1.25\"")
        assert(csvCell("名称\"测试") == "\"名称\"\"测试\"")
        print("Native CSV safety: 4 assertions passed")
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let release=root.appendingPathComponent("release",isDirectory:true)
        let current=root.appendingPathComponent("current")
        try FileManager.default.createDirectory(at:release,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:root) }
        try FileManager.default.createSymbolicLink(at:current,withDestinationURL:release)
        assert(sameDataDirectory(release.path,current.path))
        assert(!sameDataDirectory(release.path,root.path))
        print("Native data source: symlink cache and source isolation assertions passed")
    }
}
