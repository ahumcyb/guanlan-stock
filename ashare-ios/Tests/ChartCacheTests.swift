import Foundation

@main struct ChartCacheTests {
    static func main() async throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let cache=OfflineCache(root:root)
        let manifest=MobileManifest(schemaVersion:1,generation:"20260911T162000-abcdef",strategy:"leaders",asOf:"20260911",
            reportBytes:100,reportSha256:String(repeating:"a",count:64),stockCount:1,dataRevision:"20260911-"+String(repeating:"a",count:16))
        let row:[String:Any] = ["date":"20260911","open":10.0,"high":12.0,"low":9.0,"close":11.0,"ma10":NSNull(),"ma20":NSNull(),"ma60":NSNull(),"volume":10000.0,
            "raw_open":10.0,"raw_high":12.0,"raw_low":9.0,"raw_close":11.0,"raw_pre_close":10.0,"amount":11000.0]
        let value:[String:Any] = ["schema_version":1,"ts_code":"600000.SH","as_of":manifest.asOf,"data_revision":manifest.dataRevision,
            "price_basis":"continuous_latest_close","volume_unit":"lot","bars":[row]]
        let bytes=try JSONSerialization.data(withJSONObject:value)
        _=try cache.saveExtendedChart(bytes,manifest:manifest,code:"600000.SH")
        let cached=try cache.loadExtendedChart(manifest,code:"600000.SH")
        assert(cached?.bars.count==1 && cached!.canUseRaw)
        var wrong=value;wrong["ts_code"]="600001.SH"
        do { _=try cache.saveExtendedChart(JSONSerialization.data(withJSONObject:wrong),manifest:manifest,code:"600000.SH");assertionFailure("Wrong stock overwrote cache") } catch {}
        let preserved=try cache.loadExtendedChart(manifest,code:"600000.SH");assert(preserved?.tsCode=="600000.SH")
        let loaded=try await requestChartDataset(manifest:manifest,code:"600000.SH",cache:cache,api:nil)
        assert(!loaded.isLegacy)
        let legacy=try JSONSerialization.data(withJSONObject:[["date":"20260911","open":10.0,"high":12.0,"low":9.0,"close":11.0,"ma10":NSNull(),"ma20":NSNull(),"ma60":NSNull(),"volume":10000.0] as [String:Any]])
        _=try cache.saveChart(legacy,manifest:manifest,code:"600001.SH")
        let old=try await requestChartDataset(manifest:manifest,code:"600001.SH",cache:cache,api:nil)
        assert(old.isLegacy && !old.canUseRaw)
        let path=try cache.extendedChartURL(manifest,code:"600000.SH")
        try FileManager.default.removeItem(at:path)
        let target=root.appendingPathComponent("outside.json");try bytes.write(to:target)
        try FileManager.default.createSymbolicLink(at:path,withDestinationURL:target)
        do { _=try cache.loadExtendedChart(manifest,code:"600000.SH");assertionFailure("Symlink accepted") } catch {}
        print("Extended chart cache binds code/date/revision, preserves valid data and supports offline legacy fallback")
    }
}
