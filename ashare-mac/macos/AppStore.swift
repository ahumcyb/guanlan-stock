import AppKit
import Combine
import CryptoKit
import Foundation
import UniformTypeIdentifiers

@MainActor final class AppStore: ObservableObject {
    @Published var report: Report?
    @Published var busy = false
    @Published var progress = "准备就绪"
    @Published var error: String?
    @Published var activity = ""
    @Published var dataRoot: String
    @Published var favorites: Set<String>
    @Published var selection: String?
    let chartLoader=ChartLoadState()
    private var chartTask:Task<Void,Never>?
    @Published var historyLog = ""
    @Published var strategy: String
    @Published var remoteEnabled: Bool
    @Published var localResearch=false
    @Published var serverStatus:ServerStatus?
    @Published var dailyState:DailyState?
    @Published var realtimeState:RealtimeState?
    @Published var dailyJev:JevReview?
    @Published var dailyJevBusy=false
    @Published var dailyJevMessage=""
    var selectedDailyJev:JevReview? { guard publishedMode,let m=publishedSnapshot?.manifest,let r=dailyJev,r.bound(to:m) else { return nil };return r }
    @Published var favoritesMessage="自选等待同步"
    var publishedAPI:MobileAPI?
    var publishedSnapshot:CachedSnapshot?
    var favoriteReplica:WatchlistReplica?
    var lastContentRevisions:ContentRevisions?
    let publishedCache:OfflineCache
    var publishedMode:Bool { !localResearch && publishedAPI != nil }
    let runtime: Runtime
    let output: URL
    let overlay: URL
    private var process: Process?
    private var generation: URL?
    private var cancelled = false
    var serverConfig:URL { URL(fileURLWithPath:runtime.projectRoot).appendingPathComponent("settings/server.json") }
    var serverCache:URL { URL(fileURLWithPath:runtime.projectRoot).appendingPathComponent(".cache/server-data") }
    var serverConfigured:Bool { FileManager.default.fileExists(atPath:serverConfig.path) }
    var activeDataRoot:String { remoteEnabled ? serverCache.appendingPathComponent("current").path:dataRoot }
    var activeOverlay:String { remoteEnabled ? URL(fileURLWithPath:runtime.projectRoot).appendingPathComponent(".cache/server-overlay").path:overlay.path }
    var serverHost:String {
        guard let data=try? Data(contentsOf:serverConfig),let value=try? JSONSerialization.jsonObject(with:data) as? [String:Any] else { return "未配置" }
        return value["host"] as? String ?? "未配置"
    }
    private let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()

    init() {
        let initialDecoder = JSONDecoder(); initialDecoder.keyDecodingStrategy = .convertFromSnakeCase
        let fallback = Runtime(projectRoot: FileManager.default.currentDirectoryPath, python: "/usr/bin/python3")
        if let url = Bundle.main.url(forResource: "runtime", withExtension: "json"),
           let data = try? Data(contentsOf: url), let r = try? initialDecoder.decode(Runtime.self, from: data) {
            runtime = r
        } else { runtime = fallback }
        output = URL(fileURLWithPath: runtime.projectRoot).appendingPathComponent(".cache/analysis")
        overlay = URL(fileURLWithPath: runtime.projectRoot).appendingPathComponent("data")
        let base=FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask).first!
        publishedCache=OfflineCache(root:base.appendingPathComponent("GuanlanPublished"))
        dataRoot = UserDefaults.standard.string(forKey: "dataRoot")
            ?? URL(fileURLWithPath: runtime.projectRoot).deletingLastPathComponent().appendingPathComponent("data").path
        favorites = Set(UserDefaults.standard.stringArray(forKey: "favorites") ?? [])
        strategy = AfterCloseStrategies.activeChoice(UserDefaults.standard.string(forKey:"strategy"))
        remoteEnabled = UserDefaults.standard.object(forKey:"useServerData") as? Bool
            ?? FileManager.default.fileExists(atPath:runtime.projectRoot+"/settings/server.json")
        localResearch=UserDefaults.standard.bool(forKey:"independentLocalResearch")
        do {
            let config=URL(fileURLWithPath:runtime.projectRoot).appendingPathComponent("settings/mobile-viewer.json")
            if FileManager.default.fileExists(atPath:config.path) {
                publishedAPI=try MobileAPI(JSONDecoder().decode(Pairing.self,from:Data(contentsOf:config)))
            }
            favoriteReplica=try WatchlistReplica(file:base.appendingPathComponent("GuanlanWatchlist/state.json"),legacy:favorites)
            favorites=favoriteReplica!.codes
        } catch { self.error="连接或自选缓存未通过校验，原有记录已保留。" }
        if publishedMode { _=loadPublishedReport();Task { await watchPublishedState() } }
        else { if !loadReport() { run(update:remoteEnabled) };Task { await watchPublishedState() } }
    }

    @discardableResult func loadReport() -> Bool {
        do {
            let pointer = try decoder.decode(SnapshotPointer.self, from: Data(contentsOf: output.appendingPathComponent("current.json")))
            guard pointer.generation.range(of: #"^\d{8}T\d{6}-[a-f0-9]{6}$"#, options: .regularExpression) != nil else {
                throw CocoaError(.fileReadCorruptFile)
            }
            let folder = output.appendingPathComponent(pointer.generation)
            let data = try Data(contentsOf: folder.appendingPathComponent("report.json"))
            let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard hash == pointer.sha256 else { throw CocoaError(.fileReadCorruptFile) }
            let r = try decoder.decode(Report.self, from: data)
            guard r.schemaVersion == 1, sameDataDirectory(r.sourceRoot,activeDataRoot) else { return false }
            guard (r.strategyId ?? "pullback")==strategy else { return false }
            report = r; generation = folder
            progress = "已载入 \(dateText(r.asOf)) 收盘数据"
            if selection == nil || !r.stocks.contains(where: {$0.id == selection}) {
                selection = r.stocks.first(where: {$0.rank == 1})?.id ?? r.stocks.first?.id
            }
            loadChart()
            return true
        } catch {
            return false
        }
    }

    func select(_ code: String?) { selection = code; loadChart() }

    func loadChart() {
        chartTask?.cancel();chartLoader.reset()
        guard let code=selection else { return }
        if publishedMode,let manifest=publishedSnapshot?.manifest {
            chartTask=Task { await chartLoader.load(key:manifest.generation+code) {
                try await requestChartDataset(manifest:manifest,code:code,cache:publishedCache,api:publishedAPI)
            } };return
        }
        guard let folder=generation,let report else { return }
        guard code.range(of: #"^\d{6}\.(SH|SZ|BJ)$"#, options: .regularExpression) != nil else { return }
        let runtime=runtime,asOf=report.asOf,revision=report.dataRevision
        chartTask=Task { await chartLoader.load(key:folder.path+code) {
            try await Task.detached(priority:.userInitiated) {
                let extended=folder.appendingPathComponent("charts-extended/\(code).json.gz")
                if FileManager.default.fileExists(atPath:extended.path) {
                    let process=Process(),output=Pipe();process.executableURL=URL(fileURLWithPath:runtime.python)
                    process.currentDirectoryURL=URL(fileURLWithPath:runtime.projectRoot)
                    process.arguments=["-m","engine.chart_data","--folder",folder.path,"--code",code,"--as-of",asOf]
                    if let revision { process.arguments! += ["--revision",revision] }
                    process.standardOutput=output;process.standardError=FileHandle.nullDevice
                    try process.run();let bytes=output.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit()
                    guard process.terminationStatus==0 else { throw ChartDataError.invalid }
                    return try ChartDataset.decode(bytes,code:code,asOf:asOf,revision:revision)
                }
                let bytes=try Data(contentsOf:folder.appendingPathComponent("charts/\(code).json"))
                return ChartDataset.legacy(try decodeCandles(bytes,asOf:asOf),code:code,asOf:asOf,revision:revision)
            }.value
        } }
    }

    func toggleFavorite(_ stock: Stock) {
        guard let favoriteReplica else { favoritesMessage="自选缓存暂不可写入，请先检查本机记录";return }
        do { try favoriteReplica.toggle(stock.id);favorites=favoriteReplica.codes;favoritesMessage=favoriteReplica.message;Task { await syncFavorites() } }
        catch { favoritesMessage=error.localizedDescription }
    }

    func run(update: Bool) {
        guard !busy else { return }
        if publishedMode { Task { await submitPublishedJob(update ? "refresh":"recompute") };return }
        error = nil; cancelled = false; busy = true; historyLog = ""
        let missingCache=remoteEnabled && !FileManager.default.fileExists(atPath:activeDataRoot+"/manifest.json")
        launch(module:(update || missingCache) ? (remoteEnabled ? "engine.remote":"engine.update"):"engine.cli")
    }

    private func launch(module: String) {
        activity = module == "engine.remote" ? "同步服务器":(module == "engine.update" ? "更新数据" : "选股计算")
        progress = module == "engine.remote" ? "连接行情服务器…":(module == "engine.update" ? "连接行情数据源…" : "读取日线缓存…")
        let task = Process(); let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: runtime.python)
        task.currentDirectoryURL = URL(fileURLWithPath:runtime.projectRoot)
        task.arguments = module == "engine.remote"
            ? ["-u","-m",module,"--config",serverConfig.path,"--cache",serverCache.path]
            : ["-u", "-m", module, "--data-root", activeDataRoot, "--overlay", activeOverlay]
        if module == "engine.cli" { task.arguments! += ["--output",output.path,"--strategy",strategy] }
        task.standardOutput = pipe; task.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty, let text = String(data:chunk, encoding:.utf8) else { return }
            Task { @MainActor in
                guard let self else { return }
                self.historyLog = String((self.historyLog+text).suffix(16000))
                if let line = text.split(separator:"\n").last { self.progress = String(line) }
            }
        }
        task.terminationHandler = { [weak self] task in
            pipe.fileHandleForReading.readabilityHandler = nil
            let tail = pipe.fileHandleForReading.readDataToEndOfFile()
            Task { @MainActor in
                guard let self else { return }
                if let text = String(data:tail,encoding:.utf8), !text.isEmpty { self.historyLog += text }
                self.process = nil
                if self.cancelled { self.busy=false; self.progress="已取消，保留上次结果"; return }
                if task.terminationStatus == 0 && ["engine.update","engine.remote"].contains(module) {
                    self.launch(module:"engine.cli")
                } else {
                    self.busy = false
                    if task.terminationStatus == 0 {
                        if !self.loadReport() { self.error="计算完成，但报告未通过读取校验。" }
                    } else {
                        self.error = self.historyLog.split(separator:"\n").last.map(String.init) ?? "操作未完成，请重试。"
                        self.progress = "操作未完成 · 上次结果已保留"
                    }
                }
            }
        }
        process = task
        do { try task.run() }
        catch { busy=false; self.error="无法启动研究引擎，请运行工程中的 scripts/setup.sh。" }
    }

    func cancel() { cancelled = true; process?.terminate() }

    func retry() { if publishedMode { Task { await synchronizePublished() } } else { run(update:activity != "选股计算") } }

    func changeDataSource(_ useServer:Bool) {
        guard !busy, useServer != remoteEnabled else { return }
        guard !useServer || serverConfigured else { error="服务器连接尚未配置。";return }
        remoteEnabled=useServer;UserDefaults.standard.set(useServer,forKey:"useServerData")
        report=nil;generation=nil;selection=nil;chartLoader.reset()
        run(update:useServer)
    }

    func changeStrategy(_ value:String) {
        guard !busy, AfterCloseStrategies.ids.contains(value), value != strategy else { return }
        strategy=value; UserDefaults.standard.set(value,forKey:"strategy")
        if publishedMode { _=loadPublishedReport();Task { await synchronizePublished() };return }
        run(update:false)
    }

    func chooseDataRoot() {
        guard !busy else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles=false; panel.canChooseDirectories=true
        panel.message="选择包含 raw/daily.parquet 的行情数据目录"
        panel.directoryURL=URL(fileURLWithPath:dataRoot)
        if panel.runModal() == .OK, let url=panel.url {
            guard FileManager.default.fileExists(atPath:url.appendingPathComponent("raw/daily.parquet").path) else {
                error="这个目录没有 raw/daily.parquet，请选择行情数据根目录。"; return
            }
            dataRoot=url.path; UserDefaults.standard.set(dataRoot,forKey:"dataRoot")
            report=nil; generation=nil; selection=nil; chartLoader.reset(); run(update:false)
        }
    }

    func export(_ stocks: [Stock]) {
        guard !stocks.isEmpty else { return }
        let panel=NSSavePanel(); panel.allowedContentTypes=[.commaSeparatedText]
        panel.nameFieldStringValue="观澜选股-\(report?.asOf ?? "")-\(stocks.count)只.csv"
        guard panel.runModal() == .OK, let url=panel.url else { return }
        var rows=["代码,名称,行业,信号日期,收盘价,涨跌幅%,匹配分,状态,回踩参考,失效参考"]
        rows += stocks.map { s in [s.tsCode,s.name,s.industry,s.tradeDate,decimal(s.close),decimal(s.change),
                                  decimal(s.score,digits:1),s.state,decimal(s.support),decimal(s.invalidation)].map(csvCell).joined(separator:",") }
        do { try ("\u{FEFF}"+rows.joined(separator:"\r\n")).write(to:url,atomically:true,encoding:.utf8)
            progress="已导出 \(stocks.count) 只股票：\(url.lastPathComponent)"
        } catch { self.error="导出失败，请检查目标目录权限。" }
    }

    func revealReport() {
        if publishedMode { NSWorkspace.shared.selectFile(nil,inFileViewerRootedAtPath:publishedCache.root.path);return }
        guard let folder=generation else { return }
        NSWorkspace.shared.activateFileViewerSelecting([folder.appendingPathComponent("report.json")])
    }
}
