import SwiftUI

@MainActor final class DailyDesktopStore:ObservableObject {
    @Published var state:DailyState?
    @Published var detail:DailyReport?
    @Published var busy=false
    @Published var message="连接收盘总结服务…"
    let cache:DailyCache
    init() {
        let base=FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask).first!
        cache=DailyCache(root:base.appendingPathComponent("GuanlanDaily"))
        state=try? cache.loadState()
    }
    @discardableResult func request(_ action:String,runtime:Runtime,values:[String:Any]=[:]) async -> Bool {
        guard !busy else { return false };busy=true;defer { busy=false }
        if action=="report",let date=values["date"] as? String { detail=try? cache.loadReport(date) }
        do {
            let input=try JSONSerialization.data(withJSONObject:values)
            let data=try await Task.detached(priority:.utility) {
                let process=Process();let output=Pipe();let source=Pipe()
                process.executableURL=URL(fileURLWithPath:runtime.python)
                process.currentDirectoryURL=URL(fileURLWithPath:runtime.projectRoot)
                process.arguments=["-m","mobile_server.daily_control","--config",runtime.projectRoot+"/settings/mobile-viewer.json",action]
                process.standardOutput=output;process.standardError=FileHandle.nullDevice;process.standardInput=source
                try process.run();source.fileHandleForWriting.write(input);try source.fileHandleForWriting.close()
                let result=output.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit()
                guard process.terminationStatus==0,result.count<=128*1024 else { throw CocoaError(.fileReadUnknown) }
                return result
            }.value
            if action=="state" {
                state=try cache.saveState(data);message=state?.status.message ?? "已同步"
                if detail?.date==state?.latest?.date { detail=state?.latest }
            }
            else if action=="report" { detail=try cache.saveReport(data);message="已载入该交易日总结" }
            else { message=action=="settings" ? "设置已保存":"已提交，请等待收盘行情核验和分析" }
            return true
        } catch { message="收盘服务暂未连接；已有缓存仍可阅读，请稍后重试。";return false }
    }
}

struct DailySummaryView:View {
    var initialDate:String?=nil
    @EnvironmentObject var app:AppStore
    @StateObject private var store=DailyDesktopStore()
    @State private var selectedDate=""
    @State private var showSettings=false
    @State private var enabled=false
    @State private var notify=true
    @State private var ai=true
    @State private var model="deepseek-v4-flash"
    @State private var key=""
    private var report:DailyReport? { selectedDate.isEmpty ? store.state?.latest:(store.detail?.date==selectedDate ? store.detail:nil) }
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                HStack(alignment:.top) {
                    pageTitle("每日收盘总结",subtitle:"交易日 16:10 起核验行情 · Mac 优先更新与选股")
                    Spacer()
                    Button("同步") { Task { await refresh() } }.disabled(store.busy)
                    Button("重新核验并生成") { Task { await store.request("generate",runtime:app.runtime,values:["refresh_facts":true]);await refresh() } }.disabled(store.busy)
                    Button("总结设置") { loadSettings();showSettings.toggle() }.disabled(store.state==nil)
                }
                HStack {
                    Badge(text:store.state?.settings.enabled==true ? "自动总结已开启":"自动总结已暂停")
                    if store.state?.schedulerOnline==false { Badge(text:"调度暂离线",color:Palette.amber) }
                    Text(store.message).font(.system(size:12)).foregroundStyle(Palette.muted)
                    if store.busy { ProgressView().controlSize(.small) }
                    Spacer()
                    Text("下次 \(dailyTime(store.state?.status.nextRunAt))").font(.system(size:11)).foregroundStyle(Palette.muted)
                }
                if showSettings { settingsPanel }
                Picker("交易日",selection:$selectedDate) {
                    Text("最新总结").tag("")
                    ForEach(store.state?.history ?? []) { item in Text(dateText(item.date)).tag(item.date) }
                }.frame(width:230).disabled(store.busy)
                if let report {
                    HStack {
                        Text(report.analysis.headline).font(.system(size:23,weight:.semibold))
                        Spacer();Badge(text:dateText(report.date))
                        Badge(text:report.analysis.status=="ready" ? "DeepSeek 解读":(report.analysis.status=="pending" ? "分析中":"量价摘要"),color:report.analysis.status=="ready" ? Palette.teal:Palette.amber)
                    }
                    if let changes=report.evidence.marketChanges { changesPanel(changes) }
                    performancePanel(report.evidence.performance)
                    realtimePerformancePanel(report.evidence.realtimePerformance)
                    analysisPanel(report.analysis,showStrategy:report.evidence.performance != nil)
                    if let changes=report.evidence.selectionChanges { selectionPanel(changes) }
                    DisclosureGroup("收盘量价与行业明细") {
                    marketPanel(report.evidence)
                    HStack(alignment:.top,spacing:16) {
                        sectorPanel("相对较强行业",rows:report.evidence.sectorsStrong)
                        sectorPanel("相对较弱行业",rows:report.evidence.sectorsWeak)
                    }
                    }
                    DisclosureGroup("本日新选 · 留待下一交易日评价") {
                    ForEach(report.evidence.strategies) { strategy in strategyPanel(strategy) }
                    }
                    ForEach(report.evidence.warnings,id:\.self) { Text($0).font(.system(size:11)).foregroundStyle(Palette.amber) }
                    Text("生成于 \(dailyTime(report.generatedAt)) · 量价来源：已核验的收盘数据。行业数据为成分股等权均值，非行业指数；AI 未核验新闻、公告或财务，不改变选股规则。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(5)
                } else {
                    Panel { EmptyViewMessage(icon:"sun.horizon",title:"等待收盘后的完整总结",message:"16:10 起核验当日行情，再生成市场、行业与四套策略复盘。可以在总结设置中更换 DeepSeek Key。") }
                }
            }.padding(30)
        }
        .task {
            if let initialDate { selectedDate=initialDate }
            await refresh()
            while !Task.isCancelled {
                do { try await Task.sleep(for:.seconds(20)) } catch { return }
                if !store.busy { await store.request("state",runtime:app.runtime) }
            }
        }
        .onChange(of:selectedDate) { _,date in if !date.isEmpty { Task { await store.request("report",runtime:app.runtime,values:["date":date]) } } }
    }
    private func refresh() async {
        await store.request("state",runtime:app.runtime)
        if !selectedDate.isEmpty { await store.request("report",runtime:app.runtime,values:["date":selectedDate]) }
    }
    private func loadSettings() {
        if let s=store.state?.settings { enabled=s.enabled;notify=s.notificationEnabled;ai=s.aiEnabled;model=s.model }
    }
    private var settingsPanel:some View {
        Panel {
            VStack(alignment:.leading,spacing:14) {
                Text("自动复盘与 DeepSeek").font(.headline)
                HStack { Toggle("收盘后自动生成",isOn:$enabled);Toggle("完成后手机提醒",isOn:$notify);Toggle("使用 DeepSeek 分析",isOn:$ai) }
                HStack { Picker("模型",selection:$model) { Text("V4 Flash").tag("deepseek-v4-flash");Text("V4 Pro").tag("deepseek-v4-pro") }.frame(width:280);Spacer() }
                SecureField(store.state?.settings.deepseekConfigured==true ? "已配置 · 输入新 API Key 可替换":"DeepSeek API Key",text:$key)
                    .textFieldStyle(.roundedBorder)
                Text("Key 和模型与实时解读共用。留空保留现有 Key；保存后用于后续分析。只发送公开量价与候选摘要，调用费用由 DeepSeek 账户承担。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(4)
                HStack {
                    Button("保存设置") {
                        Task {
                            var values:[String:Any]=["enabled":enabled,"notification_enabled":notify,"ai_enabled":ai,"model":model]
                            let secret=key.trimmingCharacters(in:.whitespacesAndNewlines)
                            if !secret.isEmpty { values["deepseek_key"]=secret }
                            if await store.request("settings",runtime:app.runtime,values:values) { key="";showSettings=false;await refresh() }
                        }
                    }.buttonStyle(.borderedProminent).disabled(store.busy)
                    Button("重做最新总结的 AI") { Task { await store.request("generate",runtime:app.runtime,values:["retry_ai":true]);await refresh() } }.disabled(store.busy)
                }
            }
        }
    }
    private func marketPanel(_ evidence:DailyEvidence)->some View {
        Panel {
            VStack(alignment:.leading,spacing:18) {
                Text("\(evidence.market.stockCount.formatted()) 只沪深股票 · 收盘量价").font(.headline)
                HStack { Metric(label:"上涨家数",value:evidence.market.advancers.formatted(),color:Palette.up);Metric(label:"下跌家数",value:evidence.market.decliners.formatted(),color:Palette.down);Metric(label:"成交额 / 亿元",value:decimal(evidence.market.turnoverYi)) }
                HStack { Metric(label:"收盘涨停",value:String(evidence.market.limitUp));Metric(label:"收盘跌停",value:String(evidence.market.limitDown));Metric(label:"策略池 MA20 上方占比",value:percent(evidence.market.breadth)) }
                Text("平盘 \(evidence.market.unchanged) 只 · 涨跌幅中位数 \(dailyChange(evidence.market.medianChange)) · \(evidence.universeLabel)").font(.system(size:11)).foregroundStyle(Palette.muted)
            }
        }
    }
    private func changesPanel(_ changes:DailyMarketChanges)->some View {
        Panel { VStack(alignment:.leading,spacing:14) {
            Text("相对 \(dateText(changes.previousDate)) 的变化").font(.headline)
            HStack {
                Metric(label:"成交额变化",value:dailyChange(changes.turnoverChangePct))
                Metric(label:"上涨家数变化",value:String(format:"%+d",changes.advancersChange))
                Metric(label:"市场宽度变化",value:String(format:"%+.2f 个百分点",changes.breadthChangePp))
            }
            if !changes.enteredStrong.isEmpty { Text("进入行业涨幅前五："+changes.enteredStrong.joined(separator:"、")).font(.system(size:12)) }
            Text("比较两个交易日的已核验横截面，不代表连续趋势。").font(.caption).foregroundStyle(Palette.muted)
        } }
    }
    private func selectionPanel(_ changes:[DailySelectionChange])->some View {
        Panel { VStack(alignment:.leading,spacing:16) {
            Text("名单变化与条件复核").font(.headline)
            ForEach(changes) { group in
                VStack(alignment:.leading,spacing:8) {
                    Text(group.name).font(.system(size:13,weight:.semibold))
                    if group.status=="unavailable" { Text("缺少可验证的此前精选，暂不比较名单。").font(.caption).foregroundStyle(Palette.muted) }
                    else {
                        Text(group.status=="new_strategy" ? "新启用策略 · 首次记录 \(group.added.count) 只":"新增 \(group.added.count) · 连续两期入选 \(group.retained.count) · 移出 \(group.removed.count)").font(.system(size:12)).foregroundStyle(Palette.muted)
                        if !group.retained.isEmpty { Text("连续入选："+group.retained.map(\.name).joined(separator:"、")).font(.system(size:12)) }
                        DisclosureGroup("查看变动依据") {
                            if !group.added.isEmpty { Text("本期新选："+group.added.map(\.name).joined(separator:"、")).font(.system(size:12)).padding(.top,6) }
                            ForEach(group.removed) { row in Text(row.name+" · "+(row.reason ?? "本期未进入精选")).font(.system(size:12)).foregroundStyle(Palette.muted).padding(.top,6) }
                        }.font(.caption)
                    }
                }
            }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func performancePanel(_ performance:DailyPerformance?)->some View {
        Panel { VStack(alignment:.leading,spacing:16) {
            Text("昨日精选 · 今日结算").font(.headline)
            if let performance {
                Text("\(dateText(performance.signalDate ?? "—")) 精选 → \(dateText(performance.evaluationDate)) 收盘").font(.caption).foregroundStyle(Palette.muted)
                Text(performance.message ?? "等权观察口径，未计交易费用及成交约束。").font(.system(size:11)).foregroundStyle(Palette.muted)
                ForEach(performance.strategies) { group in
                    VStack(alignment:.leading,spacing:9) {
                        HStack { Text(group.name).font(.system(size:13,weight:.semibold));if !AfterCloseStrategies.ids.contains(group.id) { Badge(text:"历史策略",color:Palette.amber) };Spacer();Text(group.meanReturnPct.map(dailyChange) ?? "—").monospacedDigit().foregroundStyle((group.meanReturnPct ?? 0)>=0 ? Palette.up:Palette.down) }
                        Text("昨日 \(group.selectedCount) 只 · 已结算 \(group.settledCount) 只 · 上涨 \(group.upCount) / 下跌 \(group.downCount) / 平盘 \(group.flatCount)").font(.system(size:11)).foregroundStyle(Palette.muted)
                        if group.status=="partial" { Text("存在未结算股票，整体均值暂不展示。").font(.caption).foregroundStyle(Palette.amber) }
                        if group.status=="no_picks" { Text("上一交易日没有精选。").font(.caption).foregroundStyle(Palette.muted) }
                        DisclosureGroup("逐股结算") {
                            ForEach(group.rows) { row in
                                ChartLink(target:ChartTarget(code:row.tsCode,name:row.name,focus:performance.signalDate.map{ChartFocus(date:$0,price:row.previousClose,label:"昨日精选")},through:performance.evaluationDate)) {
                                    HStack { Text(row.name);Text(String(row.tsCode.prefix(6))).foregroundStyle(Palette.muted);Spacer();Text(row.returnPct.map(dailyChange) ?? (row.reason ?? "未结算"));Image(systemName:"chart.xyaxis.line").foregroundStyle(Palette.teal) }.font(.system(size:11)).padding(.top,5)
                                }
                            }
                        }.font(.system(size:11))
                    }.padding(.vertical,5)
                }
                if !(performance.newStrategyIds ?? []).isEmpty { Text("新启用策略尚无前一交易日精选，下一个交易日起才能结算。").font(.caption).foregroundStyle(Palette.muted) }
            } else { Text("旧版总结尚未包含上一交易日精选结算。可重新核验并生成最近收盘日。").font(.caption).foregroundStyle(Palette.muted) }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func analysisPanel(_ analysis:DailyAnalysis,showStrategy:Bool)->some View {
        Panel {
            VStack(alignment:.leading,spacing:16) {
                if analysis.status=="pending" { ProgressView("正在生成 DeepSeek 分析…") }
                paragraph("市场量价",analysis.marketView)
                paragraph("行业分化",analysis.sectorView)
                if showStrategy { paragraph("昨日策略结算",analysis.strategyView) }
                paragraph("下一交易日",analysis.watchNext)
                ForEach(analysis.risks,id:\.self) { Text("· "+$0).font(.system(size:12)).foregroundStyle(Palette.amber).lineSpacing(4) }
            }.frame(maxWidth:.infinity,alignment:.leading)
        }
    }
    @ViewBuilder private func paragraph(_ title:String,_ body:String)->some View {
        if !body.isEmpty { VStack(alignment:.leading,spacing:7) { Text(title).font(.system(size:13,weight:.semibold));Text(body).font(.system(size:13)).lineSpacing(6).textSelection(.enabled) } }
    }
    private func realtimePerformancePanel(_ performance:DailyRealtimePerformance?)->some View {
        Panel { VStack(alignment:.leading,spacing:18) {
            Text("昨日实时提醒 · 今日收益").font(.headline)
            if let performance {
                Text("\(dateText(performance.signalDate ?? "—")) 候选 → \(dateText(performance.evaluationDate)) 收盘").font(.caption).foregroundStyle(Palette.muted)
                ForEach(performance.strategies) { group in
                    VStack(alignment:.leading,spacing:10) {
                        Text(group.name).font(.system(size:13,weight:.semibold))
                        Text(group.message).font(.caption).foregroundStyle(Palette.muted)
                        if let selected=group.selectedCount {
                            HStack {
                                Metric(label:"今日等权涨跌",value:group.meanReturnPct.map(dailyChange) ?? "—",color:group.meanReturnPct.map{$0>=0 ? Palette.up:Palette.down} ?? Palette.muted)
                                Metric(label:"提醒价至今收",value:group.meanSignalReturnPct.map(dailyChange) ?? "—",color:group.meanSignalReturnPct.map{$0>=0 ? Palette.up:Palette.down} ?? Palette.muted)
                                Spacer()
                                Text("候选 \(selected) · 已结算 \(group.settledCount)\n上涨 \(group.upCount) / 下跌 \(group.downCount) / 平盘 \(group.flatCount)").font(.caption).foregroundStyle(Palette.muted)
                            }
                            if group.status=="no_picks" { Text("昨日该轮次无候选，暂无收益样本。").font(.caption).foregroundStyle(Palette.muted) }
                            if group.status=="partial" { Text("存在未结算股票，两个整体均值均暂不展示。").font(.caption).foregroundStyle(Palette.amber) }
                            if !group.rows.isEmpty {
                                DisclosureGroup("逐股收益与价格") {
                                    ForEach(group.rows) { row in
                                        VStack(alignment:.leading,spacing:5) {
                                            HStack { Text(row.name);Text(String(row.tsCode.prefix(6))).foregroundStyle(Palette.muted);Spacer();Text("今日 "+(row.returnPct.map(dailyChange) ?? "未结算")).foregroundStyle(row.returnPct.map{$0>=0 ? Palette.up:Palette.down} ?? Palette.muted);Text("提醒价至今收 "+(row.signalReturnPct.map(dailyChange) ?? "—")) }
                                            Text("提醒价 \(decimal(row.signalPrice)) · 昨收 \(decimal(row.previousClose)) · 今收 \(decimal(row.currentClose)) · 行情 \(dailyTime(row.quoteAt))").foregroundStyle(Palette.muted)
                                            if let reason=row.reason { Text(reason).foregroundStyle(Palette.amber) }
                                            ChartLink(target:ChartTarget(code:row.tsCode,name:row.name,
                                                focus:ChartFocus(date:ChartDate.key(Date(timeIntervalSince1970:row.quoteAt)),price:row.signalPrice,label:String(realtimeDate(row.quoteAt).suffix(8))+" 提醒"),through:performance.evaluationDate)) {
                                                Label("查看K线与提醒价",systemImage:"chart.xyaxis.line").foregroundStyle(Palette.teal)
                                            }
                                        }.font(.system(size:11)).padding(.top,8)
                                    }
                                }.font(.caption)
                            }
                        } else { Text("未结算 · 候选数量未知").font(.caption).foregroundStyle(Palette.amber) }
                    }
                    if group.id != performance.strategies.last?.id { Divider() }
                }
                Text(performance.message).font(.caption).foregroundStyle(Palette.muted)
            } else { Text("旧版总结暂无实时策略结算。可重新核验并生成最近收盘日。").font(.caption).foregroundStyle(Palette.muted) }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func sectorPanel(_ title:String,rows:[DailySector])->some View {
        Panel { VStack(alignment:.leading,spacing:14) {
            Text(title).font(.headline)
            if rows.isEmpty { Text("行业资料暂不足").font(.caption).foregroundStyle(Palette.muted) }
            ForEach(rows) { row in HStack { Text(row.name);Spacer();Text("\(row.members) 只").foregroundStyle(Palette.muted);Text(dailyChange(row.meanChange)).monospacedDigit().foregroundStyle(row.meanChange>=0 ? Palette.up:Palette.down) }.font(.system(size:12)) }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func strategyPanel(_ strategy:DailyStrategyFacts)->some View {
        Panel { VStack(alignment:.leading,spacing:12) {
            HStack { Text(strategy.name).font(.headline);Spacer();Badge(text:"\(strategy.shortlistCount) 只精选") }
            Text("符合条件 \(strategy.confirmedCount) 只 · 等待 \(strategy.watchingCount) 只").font(.system(size:11)).foregroundStyle(Palette.muted)
            if strategy.marketFilterApplies==true && strategy.marketFilterPassed==false { Text("市场宽度未达到 \(percent(strategy.marketFilterThreshold ?? 0.4)) 门槛，暂停新候选。").font(.system(size:11)).foregroundStyle(Palette.amber) }
            if strategy.picks.isEmpty { Text("当日暂无符合全部条件的精选候选。").font(.system(size:12)).foregroundStyle(Palette.muted) }
            ForEach(strategy.picks) { stock in
                ChartLink(target:ChartTarget(code:stock.tsCode,name:stock.name,focus:report.map{ChartFocus(date:$0.date,price:stock.close,label:"本日新选")},through:report?.date)) {
                    HStack { Text(stock.name);Text(String(stock.tsCode.prefix(6))).foregroundStyle(Palette.muted);Spacer();Text(decimal(stock.close));Text(dailyChange(stock.change)).foregroundStyle(stock.change>=0 ? Palette.up:Palette.down);Image(systemName:"chart.xyaxis.line").foregroundStyle(Palette.teal) }.font(.system(size:12))
                }
            }
        } }
    }
}
