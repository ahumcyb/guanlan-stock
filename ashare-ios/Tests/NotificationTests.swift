import Foundation

@main struct NotificationTests {
    static func main() throws {
        let id="a8ea4ae9-b0e9-4fab-a986-5f4eee728dbd"
        assert(notificationTarget(URL(string:"guanlan://alerts/"+id)!) == .event(id))
        assert(notificationTarget(URL(string:"guanlan://daily?date=20260907")!) == .daily("20260907"))
        assert(notificationTarget(URL(string:"guanlan://daily")!) == .daily(nil))
        for value in ["guanlan://alerts/not-an-id","guanlan://alerts/../../file","guanlan://daily?date=20260230",
                      "guanlan://daily?date=20260907&date=20260904","https://example.test/alerts/"+id] {
            assert(notificationTarget(URL(string:value)!)==nil)
        }
        print("Notification event/date routing and invalid-link rejection passed")
        func bottomArchive(version:Int?,volume:Double,change:Double,batch:Bool=false) throws -> RealtimeSnapshot {
            let row:[String:Any] = ["strategy":"bottom_volume","ts_code":"600000.SH","name":"测试股票","price":10.5,
                "change":change,"quote_at":1788849000.0,"reference_date":"20260907","volume_multiple":volume,"time_basis":"trade_time",
                "volume_ratio":volume,"vwap":10.4,"state":"低位放量观察","checks":[],"pending":[],"low60":10.0,"distance_low60":0.05]
            var bottom:[String:Any] = ["status":"ready","lookback":60,"matched_count":1,"candidates":[row],
                "checked_at":1788849000.0,"oldest_quote_at":1788849000.0,"message":"归档测试"]
            if let version { bottom["rule_version"]=version }
            var snapshot:[String:Any] = ["date":"20260908","previous_date":"20260907","generated_at":1788849000.0,
                "kind":"screen","status":"ready","message":"完成","executor":"mac","slot":"20260908-1430",
                "strategies":["overnight":[],"golden":[]],"reviews":[],"warnings":[],"bottom_volume":bottom]
            snapshot["universe_count"]=5000;snapshot["fresh_count"]=40
            if batch { snapshot["batch_quote_count"]=4999;snapshot["batch_received_at"]=1788849000.0 }
            let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(RealtimeSnapshot.self,from:JSONSerialization.data(withJSONObject:snapshot))
        }
        try bottomArchive(version:2,volume:2.5,change:0.001).validateArchive()
        let batch=try bottomArchive(version:2,volume:2.5,change:1.0,batch:true)
        assert(batch.quoteCoverageLabel=="批量覆盖 4999 / 5000 · D6复核 40只")
        let legacy=try bottomArchive(version:1,volume:3,change:1.0)
        assert(legacy.quoteCoverageLabel=="新鲜行情 40 / 5000")
        for (volume,change) in [(2.499,1.0),(2.5,0.0),(2.5,-1.0)] {
            let report=try bottomArchive(version:2,volume:volume,change:change)
            do { try report.validateArchive();assertionFailure("Invalid current bottom-volume result accepted") } catch {}
        }
        // Historic records retain their original rule and remain readable.
        try bottomArchive(version:nil,volume:3.0,change:-2.0).validateArchive()
        try bottomArchive(version:1,volume:3.0,change:0.0).validateArchive()
        let unsupported=try bottomArchive(version:3,volume:3.0,change:1.0)
        do { try unsupported.validateArchive();assertionFailure("Unknown rule accepted") } catch {}
        print("2.5-times rising-stock rule and original archive compatibility passed")
    }
}
