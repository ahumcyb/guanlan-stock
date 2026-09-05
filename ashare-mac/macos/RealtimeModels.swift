import Foundation

struct RealtimeSettings: Codable {
    let enabled: Bool
    let notificationEnabled: Bool
    let aiEnabled: Bool
    let model: String
    let barkConfigured: Bool
    let deepseekConfigured: Bool
}

struct RealtimeState: Codable {
    let schemaVersion: Int
    let settings: RealtimeSettings
    let macOnline: Bool
    let serverOnline: Bool
    let running: Bool
    let executor: String
    let schedule: [String]
    let events: [RealtimeEvent]
    let latest: RealtimeSnapshot?
    let lastScreen: RealtimeSnapshot?
}

struct RealtimeSnapshot: Codable {
    let date: String
    let previousDate: String
    let generatedAt: Double
    let kind: String
    let status: String
    let message: String
    let executor: String
    let slot: String
    let strategies: [String: [RealtimeCandidate]]
    let reviews: [RealtimeReview]
    let warnings: [String]
    let universeCount: Int?
    let quoteCount: Int?
    let freshCount: Int?
    let indexChange: Double?
    let ai: RealtimeAI?
}

struct RealtimeCandidate: Codable, Identifiable {
    var id: String { strategy + "-" + tsCode }
    let strategy: String
    let tsCode: String
    let name: String
    let price: Double
    let change: Double
    let quoteAt: Double
    let timeBasis: String
    let volumeMultiple: Double
    let volumeRatio: Double
    let vwap: Double
    let referenceDate: String
    let checks: [String]
    let pending: [String]
    let state: String
    let turnover: Double?
    let marketCap: Double?
}

struct RealtimeReview: Codable, Identifiable {
    var id: String { tsCode }
    let tsCode: String
    let name: String
    let price: Double
    let referencePrice: Double
    let change: Double
    let quoteAt: Double
    let note: String
}

struct RealtimeAI: Codable {
    let status: String
    let summary: String
    let risks: [String]
    let model: String?
}

struct RealtimeEvent: Codable, Identifiable {
    let id: String
    let createdAt: Double
    let title: String
    let body: String
    let kind: String
    let status: String
    var deliveryLabel: String {
        switch status {
        case "accepted": return "Bark 已接受"
        case "pending", "sending": return "等待发送"
        case "retry": return "发送失败，等待重试"
        case "unknown": return "发送结果待确认"
        case "expired": return "已过时，未推送"
        case "unconfigured": return "仅 App 内记录"
        default: return "发送失败"
        }
    }
}

func realtimeDate(_ timestamp: Double) -> String {
    let formatter = DateFormatter();formatter.locale = Locale(identifier: "zh_CN")
    formatter.timeZone = TimeZone(identifier: "Asia/Shanghai");formatter.dateFormat = "MM-dd HH:mm:ss"
    return formatter.string(from: Date(timeIntervalSince1970: timestamp))
}

func realtimeStrategy(_ id: String) -> String {
    id == "overnight" ? "一夜持股 · 正文版" : "黄金半小时 · 七步法"
}

struct RealtimeStrategyGuide: Identifiable {
    let id: String
    let summary: String
    let conditions: [String]
    let review: [String]
    let interpretation: String
    let sourceName: String
    let sourceURL: String
    var title: String { realtimeStrategy(id) }
    static let schedule = "北京时间每个交易日14:30初筛、14:45复核、14:50再次检查。Mac优先计算，Mac连不上时服务器接管；筛选完成后手机收到查看提醒。"
    static let scope = "沪深A股，排除ST与退市标记，至少60根历史日线。历史数据截至前一交易日；当日行情超过3分钟、存在异常或覆盖不足时，暂停本轮或剔除异常股票。"
    static let all: [RealtimeStrategyGuide] = [
        .init(id: "overnight", summary: "寻找尾盘放量上涨、趋势或突破形态成立的股票，作为隔夜观察候选。",
              conditions: [
                "当日涨幅在3%–5%之间。",
                "截至筛选时的累计成交量，至少为前5个完整交易日平均日成交量的1.5倍。",
                "满足两种形态之一：最新价在MA5之上，MA5>MA10>MA20且MA5向上；或者突破近期小平台。",
                "小平台定义：前10日收盘价最高/最低之比不超过1.08，最新价突破前10日最高价。",
                "沪深300当日涨跌幅不低于−0.3%。这是对原文“收红或震荡”的明确数值解释。"
              ], review: ["公告、减持、解禁与隔夜事件仍需核查。", "跳空或跌停可能使参考止损无法成交。"],
              interpretation: "“正文规则通过”表示量价条件匹配，不代表确定买点。原文配图与正文参数有差异，观澜采用正文的3%–5%涨幅和1.5倍量能；未验证原文宣传的胜率。",
              sourceName: "每日云澈 · 一夜持股法", sourceURL: "https://www.xiaohongshu.com/explore/6a817d4c000000000502a0a4"),
        .init(id: "golden", summary: "从尾盘温和上涨的股票中，进一步检查活跃度、换手、市值、均线和分时形态。",
              conditions: [
                "14:30之后检查，当日涨幅在3%–5%之间。",
                "量比不低于1：按前5日均量与当天已经过的交易分钟换算，午休不计入。",
                "换手率在5%–10%之间；流通市值在50–200亿元之间。两项均按前一交易日流通股本估算。",
                "最新价>MA5>MA10>MA20，且MA5相对前一交易日向上。",
                "分时复核：14:40–14:48附近创此前日内新高，之后回踩0.05%–1%，期间不跌破当日成交均价。"
              ], review: ["缺少完整分钟数据时，分时条件显示“待核验”，不会当作通过。", "“全天分时强于大盘”仍需人工核查，不用一个时点的涨幅替代。", "公告风险和流通股本变化仍需复核。"],
              interpretation: "“待分时核验”表示已满足基础量价条件，但七步法还没有全部确认。即使分时回踩通过，也仍须复核大盘分时和公告；规则匹配不等于盈利保证。",
              sourceName: "量化策略星 · 尾盘选股法", sourceURL: "https://www.xiaohongshu.com/explore/6a59eeac000000001102edb4")
    ]
}
