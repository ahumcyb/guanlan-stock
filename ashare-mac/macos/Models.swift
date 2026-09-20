import Foundation

enum AfterCloseStrategies {
    static let previousIds = ["leaders", "pullback", "golden_pit", "left_rebound"]
    static let ids = previousIds + ["orderflow"]
    static let historicalIds = ["leaders", "pullback", "golden_pit", "momentum_60"]
    static let supportedIds = ids + ["momentum_60"]
    static func validGroup(_ values:[String])->Bool { values.count==Set(values).count && (Set(values)==Set(ids) || Set(values)==Set(previousIds) || Set(values)==Set(historicalIds)) }
    static func activeChoice(_ saved:String?)->String { saved=="momentum_60" ? "left_rebound" : (ids.contains(saved ?? "") ? saved!:"leaders") }
    static func shortName(_ id:String)->String {
        ["orderflow":"大单承接", "leaders":"流动性趋势", "pullback":"缩量回踩", "golden_pit":"黄金坑", "left_rebound":"左侧低吸", "momentum_60":"60 日动量（历史）"][id] ?? id
    }
}

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
    let vol60: Double?; let momentumRatio: Double?
    let leftRsi5:Double?;let leftDrawdown60:Double?;let leftVolume5:Double?
    let leftMa60Slope10:Double?;let leftDistanceLow20:Double?
    let flowNet:Double?;let flowNetRatio:Double?;let flowNet3:Double?;let flowPositiveDays:Int?
    let flowLateReturn:Double?;let flowLateVolume:Double?
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
    var displayMonth:String { String(month.prefix(4))+"-"+String(month.suffix(2)) }
    var sampleLabel:String {
        if total==0 { return "无信号" }
        if count==0 { return (statuses["pending",default:0]+statuses["censored",default:0])>0 ? "待观察结束":"无可结算样本" }
        return "已结算 \(count) 次"
    }
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
    let orderflowStatus:OrderflowStatus?
    var isOrderflow:Bool { strategyId=="orderflow" }
    var orderflowIncomplete:Bool { isOrderflow && orderflowStatus?.status != "complete" }
    var isLeaders:Bool { strategyId=="leaders" }
    var isGoldenPit:Bool { strategyId=="golden_pit" }
    var isMomentum60:Bool { strategyId=="momentum_60" }
    var isLeft:Bool { strategyId=="left_rebound" }
    var conditionLabel:Bool { isMomentum60 || isLeft || isOrderflow }
}

enum LeftReboundGuide {
    static let summary="用最新完整日线寻找超跌、缩量且抛压开始收敛的股票。允许小阴线和价格仍在 MA10 下方，作为左侧观察候选；目前尚未证明获利优势。"
    static let rules=[
        "沪深非 ST / 退市股票，至少 80 根日线、最近 60 个市场日连续；价格不低于 3 元，20 日平均成交额不低于 1 亿元，ATR / 价格不超过 6%，当日复权因子与涨跌停价完整。",
        "低位区域：相对近 60 日最高价回撤 10%–25%，低于 MA20 2%–12%，距离近 20 日最低价不超过 8%。",
        "短期超跌：最近 5 日连续价格收益为 -12% 至 -3%，5 日 RSI 不超过 35。RSI 采用 Wilder 指数平滑。",
        "中期约束：MA60 相比 10 日前的跌幅不超过 3%，排除均线快速恶化。",
        "抛压收敛：当日成交量不超过前 5 个完整交易日均量的 90%；当日涨跌幅 -4% 至 +2%，收于日内振幅的上部 60%，且没有封在跌停价。无需当日上涨或收复 MA10。",
        "市场基础池处于 MA20 上方的比例至少为 20%；不足时暂停新候选。最多精选 10 只，每个行业最多 2 只。",
        "分数：超卖程度 25、低位位置 25、缩量 20、收盘承接 15、流动性 15。精选按分数与代码排序，分数不代表获利概率。",
        "低位参考是近 20 日低价。失效参考取该低价下方 2% 与收盘价减 2 ATR 的较高者；参考价不保证成交，历史事件检验未模拟盘中止损。",
        "固定规则用于 1–5 个交易日观察，尚未通过独立样本外及模拟实盘验证。左侧条件出现后仍可能继续下跌，历史统计与昨日精选的实际次日表现分别展示。"
    ]
}

enum Momentum60Guide {
    static let summary = "在成交活跃的沪深主板中，寻找价格站上 MA60、近 60 日上涨且涨幅相对波动较高的股票。按 60 日收益 / 60 日波动排序，精选最多 5 只。"
    static let evidence = "2026 年 1–4 月选择期：合并平仓胜率 48.69%，三个独立 10 万元账户平均收益 +1.99%。这是本轮八个新候选中的最高选择期胜率；开发期平均收益 -6.34%，尚未通过完整验证。"
    static let rules = [
        "基础池：沪深主板，当前非 ST / 退市名称；至少 80 根日线、最近 60 个市场日连续；价格 ≥3 元、20 日均成交额 ≥1 亿元、ATR / 价格 ≤6%。信号日必须有复权因子和有效涨跌停价。",
        "流动性：在主板基础池内，取 20 日均成交额前 40%。相同成交额按股票代码排序。",
        "趋势与涨幅：收盘价高于 MA60，近 60 个交易日连续价格收益为正，当日涨幅不超过 5%。本规则没有增加 MA20、行业限额或市场宽度择时条件。满足其他条件但当日涨幅超过 5% 时列入“等待”，符合全部条件的列入“符合”。",
        "排序：60 日收益除以近 60 日每日收益的样本标准差，取前 5；同值按代码排序。首页展示的 0–100 排序分是候选内相对排名，不是胜率，精选按未取整的原始比值确定。",
        "观察计划：D 日收盘形成信号，次日开盘才可进入；高开超过 3%、涨停、停牌或交易数据不足时保留现金，不用后排股票补位。默认研究持有 3 日，MA60 是趋势参考；图示失效价并未加入盘中止损回测。",
        "封存研究按 10 万元、5 个仓位、100 股整手、最低佣金和税费及双边各 10 bp 滑点计算；3 个起始日期各使用独立账户。开发期为 2025 年 5–12 月，合并平仓胜率 44.27%、账户平均收益 -6.34%；选择期为 2026 年 1–4 月，三个账户合计 306 笔平仓、胜率 48.69%、账户平均收益 +1.99%。",
        "这项策略尚未完成独立留出和模拟实盘盈利验证。App 的动态历史页面另按当前名称过滤、逐事件统计，存在回溯偏差与信号重叠，不能与上述资金账本结果混用；历史胜率不代表未来概率。"
    ]
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

struct OrderflowStatus:Decodable {
    let status:String;let date:String;let requested:Int;let verified:Int;let replayVerified:Int;let message:String
}
enum OrderflowGuide {
    static let summary="结合有交易日期的大单资金流和盘口复盘，观察资金持续流入、价格不过热且尾盘承接稳定的股票。用于1–5日研究观察，尚未验证盈利优势。"
    static let rules=[
        "盘后：沪深非ST股票，至少80根日线且最近60日连续；股价≥3元、20日均成交额≥1亿元、ATR≤6%，复权因子和涨跌停价齐备。基础池站上MA20比例至少40%。",
        "日线初筛：上涨0.3%–5%，位于MA20上方0%–8%，5日涨幅≤12%，收在日内振幅上部35%，成交额为20日均额1–3倍，不封涨跌停。按20日均额取前200只核验资金流。",
        "大单确认：供应商定义的大单加超大单净流入≥2000万元，占当日成交额≥3%；含当日的三个交易日中至少两日净流入且合计为正。资金流是规模分类估算，不代表机构身份。",
        "盘口确认：D3复盘须与日线收盘价、累计量相符；不可用时用达塔完整240分钟行情复核日线量额；收盘不低于14:30价格，最后半小时成交量占全天至少8%。不使用未成交挂单或单位未核验的盘口金额。",
        "评分：净流入强度35、连续性15、收盘位置20、尾盘量占比15、波动风险15；最多10只，每行业最多2只。数据缺失或过期则不生成本策略精选，其他策略独立运行。",
        "14:30盘中版：使用已完成历史日线和执行时刻的新鲜行情，先从历史基础池按20日均额取前100只，再用实时行情筛选；价格高于日内均价和MA20，涨幅0.3%–5%，累计量为前5日均量1–3倍，再核验同样的资金流条件。按净流入占比列前10只，不使用收盘条件。",
        "大额成交接口暂缺可靠交易日期，首版不计入信号。历史大单样本未齐，不以日线代理生成胜率；从真实发布的精选记录观察次日表现。次日高开超过3%或涨停不追，支持与失效价格仅作研究参考。"
    ]
}
