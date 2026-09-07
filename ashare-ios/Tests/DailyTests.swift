import Foundation

@main struct DailyTests {
    static func main() throws {
        let source=URL(fileURLWithPath:CommandLine.arguments[1]);let data=try Data(contentsOf:source)
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:root) }
        let cache=DailyCache(root:root);let state=try cache.saveState(data)
        assert(state.latest != nil && state.latest!.evidence.strategies.count==4)
        let reloaded=try cache.loadState();assert(reloaded.latest?.date==state.latest?.date)
        let report=try cache.loadReport(state.latest!.date);assert(report.evidence.market.stockCount>0)
        assert(validDailyDate(report.date) && !validDailyDate("20260230") && !validDailyDate("../../x"))
        var raw=try JSONSerialization.jsonObject(with:data) as! [String:Any]
        var latest=raw["latest"] as! [String:Any];var evidence=latest["evidence"] as! [String:Any]
        var market=evidence["market"] as! [String:Any];market["stock_count"]=0
        evidence["market"]=market;latest["evidence"]=evidence;raw["latest"]=latest
        do { _=try cache.saveState(JSONSerialization.data(withJSONObject:raw));assertionFailure("Invalid market facts were cached") } catch {}
        let preserved=try cache.loadState();assert(preserved.latest?.evidence.market.stockCount==report.evidence.market.stockCount)
        print("Native daily model, four-strategy facts, offline cache and invalid-data rejection passed · \(report.date)")
    }
}
