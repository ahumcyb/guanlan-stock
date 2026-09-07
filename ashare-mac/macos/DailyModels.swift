import Foundation

func validDailyDate(_ value:String)->Bool {
    guard value.range(of:"^[0-9]{8}$",options:.regularExpression) != nil else { return false }
    let format=DateFormatter();format.locale=Locale(identifier:"en_US_POSIX")
    format.calendar=Calendar(identifier:.gregorian);format.dateFormat="yyyyMMdd";format.isLenient=false
    return format.date(from:value) != nil
}
func dailyChange(_ value:Double)->String { String(format:"%+.2f%%",value) }
func dailyTime(_ value:Double?)->String {
    guard let value,value.isFinite else { return "—" }
    let format=DateFormatter();format.locale=Locale(identifier:"zh_CN");format.timeZone=TimeZone(identifier:"Asia/Shanghai")
    format.dateFormat="MM-dd HH:mm";return format.string(from:Date(timeIntervalSince1970:value))
}
struct DailySettings:Codable {
    let enabled:Bool;let notificationEnabled:Bool;let aiEnabled:Bool
    let model:String;let deepseekConfigured:Bool;let barkConfigured:Bool
}
struct DailyStatus:Codable {
    let date:String?;let phase:String;let message:String;let retryAt:Double?;let nextRunAt:Double?
}
struct DailyHistory:Codable,Identifiable {
    let date:String;let headline:String;let aiStatus:String
    var id:String { date }
}
struct DailyState:Codable {
    let schemaVersion:Int;let settings:DailySettings;let latest:DailyReport?
    let history:[DailyHistory];let status:DailyStatus
    let schedulerOnline:Bool?
    func validate() throws {
        guard schemaVersion==1,history.count<=30,history.allSatisfy({validDailyDate($0.date) && $0.headline.count<=100}),
              status.message.count<=500 else { throw CocoaError(.fileReadCorruptFile) }
        try latest?.validate()
    }
}
struct DailyReport:Codable {
    let schemaVersion:Int;let date:String;let generatedAt:Double;let evidenceSha256:String
    let evidence:DailyEvidence;let analysis:DailyAnalysis
    func validate() throws {
        let market=evidence.market
        guard schemaVersion==1,validDailyDate(date),date==evidence.date,generatedAt.isFinite,
              evidenceSha256.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
              (1...10000).contains(market.stockCount),market.advancers>=0,market.decliners>=0,market.unchanged>=0,
              market.advancers+market.decliners+market.unchanged==market.stockCount,
              market.turnoverYi.isFinite,market.turnoverYi>=0,market.medianChange.isFinite,(0...1).contains(market.breadth),
              evidence.strategies.count==4,Set(evidence.strategies.map(\.id))==Set(AfterCloseStrategies.ids),
              evidence.sectorsStrong.count<=5,evidence.sectorsWeak.count<=5,
              ["ready","pending","unavailable"].contains(analysis.status),analysis.risks.count<=5,
              [analysis.headline,analysis.marketView,analysis.sectorView,analysis.strategyView,analysis.watchNext].allSatisfy({$0.count<=1000}) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        for strategy in evidence.strategies {
            guard strategy.picks.count==strategy.shortlistCount,strategy.picks.count<=10,
                  strategy.picks.allSatisfy({$0.close.isFinite && $0.close>0 && $0.change.isFinite && (0...100).contains($0.score)}) else {
                throw CocoaError(.fileReadCorruptFile)
            }
        }
    }
}
struct DailyEvidence:Codable {
    let date:String;let generation:String;let dataRevision:String;let fetchedAt:String;let universeLabel:String
    let market:DailyMarketFacts;let sectorsStrong:[DailySector];let sectorsWeak:[DailySector]
    let strategies:[DailyStrategyFacts];let warnings:[String]
}
struct DailyMarketFacts:Codable {
    let stockCount:Int;let advancers:Int;let decliners:Int;let unchanged:Int;let turnoverYi:Double
    let medianChange:Double;let limitUp:Int;let limitDown:Int;let limitsUnclassified:Int;let breadth:Double
}
struct DailySector:Codable,Identifiable {
    let name:String;let members:Int;let meanChange:Double;let turnoverYi:Double
    var id:String { name }
}
struct DailyStrategyFacts:Codable,Identifiable {
    let id:String;let name:String;let shortlistCount:Int;let confirmedCount:Int;let watchingCount:Int;let picks:[DailyPick]
    let marketFilterApplies:Bool?;let marketFilterPassed:Bool?
}
struct DailyPick:Codable,Identifiable {
    let tsCode:String;let name:String;let industry:String;let close:Double;let change:Double;let score:Double;let rank:Int
    var id:String { tsCode }
}
struct DailyAnalysis:Codable {
    let status:String;let headline:String;let marketView:String;let sectorView:String;let strategyView:String;let watchNext:String
    let risks:[String];let model:String?;let errorCode:String?
}

func dailyDecoder()->JSONDecoder { let value=JSONDecoder();value.keyDecodingStrategy = .convertFromSnakeCase;return value }

final class DailyCache {
    let root:URL
    init(root:URL) { self.root=root }
    private func read(_ file:URL) throws -> Data {
        let info=try file.resourceValues(forKeys:[.fileSizeKey,.isSymbolicLinkKey])
        guard info.isSymbolicLink != true,let size=info.fileSize,size<=128*1024 else { throw CocoaError(.fileReadCorruptFile) }
        return try Data(contentsOf:file)
    }
    func loadState() throws -> DailyState {
        let result=try dailyDecoder().decode(DailyState.self,from:read(root.appendingPathComponent("state.json")))
        try result.validate();return result
    }
    @discardableResult func saveState(_ data:Data) throws -> DailyState {
        guard data.count<=128*1024 else { throw CocoaError(.fileReadCorruptFile) }
        let value=try dailyDecoder().decode(DailyState.self,from:data);try value.validate()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try data.write(to:root.appendingPathComponent("state.json"),options:.atomic)
        if let object=try JSONSerialization.jsonObject(with:data) as? [String:Any],let report=object["latest"] as? [String:Any] {
            _=try saveReport(JSONSerialization.data(withJSONObject:report))
        }
        return value
    }
    func loadReport(_ date:String) throws -> DailyReport {
        guard validDailyDate(date) else { throw CocoaError(.fileReadCorruptFile) }
        let report=try dailyDecoder().decode(DailyReport.self,from:read(root.appendingPathComponent(date+".json")))
        try report.validate();guard report.date==date else { throw CocoaError(.fileReadCorruptFile) };return report
    }
    @discardableResult func saveReport(_ data:Data) throws -> DailyReport {
        guard data.count<=128*1024 else { throw CocoaError(.fileReadCorruptFile) }
        let value=try dailyDecoder().decode(DailyReport.self,from:data);try value.validate()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try data.write(to:root.appendingPathComponent(value.date+".json"),options:.atomic);return value
    }
}
