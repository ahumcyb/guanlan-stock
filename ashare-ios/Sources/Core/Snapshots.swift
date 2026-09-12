import Foundation
import CryptoKit

struct MobileManifest:Codable,Equatable {
    let schemaVersion:Int;let generation:String;let strategy:String;let asOf:String
    let reportBytes:Int;let reportSha256:String;let stockCount:Int;let dataRevision:String
    func validate() throws {
        guard schemaVersion==1,AfterCloseStrategies.supportedIds.contains(strategy),
              generation.range(of:"^\\d{8}T\\d{6}-[a-f0-9]{6}$",options:.regularExpression) != nil,
              asOf.range(of:"^\\d{8}$",options:.regularExpression) != nil,
              reportSha256.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
              (1...12*1024*1024).contains(reportBytes),(1...10000).contains(stockCount) else { throw MobileFailure.invalidData }
    }
    func decodeReport(_ data:Data) throws -> Report {
        try validate()
        guard data.count==reportBytes,SHA256.hash(data:data).map({String(format:"%02x",$0)}).joined()==reportSha256 else { throw MobileFailure.invalidData }
        let report=try mobileDecoder().decode(Report.self,from:data)
        guard report.schemaVersion==1,report.asOf==asOf,report.strategyId==strategy,report.dataRevision==dataRevision,
              report.stocks.count==stockCount,Set(report.stocks.map(\.id)).count==stockCount,
              report.stocks.allSatisfy({validStockCode($0.id) && $0.close>0 && (0...100).contains($0.score)}) else { throw MobileFailure.invalidData }
        return report
    }
}

func mobileDecoder()->JSONDecoder { let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase;return decoder }
func validStockCode(_ value:String)->Bool { value.range(of:"^\\d{6}\\.(SH|SZ|BJ)$",options:.regularExpression) != nil }

struct ServerJob:Codable {
    let id:String?;let status:String;let message:String;let action:String?;let createdAt:Double?
    let executor:String?
    var active:Bool { ["queued","running","publishing"].contains(status) }
}
struct ServerStatus:Decodable {
    let schemaVersion:Int;let job:ServerJob;let workerOnline:Bool;let canRefresh:Bool;let macOnline:Bool?
    let reports:[String:MobileManifest]
    let marketStatus:MarketStatus?
    let marketProvider:String?
}

struct MarketStatus:Codable {
    let expectedAsOf:String?;let phase:String;let checkedAt:Double;let calendarCovered:Bool
    let nextScreenAt:Double?
    func isCurrent(at now:Date=Date())->Bool { checkedAt.isFinite && (-15...300).contains(now.timeIntervalSince1970-checkedAt) }
    func needsUpdate(_ asOf:String)->Bool { isCurrent() && calendarCovered && expectedAsOf.map{asOf<$0}==true }
    func label(_ asOf:String)->String {
        guard isCurrent(),calendarCovered,let expectedAsOf else { return "日线截至 \(dateText(asOf)) · 完整日期待核验" }
        if asOf<expectedAsOf { return "等待 \(dateText(expectedAsOf)) 的完整收盘结果" }
        let phaseLabel=["before_open":"盘前","trading":"等待今日收盘数据","after_close":"收盘后","closed":"休市"]
        return "最新完整日线 \(dateText(asOf)) · \(phaseLabel[phase] ?? "已核验")"
    }
}

struct PublishedBundle:Codable {
    let schemaVersion:Int;let manifests:[String:MobileManifest]
    func validate() throws {
        guard schemaVersion==1,Set(manifests.keys)==Set(AfterCloseStrategies.ids) else { throw MobileFailure.invalidData }
        for (id,manifest) in manifests { try manifest.validate();guard manifest.strategy==id else { throw MobileFailure.invalidData } }
        guard Set(manifests.values.map(\.generation)).count==1,Set(manifests.values.map(\.dataRevision)).count==1,
              Set(manifests.values.map(\.asOf)).count==1 else { throw MobileFailure.invalidData }
    }
}

struct CachedSnapshot { let manifest:MobileManifest;let report:Report }

final class OfflineCache {
    let root:URL
    init(root:URL) { self.root=root }
    func load(_ strategy:String) throws -> CachedSnapshot? {
        guard AfterCloseStrategies.supportedIds.contains(strategy) else { throw MobileFailure.invalidData }
        let bundleFile=root.appendingPathComponent("bundle-current.json")
        if AfterCloseStrategies.ids.contains(strategy),FileManager.default.fileExists(atPath:bundleFile.path) {
            let bundle=try mobileDecoder().decode(PublishedBundle.self,from:Data(contentsOf:bundleFile));try bundle.validate()
            let manifest=bundle.manifests[strategy]!
            return try CachedSnapshot(manifest:manifest,report:manifest.decodeReport(Data(contentsOf:reportURL(manifest))))
        }
        let pointer=root.appendingPathComponent(strategy+"-current.json")
        guard FileManager.default.fileExists(atPath:pointer.path) else { return nil }
        let manifest=try mobileDecoder().decode(MobileManifest.self,from:Data(contentsOf:pointer));try manifest.validate()
        guard manifest.strategy==strategy else { throw MobileFailure.invalidData }
        let data=try Data(contentsOf:reportURL(manifest))
        return try CachedSnapshot(manifest:manifest,report:manifest.decodeReport(data))
    }
    @discardableResult func save(_ data:Data,manifest:MobileManifest) throws -> CachedSnapshot {
        let report=try manifest.decodeReport(data)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try data.write(to:reportURL(manifest),options:.atomic)
        let encoder=JSONEncoder();encoder.keyEncodingStrategy = .convertToSnakeCase
        try encoder.encode(manifest).write(to:root.appendingPathComponent(manifest.strategy+"-current.json"),options:.atomic)
        let protected=Set(AfterCloseStrategies.supportedIds.compactMap { try? load($0)?.manifest }.map { reportURL($0).lastPathComponent }).union([reportURL(manifest).lastPathComponent])
        for file in try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil) where file.lastPathComponent.hasSuffix("-report.json") && !protected.contains(file.lastPathComponent) { try? FileManager.default.removeItem(at:file) }
        return CachedSnapshot(manifest:manifest,report:report)
    }
    func cachedData(_ manifest:MobileManifest) throws -> Data? {
        try manifest.validate();let path=reportURL(manifest)
        guard FileManager.default.fileExists(atPath:path.path) else { return nil }
        let data=try Data(contentsOf:path)
        return data.count==manifest.reportBytes && SHA256.hash(data:data).map({String(format:"%02x",$0)}).joined()==manifest.reportSha256 ? data:nil
    }
    func saveBundle(_ reports:[String:Data],manifests:[String:MobileManifest]) throws {
        let bundle=PublishedBundle(schemaVersion:1,manifests:manifests);try bundle.validate()
        guard Set(reports.keys)==Set(manifests.keys) else { throw MobileFailure.invalidData }
        var universe:Set<String>?
        for id in AfterCloseStrategies.ids {
            let report=try manifests[id]!.decodeReport(reports[id]!)
            let codes=Set(report.stocks.map(\.id))
            if let universe,universe != codes { throw MobileFailure.invalidData };universe=codes
        }
        let bundleFile=root.appendingPathComponent("bundle-current.json")
        var previousFiles=Set<String>()
        if let data=try? Data(contentsOf:bundleFile),let previous=try? mobileDecoder().decode(PublishedBundle.self,from:data),(try? previous.validate()) != nil {
            previousFiles=Set(previous.manifests.values.map{reportURL($0).lastPathComponent})
        }
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        for id in AfterCloseStrategies.ids { try reports[id]!.write(to:reportURL(manifests[id]!),options:.atomic) }
        let encoder=JSONEncoder();encoder.keyEncodingStrategy = .convertToSnakeCase
        try encoder.encode(bundle).write(to:bundleFile,options:.atomic)
        for (id,manifest) in manifests { try encoder.encode(manifest).write(to:root.appendingPathComponent(id+"-current.json"),options:.atomic) }
        let currentFiles=Set(manifests.values.map{reportURL($0).lastPathComponent})
        let historical=Set(AfterCloseStrategies.supportedIds.filter{!AfterCloseStrategies.ids.contains($0)}.compactMap{try? load($0)?.manifest}.map{reportURL($0).lastPathComponent})
        let protected=currentFiles.union(previousFiles).union(historical)
        for file in try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil)
            where file.lastPathComponent.hasSuffix("-report.json") && !protected.contains(file.lastPathComponent) { try? FileManager.default.removeItem(at:file) }
    }
    private func reportURL(_ manifest:MobileManifest)->URL { root.appendingPathComponent(manifest.strategy+"-"+manifest.generation+"-report.json") }
    func chartURL(_ manifest:MobileManifest,code:String) throws -> URL {
        try manifest.validate();guard validStockCode(code) else { throw MobileFailure.invalidData }
        return root.appendingPathComponent("chart-"+manifest.generation+"-"+code+".json")
    }
    func loadChart(_ manifest:MobileManifest,code:String) throws -> [Candle]? {
        let path=try chartURL(manifest,code:code)
        guard FileManager.default.fileExists(atPath:path.path) else { return nil }
        return try decodeCandles(Data(contentsOf:path),asOf:manifest.asOf)
    }
    func saveChart(_ data:Data,manifest:MobileManifest,code:String) throws -> [Candle] {
        let candles=try decodeCandles(data,asOf:manifest.asOf)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try data.write(to:chartURL(manifest,code:code),options:.atomic)
        let files=try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.contentModificationDateKey]).filter{$0.lastPathComponent.hasPrefix("chart-")}
        let sorted=files.sorted{((try? $0.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)>((try? $1.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)}
        for file in sorted.dropFirst(100) { try? FileManager.default.removeItem(at:file) }
        return candles
    }
    func extendedChartURL(_ manifest:MobileManifest,code:String) throws -> URL {
        try manifest.validate();guard validStockCode(code) else { throw MobileFailure.invalidData }
        return root.appendingPathComponent("chartx-"+manifest.generation+"-"+code+".json")
    }
    func loadExtendedChart(_ manifest:MobileManifest,code:String) throws -> ChartDataset? {
        let path=try extendedChartURL(manifest,code:code)
        guard FileManager.default.fileExists(atPath:path.path) else { return nil }
        let info=try path.resourceValues(forKeys:[.isSymbolicLinkKey,.isRegularFileKey,.fileSizeKey])
        guard info.isSymbolicLink==false,info.isRegularFile==true,(info.fileSize ?? Int.max)<=512*1024 else { throw MobileFailure.invalidData }
        return try ChartDataset.decode(Data(contentsOf:path),code:code,asOf:manifest.asOf,revision:manifest.dataRevision)
    }
    func saveExtendedChart(_ data:Data,manifest:MobileManifest,code:String) throws -> ChartDataset {
        let path=try extendedChartURL(manifest,code:code)
        let value=try ChartDataset.decode(data,code:code,asOf:manifest.asOf,revision:manifest.dataRevision)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try data.write(to:path,options:.atomic)
        let files=try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.contentModificationDateKey]).filter{$0.lastPathComponent.hasPrefix("chartx-")}
        let sorted=files.sorted{((try? $0.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)>((try? $1.resourceValues(forKeys:[.contentModificationDateKey]).contentModificationDate) ?? .distantPast)}
        for file in sorted.dropFirst(100) { try? FileManager.default.removeItem(at:file) }
        return value
    }
}

func requestChartDataset(manifest:MobileManifest,code:String,cache:OfflineCache,api:MobileAPI?) async throws -> ChartDataset {
    try manifest.validate();guard validStockCode(code) else { throw MobileFailure.invalidData }
    if let saved=try? cache.loadExtendedChart(manifest,code:code) { return saved }
    let legacy=try? cache.loadChart(manifest,code:code)
    func old(_ bars:[Candle])->ChartDataset { ChartDataset.legacy(bars,code:code,asOf:manifest.asOf,revision:manifest.dataRevision) }
    guard let api else {
        if let legacy { return old(legacy) }
        throw MobileFailure.server("连接服务器后可下载这只股票的K线。")
    }
    do {
        let bytes=try await api.request("/v1/reports/\(manifest.strategy)/\(manifest.generation)/charts-extended/\(code).json",limit:512*1024)
        try Task.checkCancellation()
        return try cache.saveExtendedChart(bytes,manifest:manifest,code:code)
    } catch MobileFailure.expiredSnapshot {
        if let legacy { return old(legacy) }
        let bytes=try await api.request("/v1/reports/\(manifest.strategy)/\(manifest.generation)/charts/\(code).json",limit:128*1024)
        try Task.checkCancellation()
        return old(try cache.saveChart(bytes,manifest:manifest,code:code))
    } catch let error as URLError {
        if error.code != .cancelled,let legacy { return old(legacy) }
        throw error
    }
}

func latestChartDataset(code:String,through:String?,cache:OfflineCache,api:MobileAPI?,fallback:MobileManifest?) async throws -> ChartDataset {
    var manifest=fallback
    if let api {
        do {
            let data=try await api.request("/v1/reports/leaders/current",limit:65536)
            let latest=try mobileDecoder().decode(MobileManifest.self,from:data);try latest.validate();manifest=latest
        } catch let error as URLError { if error.code == .cancelled || fallback==nil { throw error } }
    }
    guard let manifest else { throw MobileFailure.server("请先同步已发布的行情结果。") }
    if let through,manifest.asOf<through { throw MobileFailure.server("当前K线版本尚未覆盖这篇总结的日期，请同步结果后重试。") }
    return try await requestChartDataset(manifest:manifest,code:code,cache:cache,api:api)
}

func synchronizePublishedBundle(_ api:MobileAPI,cache:OfflineCache,manifests:[String:MobileManifest]) async throws {
    try PublishedBundle(schemaVersion:1,manifests:manifests).validate()
    var reports:[String:Data]=[:];var changed=false
    for id in AfterCloseStrategies.ids {
        let manifest=manifests[id]!
        if let data=try cache.cachedData(manifest) { reports[id]=data }
        else {
            reports[id]=try await api.request("/v1/reports/\(id)/\(manifest.generation)/report.json",limit:manifest.reportBytes);changed=true
        }
    }
    let pointer=try? Data(contentsOf:cache.root.appendingPathComponent("bundle-current.json"))
    let current=pointer.flatMap { try? mobileDecoder().decode(PublishedBundle.self,from:$0) }
    let matching=current.map { (try? $0.validate()) != nil && $0.manifests==manifests } ?? false
    if changed || !matching {
        let complete=reports
        try await Task.detached(priority:.utility) { try cache.saveBundle(complete,manifests:manifests) }.value
    }
}

func decodeCandles(_ data:Data,asOf:String) throws -> [Candle] {
    guard data.count<=128*1024 else { throw MobileFailure.oversized }
    let candles=try mobileDecoder().decode([Candle].self,from:data)
    guard !candles.isEmpty,candles.count<=120,Set(candles.map(\.date)).count==candles.count,
          candles.map(\.date)==candles.map(\.date).sorted(),candles.allSatisfy({ChartDate.parse($0.date) != nil && $0.date<=asOf && $0.low>0 && $0.high >= max($0.open,$0.close) && $0.low<=min($0.open,$0.close) && $0.volume>=0
              && [$0.open,$0.high,$0.low,$0.close,$0.volume].allSatisfy(\.isFinite)
              && [$0.ma10,$0.ma20,$0.ma60].compactMap({$0}).allSatisfy({$0.isFinite && $0>0})}) else { throw MobileFailure.invalidData }
    return candles
}
