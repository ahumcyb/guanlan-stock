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
        row["scope"]="after_close";row["price_date"]="20260921";row["strategies"]=["leaders","pullback"]
        let daily=try decodeRow();assert(daily.label=="可列入次日计划")
        let hash=String(repeating:"a",count:64)
        let manifest=MobileManifest(schemaVersion:1,generation:"20260921T170000-abcdef",strategy:"leaders",asOf:"20260921",reportBytes:10,reportSha256:hash,stockCount:1,dataRevision:"20260921-aaaaaaaaaaaaaaaa")
        var object:[String:Any]=["scope":"after_close","generation":manifest.generation,"slot":manifest.generation,"date":manifest.asOf,"data_revision":manifest.dataRevision,"source_report_shas":["leaders":hash],"status":"ready","input_sha256":hash,"rows":[row],"message":"done"]
        func decodeReview() throws -> JevReview { try decoder.decode(JevReview.self,from:JSONSerialization.data(withJSONObject:object)) }
        let bound=try decodeReview();assert(bound.bound(to:manifest))
        object["source_report_shas"]=["leaders":String(repeating:"b",count:64)];let mismatchHash=try decodeReview();assert(!mismatchHash.bound(to:manifest))
        object["source_report_shas"]=["leaders":hash];object["generation"]="20260921T180000-abcdef";let mismatchGeneration=try decodeReview();assert(!mismatchGeneration.bound(to:manifest))
        row["expires_at"]=now-1;let expired=try decodeRow();assert(expired.isExpired && expired.label=="当时判断：可列入次日计划")
        row["expires_at"]=now+175;row["expired"]=true;let serverExpired=try decodeRow();assert(serverExpired.isExpired)
        row["expired"]=false;row["historical"]=true;let historical=try decodeRow();assert(historical.label=="回看判断：可列入次日计划")
        row["scope"]="realtime";row["decision"]="watch";let replay=try decodeRow();assert(replay.label=="回看判断：观望");assert(replay.expiryNotice=="行情已过期，入场前需更新。过期不代表股票已不符合策略。")
        let settings:[String:Any]=["enabled":true,"notification_enabled":true,"ai_enabled":false,
            "model":"deepseek-v4-flash","bark_configured":true,"deepseek_configured":true]
        let old=try decoder.decode(RealtimeSettings.self,from:JSONSerialization.data(withJSONObject:settings))
        assert(old.jevEnabled==nil && old.jevConfigured==nil)
        print("JEV native labels, source expiry, server expiry and legacy settings passed")
    }
}
