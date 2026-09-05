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
