import Foundation

@main struct ChartLoadTests {
    @MainActor static func main() async throws {
        let loader=ChartLoadState()
        let a=ChartDataset(tsCode:"600000.SH",asOf:"20260910",dataRevision:nil,bars:[])
        let b=ChartDataset(tsCode:"600001.SH",asOf:"20260911",dataRevision:nil,bars:[])
        var pending:CheckedContinuation<ChartDataset,Error>?
        let first=Task { await loader.load(key:"old") { try await withCheckedThrowingContinuation { pending=$0 } } }
        while pending==nil { await Task.yield() }
        await loader.load(key:"new") { b }
        pending!.resume(throwing:ChartDataError.invalid);await first.value
        assert(loader.data?.tsCode==b.tsCode && loader.error==nil && !loader.loading)
        pending=nil
        let stale=Task { await loader.load(key:"same") { try await withCheckedThrowingContinuation { pending=$0 } } }
        while pending==nil { await Task.yield() }
        assert(loader.data==nil && loader.loading)
        await loader.load(key:"same") { b }
        pending!.resume(returning:a);await stale.value
        assert(loader.data?.tsCode==b.tsCode)
        await loader.load(key:"failed") { throw ChartDataError.invalid }
        assert(loader.data==nil && loader.error != nil && !loader.loading)
        loader.reset();assert(loader.data==nil && loader.error==nil && !loader.loading)
        pending=nil
        let cancelled=Task { await loader.load(key:"cancelled") { try await withCheckedThrowingContinuation { pending=$0 } } }
        while pending==nil { await Task.yield() }
        cancelled.cancel();pending!.resume(returning:a);await cancelled.value
        assert(loader.data==nil && !loader.loading && loader.error==nil)
        print("Chart load identity fences stale success/errors, clears old data and preserves retry states")
    }
}
