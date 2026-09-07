import Foundation

@main struct NativeModelTests {
    static func main() throws {
        assert(csvCell("=HYPERLINK(\"https://example.test\")").hasPrefix("\"'="))
        assert(csvCell("  +formula").hasPrefix("\"'"))
        assert(csvCell("-1.25") == "\"-1.25\"")
        assert(csvCell("名称\"测试") == "\"名称\"\"测试\"")
        print("Native CSV safety: 4 assertions passed")
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let month=try decoder.decode(MonthStats.self,from:Data(#"{"month":"202606","count":0,"total":0,"mean":null,"win_rate":null,"statuses":{}}"#.utf8))
        assert(month.sampleLabel=="无信号" && month.mean==nil)
        let nextYear=try decoder.decode(MonthStats.self,from:Data(#"{"month":"202706","count":0,"total":0,"mean":null,"win_rate":null,"statuses":{}}"#.utf8))
        assert(month.displayMonth != nextYear.displayMonth)
        let mixed=try decoder.decode(MonthStats.self,from:Data(#"{"month":"202607","count":1,"total":2,"mean":0.01,"win_rate":1,"statuses":{"settled":1,"pending":1}}"#.utf8))
        assert(mixed.sampleLabel=="已结算 1 次")
        let pending=try decoder.decode(MonthStats.self,from:Data(#"{"month":"202609","count":0,"total":5,"mean":null,"win_rate":null,"statuses":{"pending":5}}"#.utf8))
        assert(pending.sampleLabel=="待观察结束")
        print("Native empty month and pending outcome labels passed")
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
