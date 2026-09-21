import Foundation
@main struct JevTests {
    static func main() throws {
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let now=Date().timeIntervalSince1970
        var row:[String:Any]=["ts_code":"000001.SZ","name":"测试","price":10.0,"quote_at":now-5,
            "decision":"buy","model_choice":"buy","confidence":0.9,"probabilities":["buy":0.9,"watch":0.1,"avoid":0.0],
            "reason":"trend_volume","explanation":"依据分类","historical":false,"expires_at":now+175,
            "conditions":["核查公告"],"invalidation":"原信号失效则重新评估"]
        func decodeRow() throws -> JevStockReview { try decoder.decode(JevStockReview.self,from:JSONSerialization.data(withJSONObject:row)) }
        let fresh=try decodeRow();assert(!fresh.isExpired && fresh.label=="可考虑买入")
        row["expires_at"]=now-1;let expired=try decodeRow();assert(expired.isExpired)
        row["expires_at"]=now+175;row["expired"]=true;let serverExpired=try decodeRow();assert(serverExpired.isExpired)
        row["expired"]=false;row["historical"]=true;let historical=try decodeRow();assert(historical.label=="已过期 · 回看")
        let settings:[String:Any]=["enabled":true,"notification_enabled":true,"ai_enabled":false,
            "model":"deepseek-v4-flash","bark_configured":true,"deepseek_configured":true]
        let old=try decoder.decode(RealtimeSettings.self,from:JSONSerialization.data(withJSONObject:settings))
        assert(old.jevEnabled==nil && old.jevConfigured==nil)
        print("JEV native labels, source expiry, server expiry and legacy settings passed")
    }
}
