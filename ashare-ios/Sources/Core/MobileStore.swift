import Foundation
import Combine

@MainActor final class MobileStore:ObservableObject {
    @Published var snapshot:CachedSnapshot?
    @Published var strategy=AfterCloseStrategies.activeChoice(UserDefaults.standard.string(forKey:"mobileStrategy"))
    @Published var favorites=Set(UserDefaults.standard.stringArray(forKey:"mobileFavorites") ?? [])
    @Published var status:ServerStatus?
    @Published var busy=false
    @Published var message="导入连接配置后即可同步"
    @Published var error:String?
    @Published var connected=false
    @Published var favoritesMessage="自选等待同步"
    @Published var selectedTab=0
    @Published var realtime:RealtimeState?
    @Published var realtimeBusy=false
    @Published var realtimeMessage="连接服务器后查看定时策略和提醒"
    @Published var realtimeSettingsPresented=false
    @Published var realtimeNavigationRevision=0
    @Published var realtimeHistory:[RealtimeRunSummary]=[]
    @Published var realtimeDetail:RealtimeSnapshot?
    @Published var realtimeEventDetail:RealtimeEventDetail?
    @Published var realtimeDetailPresented=false
    @Published var realtimeDetailMessage=""
    @Published var daily:DailyState?
    @Published var dailyDetail:DailyReport?
    @Published var dailyBusy=false
    @Published var dailyPresented=false
    @Published var dailyRequestedDate:String?
    @Published var dailyMessage="交易日 16:10 后自动生成收盘总结"
    private var api:MobileAPI?
    private var favoriteReplica:WatchlistReplica?
    let cache:OfflineCache
    let dailyCache:DailyCache
    private var operation:UUID?
    private var historyOperation:UUID?
    private let realtimeReader:((String,Int) async throws -> Data)?
    var report:Report? { snapshot?.report }

    init(storageRoot:URL?=nil,startAutomatically:Bool=true,realtimeReader:((String,Int) async throws -> Data)?=nil) {
        self.realtimeReader=realtimeReader
        let base=storageRoot ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask).first!
        if storageRoot != nil { favorites=[] }
        cache=OfflineCache(root:base.appendingPathComponent("GuanlanMobile",isDirectory:true))
        dailyCache=DailyCache(root:base.appendingPathComponent("GuanlanDaily",isDirectory:true))
        daily=try? dailyCache.loadState()
        do {
            favoriteReplica=try WatchlistReplica(file:base.appendingPathComponent("GuanlanWatchlist/state.json"),legacy:favorites)
            favorites=favoriteReplica!.codes
        } catch { favoritesMessage="自选缓存未通过校验，原有观察列表已保留" }
        if startAutomatically { do {
            if let pairing=try CredentialStore.load() { api=try MobileAPI(pairing);connected=true }
            snapshot=try cache.load(strategy)
            if snapshot != nil { message="已载入上次同步结果" }
        } catch { self.error="上次连接或缓存读取失败，请重新导入配置。" } }
        #if DEBUG
        let inbox=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask).first!.appendingPathComponent("Pairing.guanlan")
        if startAutomatically,let data=try? Data(contentsOf:inbox) {
            do { try connect(data);try FileManager.default.removeItem(at:inbox) }
            catch { self.error=error.localizedDescription }
        }
        #endif
        if startAutomatically { Task { await synchronize() } }
    }

    func connect(_ data:Data) throws {
        guard data.count<=32768 else { throw MobileFailure.invalidConfiguration }
        let pairing=try JSONDecoder().decode(Pairing.self,from:data).validated()
        try CredentialStore.save(pairing);api=try MobileAPI(pairing);connected=true;error=nil
    }
    func importConnection(_ url:URL) async {
        let access=url.startAccessingSecurityScopedResource();defer { if access { url.stopAccessingSecurityScopedResource() } }
        do {
            guard let size=try url.resourceValues(forKeys:[.fileSizeKey]).fileSize,size<=32768 else { throw MobileFailure.invalidConfiguration }
            try connect(Data(contentsOf:url));await synchronize()
        }
        catch { self.error=error.localizedDescription }
    }
    func changeStrategy(_ value:String) {
        guard !busy,AfterCloseStrategies.ids.contains(value),value != strategy else { return }
        strategy=value;UserDefaults.standard.set(value,forKey:"mobileStrategy")
        snapshot=try? cache.load(value)
        Task { await synchronize() }
    }
    func synchronize() async {
        guard let api,!busy else { return }
        let id=UUID();operation=id;busy=true;error=nil;message="同步研究结果…"
        defer { if operation==id { busy=false } }
        do {
            let selected=strategy
            let server=try mobileDecoder().decode(ServerStatus.self,from:await api.request("/v1/status",limit:65536));status=server
            try await synchronizePublishedBundle(api,cache:cache,manifests:server.reports)
            guard operation==id,strategy==selected else { return }
            snapshot=try cache.load(selected)
            guard let manifest=snapshot?.manifest else { throw MobileFailure.invalidData }
            message="已同步 \(dateText(manifest.asOf)) 收盘结果"
        } catch is CancellationError { message="同步已取消，保留原有结果" }
        catch { self.error=error.localizedDescription;message=snapshot == nil ? "同步未完成":"离线缓存可继续使用" }
        await refreshStatus()
    }
    func refreshStatus() async {
        guard let api else { return }
        do {
            let data=try await api.request("/v1/status",limit:65536)
            status=try mobileDecoder().decode(ServerStatus.self,from:data)
            if status?.job.active==true { message=status!.job.message }
        } catch { if snapshot==nil { self.error=error.localizedDescription } }
    }
    func startJob(_ action:String) async {
        guard let api,!busy,["recompute","refresh"].contains(action) else { return }
        busy=true;error=nil
        do {
            let body=try JSONSerialization.data(withJSONObject:["action":action,"request_id":UUID().uuidString.lowercased()])
            let data=try await api.request("/v1/jobs",method:"POST",body:body,limit:65536)
            let job=try mobileDecoder().decode(ServerJob.self,from:data);message=job.message
            await refreshStatus()
        } catch { self.error=error.localizedDescription }
        busy=false
    }
    func watchJob() async {
        while !Task.isCancelled {
            await refreshStatus()
            await refreshRealtime()
            await refreshDaily()
            await syncFavorites()
            if !busy,let manifest=status?.reports[strategy],manifest != snapshot?.manifest { await synchronize() }
            if status?.job.status=="failed" { error=status?.job.message }
            do { try await Task.sleep(for:.seconds(status?.job.active==true ? 3:20)) }
            catch { return }
        }
    }
    func refreshRealtime() async {
        guard api != nil || realtimeReader != nil else { return }
        do {
            let data=try await readRealtime("/v1/realtime",limit:2*1024*1024)
            let value=try mobileDecoder().decode(RealtimeState.self,from:data)
            guard value.schemaVersion==1,value.events.count<=30 else { throw MobileFailure.invalidData }
            realtime=value;realtimeMessage=value.running ? "正在检查实时行情":"已同步实时提醒状态"
        } catch { realtimeMessage="实时服务暂未连接；请下拉刷新，已有研究结果仍可使用。" }
    }
    func realtimeAction(_ action:String,values:[String:Any]=[:]) async {
        guard let api,!realtimeBusy,["settings","test","scan"].contains(action) else { return }
        realtimeBusy=true
        defer { realtimeBusy=false }
        do {
            let body=try JSONSerialization.data(withJSONObject:values)
            _=try await api.request("/v1/realtime/\(action)",method:"POST",body:body,limit:65536)
            await refreshRealtime()
            realtimeMessage=action=="settings" ? "设置已保存" : (action=="test" ? "测试已提交，请查看 Bark 和提醒记录":"检查已提交，优先等待 Mac 执行")
        } catch { realtimeMessage=error.localizedDescription }
    }
    func openURL(_ url:URL) async {
        if url.isFileURL { await importConnection(url);return }
        guard let target=notificationTarget(url) else { return }
        switch target {
        case .daily(let date):
            closeRealtimeDetail()
            realtimeSettingsPresented=false;selectedTab=0
            dailyRequestedDate=date;dailyPresented=true;await refreshDaily()
        case .realtime:
            closeRealtimeDetail()
            dailyPresented=false
            realtimeSettingsPresented=false;realtimeNavigationRevision+=1
            selectedTab=1;await refreshRealtime()
        case .event(let id):
            dailyPresented=false;realtimeSettingsPresented=false;selectedTab=1
            // Reserve the user's selection before the first suspension point.
            await openRealtimeEvent(id)
            await refreshRealtime()
        }
    }

    func refreshRealtimeHistory() async {
        guard let api else { return }
        do {
            let value=try mobileDecoder().decode(RealtimeHistory.self,from:await api.request("/v1/realtime/history",limit:128*1024))
            guard value.schemaVersion==1,value.runs.count<=90,value.runs.allSatisfy({validRealtimeSlot($0.slot)}) else { throw MobileFailure.invalidData }
            realtimeHistory=value.runs
        } catch { realtimeDetailMessage="历史轮次暂不可读取，已保留现有记录" }
    }
    func openRealtimeRun(_ slot:String) async {
        guard (api != nil || realtimeReader != nil),validRealtimeSlot(slot) else { return }
        let operation=UUID();historyOperation=operation
        realtimeEventDetail=nil;realtimeDetail=nil;realtimeDetailMessage="正在读取固定轮次…";realtimeDetailPresented=true
        do {
            let report=try mobileDecoder().decode(RealtimeSnapshot.self,from:await readRealtime("/v1/realtime/runs/\(slot)",limit:256*1024))
            try report.validateArchive(slot);guard historyOperation==operation else { return };realtimeDetail=report;realtimeDetailMessage="已载入原始轮次"
        } catch { if historyOperation==operation { realtimeDetailMessage="这个历史轮次暂不可读取，可稍后重试。" } }
    }
    func openRealtimeEvent(_ id:String) async {
        guard (api != nil || realtimeReader != nil),UUID(uuidString:id) != nil else { return }
        let operation=UUID();historyOperation=operation
        realtimeEventDetail=nil;realtimeDetail=nil;realtimeDetailMessage="正在定位这条通知…";realtimeDetailPresented=true
        do {
            let detail=try mobileDecoder().decode(RealtimeEventDetail.self,from:await readRealtime("/v1/realtime/events/\(id)",limit:256*1024))
            guard detail.event.id==id else { throw MobileFailure.invalidData }
            guard detail.report==nil || detail.event.runId==detail.report?.slot else { throw MobileFailure.invalidData }
            try detail.report?.validateArchive(detail.event.runId)
            guard historyOperation==operation else { return }
            realtimeEventDetail=detail;realtimeDetail=detail.report;realtimeDetailMessage=detail.message
            if let value=detail.event.url,let url=URL(string:value),let target=notificationTarget(url),case .daily(let date)=target {
                realtimeDetailPresented=false;dailyRequestedDate=date;dailyPresented=true;await refreshDaily()
            }
        } catch { if historyOperation==operation { realtimeDetailMessage="这条通知暂不可读取，未用最新结果替代。" } }
    }
    func closeRealtimeDetail() { historyOperation=nil;realtimeDetailPresented=false }
    func openReminder(_ event:RealtimeEvent) async {
        if let text=event.url,let url=URL(string:text),let target=notificationTarget(url),case .daily=target { await openURL(url) }
        else { await openRealtimeEvent(event.id) }
    }
    private func readRealtime(_ path:String,limit:Int) async throws -> Data {
        if let realtimeReader { return try await realtimeReader(path,limit) }
        guard let api else { throw MobileFailure.unauthorized }
        return try await api.request(path,limit:limit)
    }

    func openDailySummary() { dailyRequestedDate=nil;dailyPresented=true }
    func refreshDaily() async {
        guard let api else { return }
        do {
            let data=try await api.request("/v1/daily",limit:128*1024)
            let value=try dailyCache.saveState(data);daily=value;dailyMessage=value.status.message
            if dailyDetail?.date==value.latest?.date { dailyDetail=value.latest }
        } catch { dailyMessage="收盘总结暂未连接，已有缓存仍可阅读。" }
    }
    func loadDailyReport(_ date:String) async {
        guard validDailyDate(date),!dailyBusy else { return }
        dailyDetail=try? dailyCache.loadReport(date)
        guard let api else { return }
        dailyBusy=true;defer { dailyBusy=false }
        do {
            let data=try await api.request("/v1/daily/\(date)",limit:128*1024)
            let value=try dailyCache.saveReport(data)
            guard value.date==date else { throw MobileFailure.invalidData };dailyDetail=value
        } catch { dailyMessage="该日期的总结尚未载入，可稍后重试。" }
    }
    @discardableResult func dailyAction(_ action:String,values:[String:Any]=[:]) async -> Bool {
        guard let api,!dailyBusy,["settings","generate"].contains(action) else { return false }
        dailyBusy=true;defer { dailyBusy=false }
        do {
            let body=try JSONSerialization.data(withJSONObject:values)
            _=try await api.request("/v1/daily/\(action)",method:"POST",body:body,limit:65536)
            await refreshDaily();return true
        } catch { dailyMessage=error.localizedDescription;return false }
    }
    func toggleFavorite(_ stock:Stock) {
        guard let favoriteReplica else { favoritesMessage="自选缓存暂不可写入，请先检查本机记录";return }
        do {
            try favoriteReplica.toggle(stock.id);favorites=favoriteReplica.codes;favoritesMessage=favoriteReplica.message
            Task { await syncFavorites() }
        } catch { favoritesMessage=error.localizedDescription }
    }
    func syncFavorites() async {
        guard let api,let favoriteReplica else { return }
        await favoriteReplica.synchronize(api);favorites=favoriteReplica.codes;favoritesMessage=favoriteReplica.message
    }
    func candles(_ manifest:MobileManifest,code:String) async throws -> [Candle] {
        if let cached=try cache.loadChart(manifest,code:code) { return cached }
        guard let api else { throw MobileFailure.server("连接服务器后可下载这只股票的 K 线。") }
        guard validStockCode(code) else { throw MobileFailure.invalidData }
        let data=try await api.request("/v1/reports/\(manifest.strategy)/\(manifest.generation)/charts/\(code).json",limit:128*1024)
        return try cache.saveChart(data,manifest:manifest,code:code)
    }
    func chartData(_ manifest:MobileManifest,code:String) async throws -> ChartDataset {
        try await requestChartDataset(manifest:manifest,code:code,cache:cache,api:api)
    }
    func chartData(code:String,through:String?) async throws -> ChartDataset {
        try await latestChartDataset(code:code,through:through,cache:cache,api:api,fallback:snapshot?.manifest)
    }
    func export(_ stocks:[Stock]) throws -> URL {
        var rows=["代码,名称,行业,日期,收盘价,涨跌幅%,匹配分,状态,回踩参考,突破观察,失效参考"]
        rows += stocks.map { [$0.tsCode,$0.name,$0.industry,$0.tradeDate,decimal($0.close),decimal($0.change),decimal($0.score,digits:1),$0.state,decimal($0.support),decimal($0.breakout),decimal($0.invalidation)].map(csvCell).joined(separator:",") }
        let file=FileManager.default.temporaryDirectory.appendingPathComponent("观澜选股-\(report?.asOf ?? "当前").csv")
        try ("\u{FEFF}"+rows.joined(separator:"\r\n")).write(to:file,atomically:true,encoding:.utf8);return file
    }
}
