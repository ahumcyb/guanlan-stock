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
            let state=try mobileDecoder().decode(ServerStatus.self,from:await api.request("/v2/status",limit:65536));serverStatus=state
            progress="正在同步已发布的五套策略…"
            try await synchronizePublishedBundle(api,cache:publishedCache,manifests:state.reports)
            guard publishedMode else { return };_=loadPublishedReport()
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
                    serverStatus=try mobileDecoder().decode(ServerStatus.self,from:await api.request("/v2/status",limit:65536))
                    if publishedMode,!busy,let manifest=serverStatus?.reports[strategy],manifest != publishedSnapshot?.manifest { await synchronizePublished() }
                    if serverStatus?.job.active==true { progress=serverStatus!.job.message }
                } catch { if publishedMode && !busy { progress=report==nil ? "服务器暂未连接":"离线缓存 · \(dateText(report!.asOf))" } }
                if let data=try? await api.request("/v2/daily",limit:128*1024),let value=try? mobileDecoder().decode(DailyState.self,from:data), (try? value.validate()) != nil { dailyState=value }
                if let data=try? await api.request("/v1/realtime",limit:2*1024*1024) { realtimeState=try? mobileDecoder().decode(RealtimeState.self,from:data) }
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

    func setLocalResearch(_ value:Bool) {
        guard !busy else { return };localResearch=value;UserDefaults.standard.set(value,forKey:"independentLocalResearch")
        report=nil;selection=nil;chartLoader.reset()
        if publishedMode { _=loadPublishedReport();Task { await synchronizePublished() } }
        else if !loadReport() { run(update:false) }
    }
}
