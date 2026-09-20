import Foundation

@main struct CoreTests {
    static func main() async throws {
        let fixture=URL(fileURLWithPath:CommandLine.arguments[1]).resolvingSymlinksInPath()
        let manifest=try mobileDecoder().decode(MobileManifest.self,from:Data(contentsOf:fixture.appendingPathComponent("leaders/manifest.json")))
        let data=try Data(contentsOf:fixture.appendingPathComponent("leaders/report.json"))
        let report=try manifest.decodeReport(data)
        assert(report.stocks.count==manifest.stockCount && report.asOf==manifest.asOf)
        let temporary=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:temporary) }
        let cache=OfflineCache(root:temporary)
        try cache.save(data,manifest:manifest)
        do { try cache.save(data+Data([32]),manifest:manifest);assertionFailure("Corrupt data was accepted") } catch {}
        let cached=try cache.load("leaders");assert(cached?.manifest==manifest)
        var cachedStrategies=["leaders"]
        assert(AfterCloseStrategies.activeChoice("momentum_60")=="left_rebound")
        assert(AfterCloseStrategies.validGroup(AfterCloseStrategies.ids))
        assert(AfterCloseStrategies.validGroup(AfterCloseStrategies.previousIds))
        assert(!AfterCloseStrategies.validGroup(AfterCloseStrategies.ids+["orderflow"]))
        for strategy in ["pullback","golden_pit","left_rebound","momentum_60"] {
            let folder=fixture.appendingPathComponent(strategy)
            // Old published fixtures remain valid during a staged app/server update.
            guard FileManager.default.fileExists(atPath:folder.appendingPathComponent("manifest.json").path) else { continue }
            let other=try mobileDecoder().decode(MobileManifest.self,from:Data(contentsOf:folder.appendingPathComponent("manifest.json")))
            let snapshot=try cache.save(Data(contentsOf:folder.appendingPathComponent("report.json")),manifest:other)
            cachedStrategies.append(strategy)
            assert(snapshot.report.strategyId==strategy)
            if strategy=="left_rebound" {
                assert(snapshot.report.isLeft && snapshot.report.shortlistCount<=10)
                for stock in snapshot.report.stocks where stock.state=="入选" {
                    assert((0...35).contains(stock.leftRsi5!))
                    assert((0.10...0.25).contains(stock.leftDrawdown60!))
                    assert(stock.leftVolume5!<=0.9)
                }
            }
            if strategy=="momentum_60" {
                assert(snapshot.report.isMomentum60 && snapshot.report.shortlistCount<=5)
                for stock in snapshot.report.stocks where stock.state=="入选" {
                    assert(stock.ret60!>0 && stock.vol60!>0 && stock.momentumRatio!>0)
                    assert((0...100).contains(stock.score))
                }
            }
            if strategy=="golden_pit" {
                assert(snapshot.report.isGoldenPit)
                for stock in snapshot.report.stocks where stock.state=="入选" {
                    assert(stock.pitPeakDate!<stock.pitTroughDate! && stock.pitTroughDate!<stock.tradeDate)
                    assert((0.08...0.20).contains(stock.pitDepth!))
                }
            }
        }
        for strategy in cachedStrategies {
            let saved=try cache.load(strategy);assert(saved?.report.strategyId==strategy)
        }
        if cachedStrategies.contains("left_rebound") {
            var manifests:[String:MobileManifest]=[:];var reports:[String:Data]=[:]
            for strategy in AfterCloseStrategies.ids where FileManager.default.fileExists(atPath:fixture.appendingPathComponent(strategy+"/manifest.json").path) {
                let folder=fixture.appendingPathComponent(strategy)
                manifests[strategy]=try mobileDecoder().decode(MobileManifest.self,from:Data(contentsOf:folder.appendingPathComponent("manifest.json")))
                reports[strategy]=try Data(contentsOf:folder.appendingPathComponent("report.json"))
            }
            try cache.saveBundle(reports,manifests:manifests)
            reports["left_rebound"]!.append(32)
            do { try cache.saveBundle(reports,manifests:manifests);assertionFailure("Partial invalid bundle replaced complete cache") } catch {}
            for strategy in AfterCloseStrategies.ids where FileManager.default.fileExists(atPath:fixture.appendingPathComponent(strategy+"/manifest.json").path) {
                let saved=try cache.load(strategy);assert(saved?.manifest==manifests[strategy])
            }
            reports["left_rebound"]!.removeLast()
            for index in 1...3 {
                let generation="20260908T12000\(index)-aaaaa\(index)"
                let next=manifests.mapValues { m in MobileManifest(schemaVersion:m.schemaVersion,generation:generation,strategy:m.strategy,asOf:m.asOf,reportBytes:m.reportBytes,reportSha256:m.reportSha256,stockCount:m.stockCount,dataRevision:m.dataRevision) }
                try cache.saveBundle(reports,manifests:next)
            }
            let retained=try FileManager.default.contentsOfDirectory(at:temporary,includingPropertiesForKeys:nil).filter{$0.lastPathComponent.hasSuffix("-report.json")}
            assert(retained.count<=9)
            print("Atomic four-strategy cache and invalid-bundle preservation passed")
        }
        do { _=try cache.chartURL(manifest,code:"../../secret");assertionFailure("Traversal was accepted") } catch {}
        let code=(report.stocks.first(where:{$0.rank==1}) ?? report.stocks[0]).id
        let chart=try Data(contentsOf:fixture.appendingPathComponent("charts/\(code).json"))
        let candles=try cache.saveChart(chart,manifest:manifest,code:code)
        assert(!candles.isEmpty && candles.count<=120)
        let cachedCandles=try cache.loadChart(manifest,code:code);assert(cachedCandles?.count==candles.count)
        do { _=try decodeCandles(Data("[]".utf8),asOf:manifest.asOf);assertionFailure("Empty chart accepted") } catch {}
        assert(csvCell("=SUM(A1:A2)").hasPrefix("\"'="))
        assert(csvCell("-1.25")=="\"-1.25\"")
        print("Native model/cache/CSV checks passed · \(cachedStrategies.joined(separator:",")) · \(report.stocks.count) stocks · \(report.asOf)")
        if CommandLine.arguments.count>2 {
            let pairing=try JSONDecoder().decode(Pairing.self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[2])))
            let invalid=Pairing(endpoint:"https://example.invalid",token:pairing.token,certificate:pairing.certificate)
            do { _=try invalid.validated();assertionFailure("Unexpected host accepted") } catch {}
            let api=try MobileAPI(pairing)
            let status=try await api.request("/v1/status",limit:65536)
            let state=try mobileDecoder().decode(ServerStatus.self,from:status);assert(state.schemaVersion==1)
            let value=try await api.request("/v1/reports/leaders/current",limit:65536)
            let remote=try mobileDecoder().decode(MobileManifest.self,from:value)
            let bytes=try await api.request("/v1/reports/leaders/\(remote.generation)/report.json",limit:remote.reportBytes)
            let verified=try remote.decodeReport(bytes)
            print("Native HTTPS / dedicated certificate / report SHA-256 passed · \(verified.stocks.count) stocks")
        }
    }
}
