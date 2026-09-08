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
    let lastBottom:RealtimeSnapshot?
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
    let runState:String?
    let failureStage:String?
    let changes:[String:RealtimeSelectionChange]?
    let bottomVolume:BottomVolumeResult?
    var complete:Bool { ["ready","empty"].contains(status) && runState != "waiting" }
    var executionLabel:String {
        if status=="blocked",bottomVolume?.complete==true { return "原两套策略未完成；底部放量已完成" }
        if ["ready","empty"].contains(status),let bottom=bottomVolume,!bottom.complete { return "原两套策略完成；底部放量未完成" }
        if kind=="prepare" && status=="ready" { return "历史数据已准备，等待策略时段" }
        if runState=="waiting" { return "等待策略时段" }
        if status=="blocked" {
            if failureStage=="publication" { return "结果提交失败" }
            if ["quotes","index","history","credentials"].contains(failureStage ?? "") { return "行情或历史数据不足，未完成筛选" }
            if failureStage=="validation" { return "结果未通过校验" }
            return "本轮未完成，请查看具体说明"
        }
        return ["ready":"筛选完成","empty":"筛选完成 · 0只候选","closed":"休市"][status] ?? "状态待核验"
    }
}

struct BottomVolumeResult:Codable {
    let status:String;let lookback:Int;let matchedCount:Int;let candidates:[RealtimeCandidate]
    let checkedAt:Double;let oldestQuoteAt:Double;let message:String
    var complete:Bool { ["ready","empty"].contains(status) }
}

struct RealtimeSelectionChange:Codable {
    struct Item:Codable,Identifiable { let tsCode:String;let name:String;var id:String{tsCode} }
    let previousSlot:String;let added:[Item];let removed:[Item];let retainedCount:Int
}

struct RealtimeRunSummary:Codable,Identifiable {
    let slot:String;let date:String;let generatedAt:Double;let kind:String;let status:String;let message:String;let executor:String
    let runState:String?;let strategyCounts:[String:Int]
    var id:String{slot}
    var label:String { dateText(date)+" · "+realtimeSlot(slot) }
}
struct RealtimeHistory:Codable { let schemaVersion:Int;let runs:[RealtimeRunSummary] }
struct RealtimeEventDetail:Codable { let event:RealtimeEvent;let report:RealtimeSnapshot?;let message:String }

enum NotificationTarget:Equatable { case realtime,event(String),daily(String?) }
func notificationTarget(_ url:URL)->NotificationTarget? {
    guard url.scheme=="guanlan",url.user==nil,url.password==nil,url.port==nil,url.fragment==nil else { return nil }
    if url.host=="alerts",url.query==nil {
        if url.path.isEmpty || url.path=="/" { return .realtime }
        let parts=url.path.split(separator:"/")
        guard parts.count==1,let id=UUID(uuidString:String(parts[0])) else { return nil }
        return .event(id.uuidString.lowercased())
    }
    if url.host=="daily",url.path.isEmpty || url.path=="/" {
        let items=URLComponents(url:url,resolvingAgainstBaseURL:false)?.queryItems ?? []
        if items.isEmpty { return .daily(nil) }
        guard items.count==1,items[0].name=="date",let date=items[0].value,validDailyDate(date) else { return nil }
        return .daily(date)
    }
    return nil
}

func validRealtimeSlot(_ value:String)->Bool {
    if value.hasPrefix("manual-") { return UUID(uuidString:String(value.dropFirst(7))) != nil }
    return value.range(of:"^[0-9]{8}-(0910|1430|1445|1450)$",options:.regularExpression) != nil && validDailyDate(String(value.prefix(8)))
}

extension RealtimeSnapshot {
    func validateArchive(_ expectedSlot:String?=nil) throws {
        guard validRealtimeSlot(slot),expectedSlot==nil || expectedSlot==slot,validDailyDate(date),validDailyDate(previousDate),
              previousDate<date,generatedAt.isFinite,generatedAt>0,["screen","prepare","review"].contains(kind),
              ["ready","empty","blocked","closed"].contains(status),["mac","server"].contains(executor),
              Set(strategies.keys)==Set(["overnight","golden"]),message.count<=500,reviews.count<=20 else { throw CocoaError(.fileReadCorruptFile) }
        for (strategy,rows) in strategies {
            guard rows.count<=10,Set(rows.map(\.tsCode)).count==rows.count,complete || rows.isEmpty,
                  rows.allSatisfy({$0.strategy==strategy && $0.price.isFinite && $0.price>0 && $0.quoteAt.isFinite && $0.quoteAt<=generatedAt+15}) else { throw CocoaError(.fileReadCorruptFile) }
        }
        if let bottom=bottomVolume {
            guard slot==date+"-1430",bottom.lookback==60,["ready","empty","blocked"].contains(bottom.status),
                  (0...6500).contains(bottom.matchedCount),bottom.candidates.count<=10,bottom.matchedCount>=bottom.candidates.count,
                  bottom.checkedAt.isFinite,bottom.oldestQuoteAt.isFinite,
                  bottom.complete || bottom.candidates.isEmpty else { throw CocoaError(.fileReadCorruptFile) }
            for row in bottom.candidates {
                guard row.strategy=="bottom_volume",row.price>0,row.price.isFinite,row.volumeMultiple>=3,
                      row.low60.map({$0>0 && $0.isFinite})==true,row.distanceLow60.map({(-0.000001...0.100001).contains($0)})==true,
                      row.referenceDate==previousDate,row.quoteAt.isFinite,row.quoteAt<=generatedAt+15 else { throw CocoaError(.fileReadCorruptFile) }
            }
        }
    }
}

func realtimeSlot(_ slot:String)->String {
    if slot.hasPrefix("manual-") { return "手动检查" }
    return ["0910":"09:10 准备","1430":"14:30 初筛","1445":"14:45 复核","1450":"14:50 最终"] [String(slot.suffix(4))] ?? "历史轮次"
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
    let low60:Double?
    let distanceLow60:Double?
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
    let runId:String?
    let url:String?
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
    ["overnight":"一夜持股 · 正文版","golden":"黄金半小时 · 七步法","bottom_volume":"底部放量 · 3倍观察"][id] ?? id
}

struct RealtimeStrategyGuide: Identifiable {
    let id: String
    let summary: String
    let conditions: [String]
    let review: [String]
    let interpretation: String
    let sourceName: String
    let sourceURL: String?
    var title: String { realtimeStrategy(id) }
    static let schedule = "北京时间交易日14:30执行三套策略；底部放量仅在14:30检查，原两套策略在14:45、14:50继续复核。Mac优先，失联时服务器接管；筛选完成后手机收到提醒。"
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
              sourceName: "量化策略星 · 尾盘选股法", sourceURL: "https://www.xiaohongshu.com/explore/6a59eeac000000001102edb4"),
        .init(id:"bottom_volume",summary:"交易日14:30，寻找近60日低位、累计成交量达到前5日日均量3倍以上的股票。",
              conditions:["只在交易日14:30这一轮执行；14:45和14:50不重算、不覆盖这份结果。",
                          "最新价位于前60个完整交易日最低价上方0%–10%，不低于该历史低点。历史低价按前一交易日复权口径锚定。",
                          "截至筛选时累计成交量 ÷ 前5个完整交易日的全天平均成交量 ≥3，成交量统一按股计算。",
                          "不套用另外两策略的3%–5%涨幅限制，也不依赖指数或分时形态条件。",
                          "沪深非ST/退市标记股票，至少60根历史日线；前收与历史价格不连续、报价过时或缺数时排除。",
                          "显示全部命中数量，按放量倍数从高到低展示前10只；通知正文包含名称、代码和倍数。"],
              review:["低位不等于底部确认，放量也可能伴随抛压。","公告、减持、解禁和成交可得性仍需核查。"],
              interpretation:"这是用户定义的低位放量观察条件，没有验证其盈利优势，不代表买点或底部已经形成。",
              sourceName:"用户自定义规则 · 2026-09-08",sourceURL:nil)
    ]
}
