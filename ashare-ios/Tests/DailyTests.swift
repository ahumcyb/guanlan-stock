import Foundation

@main struct DailyTests {
    static func main() throws {
        let source=URL(fileURLWithPath:CommandLine.arguments[1]);let data=try Data(contentsOf:source)
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let cache=DailyCache(root:root);let state=try cache.saveState(data)
        assert(state.latest != nil && AfterCloseStrategies.validGroup(state.latest!.evidence.strategies.map(\.id)))
        let reloaded=try cache.loadState();assert(reloaded.latest?.date==state.latest?.date)
        let report=try cache.loadReport(state.latest!.date);assert(report.evidence.market.stockCount>0)
        if let realtime=report.evidence.realtimePerformance {
            try realtime.validate(date:report.date)
            assert(realtime.strategies.count==3)
        }
        assert(validDailyDate(report.date) && !validDailyDate("20260230") && !validDailyDate("../../x"))
        var raw=try JSONSerialization.jsonObject(with:data) as! [String:Any]
        var latest=raw["latest"] as! [String:Any];var evidence=latest["evidence"] as! [String:Any]
        var market=evidence["market"] as! [String:Any];market["stock_count"]=0
        evidence["market"]=market;latest["evidence"]=evidence;raw["latest"]=latest
        do { _=try cache.saveState(JSONSerialization.data(withJSONObject:raw));assertionFailure("Invalid market facts were cached") } catch {}
        let preserved=try cache.loadState();assert(preserved.latest?.evidence.market.stockCount==report.evidence.market.stockCount)
        let original=try JSONSerialization.jsonObject(with:data) as! [String:Any]
        var compatible=original;var oldLatest=compatible["latest"] as! [String:Any]
        var oldEvidence=oldLatest["evidence"] as! [String:Any];oldEvidence.removeValue(forKey:"realtime_performance")
        oldLatest["evidence"]=oldEvidence;compatible["latest"]=oldLatest
        let legacy=try dailyDecoder().decode(DailyState.self,from:JSONSerialization.data(withJSONObject:compatible))
        try legacy.validate();assert(legacy.latest!.evidence.realtimePerformance==nil)
        if let latest=original["latest"] as? [String:Any],let evidence=latest["evidence"] as? [String:Any],
           let realtime=evidence["realtime_performance"] as? [String:Any],realtime["status"] as? String=="available" {
            for field in ["mean_return_pct","mean_signal_return_pct","up_count","source_slot"] {
                var invalid=original;var latest=latest;var evidence=evidence;var realtime=realtime
                var groups=realtime["strategies"] as! [[String:Any]]
                if field=="source_slot" { groups[0][field]="20990101-1450" } else { groups[0][field]=999 }
                realtime["strategies"]=groups;evidence["realtime_performance"]=realtime;latest["evidence"]=evidence;invalid["latest"]=latest
                do { _=try cache.saveState(JSONSerialization.data(withJSONObject:invalid));assertionFailure("Invalid realtime settlement cached") } catch {}
            }
        }
        print("Native daily model, versioned strategy facts, offline cache and invalid-data rejection passed · \(report.date)")
    }
}
