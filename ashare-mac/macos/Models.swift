import Foundation

struct SnapshotPointer: Decodable { let generation: String; let asOf: String; let sha256: String }
struct Runtime: Codable { let projectRoot: String; let python: String }
struct SourceInfo: Decodable, Identifiable {
    let kind: String; let rows: Int; let files: Int; let start: String; let end: String
    var id: String { kind }
    var title: String { ["daily":"日线行情", "adj_factor":"复权因子", "stk_limit":"涨跌停价"][kind] ?? kind }
}
struct UpdateFailure: Decodable, Identifiable {
    let date: String; let error: String
    var id: String { date }
}
struct UpdateResult: Decodable {
    let through: String; let updatedDays: Int; let checkedSessions: Int
    let validation: String; let failures: [UpdateFailure]?
}
struct Stock: Decodable, Identifiable, Hashable {
    let tsCode: String; let name: String; let industry: String; let tradeDate: String
    let close: Double; let change: Double; let score: Double; let state: String; let rank: Int
    let eligible: Bool; let stale: Bool; let adjusted: Bool; let limitAvailable: Bool
    let ret20: Double?; let rs20: Double?; let atr: Double?; let volumeRatio: Double?
    let pullback: Double?; let `extension`: Double?; let amount20: Double?
    let support: Double?; let breakout: Double?; let invalidation: Double?
    let trendOk: Bool; let strengthOk: Bool; let pullbackOk: Bool; let volumeOk: Bool; let turnOk: Bool
    let strengthScore: Double?; let trendScore: Double?; let positionScore: Double?
    let volumeScore: Double?; let riskScore: Double?
    let liquidityRank: Double?
    var id: String { tsCode }
    var symbol: String { String(tsCode.prefix(6)) }
}
struct Candle: Decodable, Identifiable {
    let date: String; let open: Double; let high: Double; let low: Double; let close: Double
    let ma10: Double?; let ma20: Double?; let ma60: Double?; let volume: Double
    var id: String { date }
}
struct StudyStats: Decodable {
    let count: Int; let total: Int; let mean: Double?; let median: Double?
    let winRate: Double?; let stressMean: Double?; let worst: Double?; let p10: Double?
    let statuses: [String:Int]
}
struct Horizon: Decodable, Identifiable {
    let horizon: Int; let count: Int; let total: Int; let mean: Double?; let median: Double?
    let winRate: Double?; let stressMean: Double?; let worst: Double?; let p10: Double?
    let statuses: [String:Int]; let benchmark: StudyStats
    var id: Int { horizon }
}
struct MonthStats: Decodable, Identifiable {
    let month: String; let count: Int; let total: Int; let mean: Double?; let winRate: Double?
    let statuses: [String:Int]
    var id: String { month }
}
struct Study: Decodable {
    let start: String; let end: String; let horizons: [Horizon]; let monthly: [MonthStats]
    let benchmarkLabel: String
}
struct Report: Decodable {
    let schemaVersion: Int; let version: String; let asOf: String; let generatedAt: String
    let sourceRoot: String; let overlayRoot: String; let priceRows: Int; let universeCount: Int
    let eligibleCount: Int; let confirmedCount: Int; let shortlistCount: Int; let watchingCount: Int
    let breadth: Double; let regime: String; let staleSessions: Int
    let missingAdjustmentToday: Int; let missingLimitsToday: Int
    let sources: [SourceInfo]; let warnings: [String]; let stocks: [Stock]; let backtest: Study
    let lastUpdate: UpdateResult?
    let strategyId: String?; let strategyName: String?
    var isLeaders:Bool { strategyId=="leaders" }
}

func dateText(_ value: String) -> String {
    guard value.count == 8 else { return value }
    let a = Array(value)
    return String(a[0..<4])+"-"+String(a[4..<6])+"-"+String(a[6..<8])
}
func decimal(_ value: Double?, digits: Int = 2) -> String {
    guard let value, value.isFinite else { return "—" }
    return String(format: "%.*f", digits, value)
}
func percent(_ value: Double?, signed: Bool = false) -> String {
    guard let value, value.isFinite else { return "—" }
    return String(format: signed ? "%+.2f%%" : "%.2f%%", value*100)
}
