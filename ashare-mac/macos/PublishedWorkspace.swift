import Foundation

extension AppStore {
    @discardableResult func loadPublishedReport()->Bool {
        do {
            guard let saved=try publishedCache.load(strategy) else { report=nil;publishedSnapshot=nil;chartLoader.reset();return false }
            publishedSnapshot=saved;report=saved.report
            if dailyJev?.bound(to:saved.manifest) != true { dailyJev=cachedDailyJev(publishedCache.root,saved.manifest) }
            if !saved.report.stocks.contains(where:{$0.id==selection}) { selection=saved.report.stocks.first(where:{$0.rank==1})?.id }
            progress="已载入 \(dateText(saved.report.asOf)) · 多策略同一发布版本";loadChart();return true
        } catch { report=nil;publishedSnapshot=nil;selection=nil;chartLoader.reset();progress="已同步缓存暂不可读取，等待重新同步";return false }
    }

    func synchronizePublished() async {
        guard publishedMode,let api=publishedAPI,!busy else { return }
        busy=true;activity="同步结果";error=nil;defer { busy=false }
        do {
            let state=try mobileDecoder().decode(ServerStatus.self,from:await api.request("/v2/status",limit:65536))
            if serverStatus?.job.id != state.job.id || serverStatus?.reports != state.reports { serverStatus=state }
            lastContentRevisions=state.revisions
            progress="正在同步已发布的策略短列表…"
            try await synchronizePublishedBundle(api,cache:publishedCache,manifests:state.reports)
            guard publishedMode else { return }
            if let saved=try await loadVerifiedSnapshot(cache:publishedCache,strategy:strategy) {
                publishedSnapshot=saved;report=saved.report
                if dailyJev?.bound(to:saved.manifest) != true { dailyJev=cachedDailyJev(publishedCache.root,saved.manifest) }
                if !saved.report.stocks.contains(where:{$0.id==selection}) { selection=saved.report.stocks.first(where:{$0.rank==1})?.id }
                progress="已载入 \(dateText(saved.report.asOf)) · 多策略同一发布版本";loadChart()
            }
        } catch { progress=report==nil ? "结果尚未同步，请稍后重试":"同步暂未完成，保留已校验缓存";self.error=error.localizedDescription }
    }

    func submitPublishedJob(_ action:String) async {
        guard let api=publishedAPI,!busy else { return }
        if serverStatus?.job.active==true { progress=serverStatus!.job.message;return }
        busy=true;defer{busy=false}
        do {
            let body=try JSONSerialization.data(withJSONObject:["action":action,"request_id":UUID().uuidString.lowercased()])
            let job=try mobileDecoder().decode(ServerJob.self,from:await api.request("/v1/jobs",method:"POST",body:body,limit:65536))
            progress=job.message
        } catch { self.error=error.localizedDescription }
    }

    func watchPublishedState() async {
        while !Task.isCancelled {
            if let api=publishedAPI {
                do {
                    let next=try mobileDecoder().decode(ServerStatus.self,from:await api.request("/v2/status",limit:65536))
                    serverStatus=next
                    let revisions=next.revisions
                    let reportsChanged=publishedMode && !busy && (next.reports[strategy] != publishedSnapshot?.manifest || revisions?.reports != lastContentRevisions?.reports)
                    if reportsChanged { await synchronizePublished() }
                    if revisions?.daily != lastContentRevisions?.daily,let data=try? await api.request("/v2/daily",limit:128*1024),let value=try? mobileDecoder().decode(DailyState.self,from:data),(try? value.validate()) != nil {
                        if dailyState?.latest?.date != value.latest?.date || dailyState?.status.message != value.status.message { dailyState=value }
                    }
                    if revisions?.realtime != lastContentRevisions?.realtime,let data=try? await api.request("/v1/realtime",limit:2*1024*1024),let value=try? mobileDecoder().decode(RealtimeState.self,from:data) {
                        if realtimeState?.latest?.generatedAt != value.latest?.generatedAt || realtimeState?.running != value.running { realtimeState=value }
                    }
                    lastContentRevisions=revisions ?? lastContentRevisions
                    if serverStatus?.job.active==true { progress=serverStatus!.job.message }
                } catch { if publishedMode && !busy { progress=report==nil ? "服务器暂未连接":"离线缓存 · \(dateText(report!.asOf))" } }
                await refreshDailyJev()
                await syncFavorites()
            }
            do { try await Task.sleep(for:.seconds(serverStatus?.job.active==true ? 3:20)) } catch { return }
        }
    }

    func refreshDailyJev() async {
        guard publishedMode,let api=publishedAPI,let m=publishedSnapshot?.manifest else { return }
        do {
            let value=try await fetchDailyJev(api,root:publishedCache.root,manifest:m)
            guard publishedMode,publishedSnapshot?.manifest==m else { return }
            if let old=dailyJev,old.bound(to:m),(old.requestedAt ?? 0)>(value.requestedAt ?? 0) { return }
            dailyJev=value;dailyJevMessage=""
        } catch { if publishedSnapshot?.manifest==m { dailyJevMessage="JEV暂不可读取，保留已核验缓存。" } }
    }
    func requestDailyJev() async {
        guard !dailyJevBusy,let api=publishedAPI,let m=publishedSnapshot?.manifest else { return }
        dailyJevBusy=true;defer{dailyJevBusy=false}
        do { _=try await api.request("/v1/jev/daily/"+m.generation,method:"POST",body:Data("{}".utf8),limit:65536);await refreshDailyJev() }
        catch { dailyJevMessage=error.localizedDescription }
    }

    func syncFavorites() async {
        guard let api=publishedAPI,let favoriteReplica else { return }
        await favoriteReplica.synchronize(api);favorites=favoriteReplica.codes;favoritesMessage=favoriteReplica.message
    }

    func chartData(for target:ChartTarget) async throws -> ChartDataset {
        try await latestChartDataset(code:target.code,through:target.through,cache:publishedCache,api:publishedAPI,fallback:publishedSnapshot?.manifest)
    }

    func stockDetail(code:String) async throws -> Stock {
        guard let manifest=publishedSnapshot?.manifest else { throw MobileFailure.server("请先同步已发布结果。") }
        if let saved=try? publishedCache.loadStockDetail(manifest,code:code) { return saved }
        guard let api=publishedAPI else { throw MobileFailure.server("连接服务器后可下载条件明细。") }
        let data=try await api.request("/v1/reports/\(manifest.strategy)/\(manifest.generation)/stocks/\(code).json",limit:65536)
        return try publishedCache.saveStockDetail(data,manifest:manifest,code:code)
    }

    func setLocalResearch(_ value:Bool) {
        guard !busy else { return };localResearch=value;UserDefaults.standard.set(value,forKey:"independentLocalResearch")
        report=nil;selection=nil;chartLoader.reset()
        if publishedMode { _=loadPublishedReport();Task { await synchronizePublished() } }
        else if !loadReport() { run(update:false) }
    }
}
