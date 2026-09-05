import Foundation

func sameDataDirectory(_ lhs:String,_ rhs:String)->Bool {
    // URL equality distinguishes trailing directory slashes after symlink resolution.
    URL(fileURLWithPath:lhs).standardizedFileURL.resolvingSymlinksInPath().path
        == URL(fileURLWithPath:rhs).standardizedFileURL.resolvingSymlinksInPath().path
}

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
    let pitPeakDate: String?; let pitTroughDate: String?
    let pitDepth: Double?; let pitAge: Double?; let pitFallDays: Double?; let pitRebound: Double?
    let pitContraction: Double?; let pitRecoveryVolume: Double?; let pitPeak: Double?; let pitLow: Double?
    let ma60Slope: Double?; let ret60: Double?
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
    let dataRevision:String?
    var isLeaders:Bool { strategyId=="leaders" }
    var isGoldenPit:Bool { strategyId=="golden_pit" }
}

enum GoldenPitGuide {
    static let summary = "寻找上升趋势中的缩量深回撤，在见底后重新收复均线、放量转强时进入观察。使用收盘后的完整日线，研究持有 1–5 个交易日。"
    static let rules = [
        "基础池：沪深非 ST / 退市名称，至少 80 根日线，最近 60 个交易日连续有行情；股价 ≥3 元，20 日平均成交额 ≥1 亿元，ATR / 价格 ≤6%。",
        "趋势：收盘高于 MA60，MA60 高于 5 日前；60 日涨幅大于 0、不超过 60%。",
        "坑形：最近 30 个交易日先出现最高价，其后出现最低价；回撤 8%–20%，高点到低点相隔 3–20 日，低点距今 2–8 日。同价取最近一天，创新低或再次触底会重新计时。",
        "缩量与修复：低点及前 2 日平均成交额，最多为高点及前 4 日均额的 80%；反弹 3%–12%，收盘 ≥MA10，距 MA20 为 -3% 至 8%，当天涨跌幅 -3% 至 5%。形态窗口内缺成交不入选。",
        "右侧确认：收盘 ≥MA20，当天上涨 0.3%–5%，收在日内振幅上部 40%；当日成交额 ≥此前 5 日均额的 1.2 倍。形态满足但尚未确认的列入“等待”。",
        "市场与排序：基础池中至少 40% 的股票站上 MA20，否则暂停新候选。匹配分由趋势 20、60 日涨幅 20、坑深及反弹位置 25、缩量 20、低波动 15 构成；最多精选 10 只，每行业最多 2 只。",
        "观察计划：MA20 为回踩参考，前期高点为坑口压力；失效参考取坑底下方 1% 与收盘价减 1.5 ATR 的较高者。次日高开超过 3% 或涨停不追入，默认研究持有 3 日。历史检验扣双边合计 0.3% 成本，并列出 1 / 3 / 5 日及成本翻倍结果，未模拟盘中止损。",
        "这是固定参数的技术形态研究，不包含基本面或估值筛选。形态价格以每日 close / 除权参考前收串联，事件收益使用复权因子；存在历史名单与行业回溯偏差，尚未完成独立样本外验证。匹配分不是胜率。"
    ]
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

func csvCell(_ value:String)->String {
    let first=value.trimmingCharacters(in:.whitespacesAndNewlines).first
    let formula=first.map { ["=","+","-","@"].contains(String($0)) } ?? false
    let safe=formula && Double(value)==nil ? "'"+value:value
    return "\""+safe.replacingOccurrences(of:"\"",with:"\"\"")+"\""
}
