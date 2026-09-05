import Foundation
import CryptoKit

struct MobileManifest:Codable,Equatable {
    let schemaVersion:Int;let generation:String;let strategy:String;let asOf:String
    let reportBytes:Int;let reportSha256:String;let stockCount:Int;let dataRevision:String
    func validate() throws {
        guard schemaVersion==1,["leaders","pullback","golden_pit"].contains(strategy),
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
}

struct CachedSnapshot { let manifest:MobileManifest;let report:Report }

final class OfflineCache {
    let root:URL
    init(root:URL) { self.root=root }
    func load(_ strategy:String) throws -> CachedSnapshot? {
        guard ["leaders","pullback","golden_pit"].contains(strategy) else { throw MobileFailure.invalidData }
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
        let protected=Set(["leaders","pullback","golden_pit"].compactMap { try? load($0)?.manifest }.map { reportURL($0).lastPathComponent })
        for file in try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil) where file.lastPathComponent.hasSuffix("-report.json") && !protected.contains(file.lastPathComponent) { try? FileManager.default.removeItem(at:file) }
        return CachedSnapshot(manifest:manifest,report:report)
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
}

func decodeCandles(_ data:Data,asOf:String) throws -> [Candle] {
    guard data.count<=128*1024 else { throw MobileFailure.oversized }
    let candles=try mobileDecoder().decode([Candle].self,from:data)
    guard !candles.isEmpty,candles.count<=120,Set(candles.map(\.date)).count==candles.count,
          candles.map(\.date)==candles.map(\.date).sorted(),candles.allSatisfy({$0.date<=asOf && $0.low>0 && $0.high >= max($0.open,$0.close) && $0.low<=min($0.open,$0.close) && $0.volume>=0}) else { throw MobileFailure.invalidData }
    return candles
}
