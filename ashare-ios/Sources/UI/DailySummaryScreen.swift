import SwiftUI

struct DailySummaryScreen:View {
    @EnvironmentObject var store:MobileStore
    @Environment(\.dismiss) private var dismiss
    @State private var date=""
    @State private var settings=false
    private var report:DailyReport? { date.isEmpty ? store.daily?.latest:(store.dailyDetail?.date==date ? store.dailyDetail:nil) }
    var body:some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading,spacing:16) {
                    ResearchCard {
                        VStack(alignment:.leading,spacing:12) {
                            HStack { StatePill(text:store.daily?.settings.enabled==true ? "自动总结已开启":"自动总结已暂停");Spacer();if store.dailyBusy { ProgressView() } }
                            if store.daily?.schedulerOnline==false { Text("后台调度暂未连接，已有总结仍可阅读。").font(.caption).foregroundStyle(MobileTheme.amber) }
                            Text(store.dailyMessage).font(.subheadline).foregroundStyle(.secondary)
                            Text("北京时间交易日 16:10 起核验行情 · 下次 \(dailyTime(store.daily?.status.nextRunAt))").font(.caption).foregroundStyle(.secondary)
                            Picker("交易日",selection:$date) {
                                Text("最新总结").tag("")
                                ForEach(store.daily?.history ?? []) { row in Text(dateText(row.date)).tag(row.date) }
                            }.disabled(store.dailyBusy)
                        }
                    }
                    if let report {
                        VStack(alignment:.leading,spacing:8) {
                            Text(dateText(report.date)+" 收盘").font(.caption).foregroundStyle(.secondary)
                            Text(report.analysis.headline).font(.title2.weight(.semibold))
                        }.padding(.horizontal,4)
                        if let changes=report.evidence.marketChanges { changesCard(changes) }
                        performanceCard(report.evidence.performance)
                        realtimePerformanceCard(report.evidence.realtimePerformance)
                        analysisCard(report.analysis,showStrategy:report.evidence.performance != nil)
                        if let changes=report.evidence.selectionChanges { selectionCard(changes) }
                        DisclosureGroup("收盘量价与行业明细") {
                        marketCard(report.evidence)
                        sectorsCard("相对较强行业",report.evidence.sectorsStrong)
                        sectorsCard("相对较弱行业",report.evidence.sectorsWeak)
                        }.padding(.horizontal,4)
                        DisclosureGroup("本日新选 · 留待下一交易日评价") {
                        ForEach(report.evidence.strategies) { strategy in strategyCard(strategy) }
                        }.padding(.horizontal,4)
                        ForEach(report.evidence.warnings,id:\.self) { Text($0).font(.caption).foregroundStyle(MobileTheme.amber) }
                        Text("生成于 \(dailyTime(report.generatedAt))。数据来自已核验的收盘行情；行业为成分股等权均值，非行业指数。AI 只作量价解读，未核验新闻或财务，不改变候选。")
                            .font(.caption).foregroundStyle(.secondary).lineSpacing(4).padding(.horizontal,4)
                    } else {
                        EmptyMessage(title:"等待收盘后的完整总结",text:"核对当日行情与四策略结果后，再生成复盘。可在右上角设置中更换 DeepSeek API Key。",icon:"sun.horizon")
                    }
                    Button { Task { await store.dailyAction("generate",values:["refresh_facts":true]) } } label: {
                        Label("重新核验并生成",systemImage:"arrow.clockwise").frame(maxWidth:.infinity,minHeight:32)
                    }.buttonStyle(.bordered).disabled(store.dailyBusy || !store.connected)
                }.padding(16)
            }.background(MobileTheme.background).navigationTitle("收盘总结")
                .toolbar {
                    ToolbarItem(placement:.cancellationAction) { Button("完成") { dismiss() } }
                    ToolbarItem(placement:.primaryAction) { Button("设置",systemImage:"gearshape") { settings=true }.disabled(store.daily==nil) }
                }
                .refreshable { await store.refreshDaily();if !date.isEmpty { await store.loadDailyReport(date) } }
                .sheet(isPresented:$settings) { DailySummarySettings().environmentObject(store) }
        }
        .task(id:store.dailyRequestedDate) { await store.refreshDaily();date=store.dailyRequestedDate ?? "" }
        .onChange(of:date) { _,value in if !value.isEmpty { Task { await store.loadDailyReport(value) } } }
    }
    private func marketCard(_ evidence:DailyEvidence)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:18) {
            Text("\(evidence.market.stockCount.formatted()) 只沪深股票").font(.headline)
            HStack { Metric(label:"上涨",value:evidence.market.advancers.formatted(),color:MobileTheme.change(1));Metric(label:"下跌",value:evidence.market.decliners.formatted(),color:MobileTheme.change(-1));Metric(label:"成交额 / 亿",value:decimal(evidence.market.turnoverYi)) }
            HStack { Metric(label:"收盘涨停",value:String(evidence.market.limitUp));Metric(label:"收盘跌停",value:String(evidence.market.limitDown));Metric(label:"策略池宽度",value:percent(evidence.market.breadth),color:MobileTheme.teal) }
            Text("平盘 \(evidence.market.unchanged) 只 · 涨跌中位数 \(dailyChange(evidence.market.medianChange))").font(.caption).foregroundStyle(.secondary)
            Text(evidence.universeLabel).font(.caption2).foregroundStyle(.secondary)
        } }
    }
    private func changesCard(_ changes:DailyMarketChanges)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:14) {
            Text("相对 \(dateText(changes.previousDate)) 的变化").font(.headline)
            HStack { Metric(label:"成交额变化",value:dailyChange(changes.turnoverChangePct));Metric(label:"上涨家数变化",value:String(format:"%+d",changes.advancersChange)) }
            Text(String(format:"市场宽度变化 %+.2f 个百分点",changes.breadthChangePp)).font(.subheadline)
            if !changes.enteredStrong.isEmpty { Text("进入行业涨幅前五："+changes.enteredStrong.joined(separator:"、")).font(.caption) }
            Text("比较两个交易日的已核验横截面，不代表连续趋势。").font(.caption).foregroundStyle(.secondary)
        } }
    }
    private func selectionCard(_ changes:[DailySelectionChange])->some View {
        ResearchCard { VStack(alignment:.leading,spacing:16) {
            Text("名单变化与条件复核").font(.headline)
            ForEach(changes) { group in
                VStack(alignment:.leading,spacing:8) {
                    Text(group.name).font(.subheadline.weight(.semibold))
                    if group.status=="unavailable" { Text("缺少此前精选，暂不比较名单。").font(.caption).foregroundStyle(.secondary) }
                    else {
                        Text(group.status=="new_strategy" ? "新启用策略 · 首次记录 \(group.added.count) 只":"新增 \(group.added.count) · 连续两期入选 \(group.retained.count) · 移出 \(group.removed.count)").font(.caption).foregroundStyle(.secondary)
                        if !group.retained.isEmpty { Text("连续入选："+group.retained.map(\.name).joined(separator:"、")).font(.caption) }
                        DisclosureGroup("查看变动依据") {
                            if !group.added.isEmpty { Text("本期新选："+group.added.map(\.name).joined(separator:"、")).font(.caption).padding(.top,6) }
                            ForEach(group.removed) { row in Text(row.name+" · "+(row.reason ?? "本期未进入精选")).font(.caption).foregroundStyle(.secondary).padding(.top,6) }
                        }.font(.caption)
                    }
                }
            }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func performanceCard(_ performance:DailyPerformance?)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:16) {
            Text("昨日精选 · 今日结算").font(.headline)
            if let performance {
                Text("\(dateText(performance.signalDate ?? "—")) 精选 → \(dateText(performance.evaluationDate)) 收盘").font(.caption).foregroundStyle(.secondary)
                Text(performance.message ?? "等权观察口径，未计交易费用及成交约束。").font(.caption).foregroundStyle(.secondary)
                ForEach(performance.strategies) { group in
                    VStack(alignment:.leading,spacing:10) {
                        HStack { Text(group.name).font(.subheadline.weight(.semibold));Spacer();Text(group.meanReturnPct.map(dailyChange) ?? "—").monospacedDigit().foregroundStyle(MobileTheme.change(group.meanReturnPct ?? 0)) }
                        if !AfterCloseStrategies.ids.contains(group.id) { Text("此前策略 · 保留历史结算").font(.caption2).foregroundStyle(MobileTheme.amber) }
                        Text("昨日 \(group.selectedCount) 只 · 结算 \(group.settledCount) 只\n上涨 \(group.upCount) / 下跌 \(group.downCount) / 平盘 \(group.flatCount)").font(.caption).foregroundStyle(.secondary)
                        if group.status=="partial" { Text("存在未结算股票，整体均值暂不展示。").font(.caption).foregroundStyle(MobileTheme.amber) }
                        if group.status=="unavailable" { Text("上一交易日该策略数据未完成，未结算。") }
                        if group.status=="no_picks" { Text("上一交易日没有精选。").font(.caption).foregroundStyle(.secondary) }
                        DisclosureGroup("逐股结算") {
                            ForEach(group.rows) { row in
                                NavigationLink {
                                    MobileChartScreen(target:ChartTarget(code:row.tsCode,name:row.name,focus:performance.signalDate.map{ChartFocus(date:$0,price:row.previousClose,label:"昨日精选")},through:performance.evaluationDate))
                                } label: {
                                    VStack(alignment:.leading,spacing:4) { HStack { Text(row.name);Spacer();Text(row.returnPct.map(dailyChange) ?? "未结算");Image(systemName:"chart.xyaxis.line") };Text(row.reason ?? String(row.tsCode.prefix(6))).font(.caption2).foregroundStyle(.secondary) }.font(.caption).padding(.top,6)
                                }
                            }
                        }.font(.caption)
                    }.padding(.vertical,4)
                }
                if !(performance.newStrategyIds ?? []).isEmpty { Text("新策略尚无昨日精选，下个交易日起才能结算。").font(.caption).foregroundStyle(.secondary) }
            } else { Text("旧版总结尚未包含昨日精选结算。可重新核验并生成最近收盘日。").font(.caption).foregroundStyle(.secondary) }
        } }
    }
    private func analysisCard(_ analysis:DailyAnalysis,showStrategy:Bool)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:16) {
            Label(analysis.status=="ready" ? "DeepSeek 量价解读":"量价摘要",systemImage:"text.alignleft").font(.headline)
            if analysis.status=="pending" { ProgressView("正在生成分析…") }
            paragraph("市场",analysis.marketView);paragraph("行业",analysis.sectorView)
            if showStrategy { paragraph("昨日策略结算",analysis.strategyView) };paragraph("下一交易日",analysis.watchNext)
            ForEach(analysis.risks,id:\.self) { Text("· "+$0).font(.caption).foregroundStyle(MobileTheme.amber).lineSpacing(4) }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    private func realtimePerformanceCard(_ performance:DailyRealtimePerformance?)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:16) {
            Text("昨日实时提醒 · 今日收益").font(.headline)
            if let performance {
                Text("\(dateText(performance.signalDate ?? "—")) 候选 → \(dateText(performance.evaluationDate)) 收盘").font(.caption).foregroundStyle(.secondary)
                ForEach(performance.strategies) { group in
                    VStack(alignment:.leading,spacing:10) {
                        Text(group.name).font(.subheadline.weight(.semibold))
                        Text(group.message).font(.caption2).foregroundStyle(.secondary)
                        if let selected=group.selectedCount {
                            HStack {
                                Metric(label:"今日等权涨跌",value:group.meanReturnPct.map(dailyChange) ?? "—",color:group.meanReturnPct.map(MobileTheme.change) ?? .secondary)
                                Metric(label:"提醒价至今收",value:group.meanSignalReturnPct.map(dailyChange) ?? "—",color:group.meanSignalReturnPct.map(MobileTheme.change) ?? .secondary)
                            }
                            Text("候选 \(selected) · 已结算 \(group.settledCount) · 涨 \(group.upCount) / 跌 \(group.downCount) / 平 \(group.flatCount)").font(.caption2).foregroundStyle(.secondary)
                            if group.status=="no_picks" { Text("昨日该轮次无候选，暂无收益样本。").font(.caption).foregroundStyle(.secondary) }
                            if group.status=="partial" { Text("存在未结算股票，两个整体均值均暂不展示。").font(.caption).foregroundStyle(MobileTheme.amber) }
                            if !group.rows.isEmpty {
                                DisclosureGroup("逐股收益与价格") {
                                    ForEach(group.rows) { row in
                                        VStack(alignment:.leading,spacing:5) {
                                            HStack { Text(row.name);Text(String(row.tsCode.prefix(6))).foregroundStyle(.secondary);Spacer();Text(row.returnPct.map(dailyChange) ?? "未结算").foregroundStyle(row.returnPct.map(MobileTheme.change) ?? .secondary) }
                                            Text("提醒价 \(decimal(row.signalPrice)) · 昨收 \(decimal(row.previousClose)) · 今收 \(decimal(row.currentClose))").font(.caption2).foregroundStyle(.secondary)
                                            Text("提醒价至今收 \(row.signalReturnPct.map(dailyChange) ?? "—") · 行情 \(dailyTime(row.quoteAt))").font(.caption2).foregroundStyle(.secondary)
                                            if let reason=row.reason { Text(reason).font(.caption2).foregroundStyle(MobileTheme.amber) }
                                            NavigationLink {
                                                MobileChartScreen(target:ChartTarget(code:row.tsCode,name:row.name,
                                                    focus:ChartFocus(date:ChartDate.key(Date(timeIntervalSince1970:row.quoteAt)),price:row.signalPrice,label:String(realtimeDate(row.quoteAt).suffix(8))+" 提醒"),through:performance.evaluationDate))
                                            } label: { Label("查看K线与提醒价",systemImage:"chart.xyaxis.line").font(.caption2) }
                                        }.font(.caption).padding(.top,8)
                                    }
                                }.font(.caption)
                            }
                        } else { Text("未结算 · 候选数量未知").font(.caption).foregroundStyle(MobileTheme.amber) }
                    }
                    if group.id != performance.strategies.last?.id { Divider() }
                }
                Text(performance.message).font(.caption2).foregroundStyle(.secondary)
            } else { Text("旧版总结暂无实时策略结算。可重新核验并生成最近收盘日。").font(.caption).foregroundStyle(.secondary) }
        }.frame(maxWidth:.infinity,alignment:.leading) }
    }
    @ViewBuilder private func paragraph(_ title:String,_ text:String)->some View {
        if !text.isEmpty { VStack(alignment:.leading,spacing:6) { Text(title).font(.subheadline.weight(.semibold));Text(text).font(.subheadline).lineSpacing(5).textSelection(.enabled) } }
    }
    private func sectorsCard(_ title:String,_ rows:[DailySector])->some View {
        ResearchCard { VStack(alignment:.leading,spacing:14) {
            Text(title).font(.headline)
            if rows.isEmpty { Text("行业资料暂不足").font(.subheadline).foregroundStyle(.secondary) }
            ForEach(rows) { row in HStack { Text(row.name);Spacer();Text("\(row.members) 只").font(.caption).foregroundStyle(.secondary);Text(dailyChange(row.meanChange)).monospacedDigit().foregroundStyle(MobileTheme.change(row.meanChange)) }.font(.subheadline) }
        } }
    }
    private func strategyCard(_ strategy:DailyStrategyFacts)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:12) {
            HStack { Text(strategy.name).font(.headline);Spacer();StatePill(text:"\(strategy.shortlistCount) 只精选") }
            Text(strategy.dataStatus=="incomplete" ? (strategy.dataMessage ?? "本策略数据未完成") : "符合条件 \(strategy.confirmedCount) 只 · 等待 \(strategy.watchingCount) 只").font(.caption).foregroundStyle(.secondary)
            if strategy.marketFilterApplies==true && strategy.marketFilterPassed==false { Text("市场宽度未达到 \(percent(strategy.marketFilterThreshold ?? 0.4)) 门槛，暂停新候选。").font(.caption).foregroundStyle(MobileTheme.amber) }
            if strategy.picks.isEmpty { Text("当日暂无符合全部条件的精选候选。").font(.subheadline).foregroundStyle(.secondary) }
            ForEach(strategy.picks) { row in
                NavigationLink {
                    MobileChartScreen(target:ChartTarget(code:row.tsCode,name:row.name,focus:report.map{ChartFocus(date:$0.date,price:row.close,label:"本日新选")},through:report?.date))
                } label: {
                    HStack { VStack(alignment:.leading,spacing:4) { Text(row.name);Text(String(row.tsCode.prefix(6))).font(.caption).foregroundStyle(.secondary) };Spacer();Text(decimal(row.close)).monospacedDigit();Text(dailyChange(row.change)).monospacedDigit().foregroundStyle(MobileTheme.change(row.change));Image(systemName:"chart.xyaxis.line") }.font(.subheadline)
                }
            }
        } }
    }
}

struct DailySummarySettings:View {
    @EnvironmentObject var store:MobileStore
    @Environment(\.dismiss) private var dismiss
    @State private var enabled=false
    @State private var notifications=true
    @State private var ai=true
    @State private var model="deepseek-v4-flash"
    @State private var key=""
    var body:some View {
        NavigationStack {
            Form {
                Section("每日收盘") {
                    Toggle("收盘后自动生成",isOn:$enabled)
                    Toggle("完成后手机提醒",isOn:$notifications)
                    Text("交易日 16:10 起检查。行情未齐稍后重试，Mac 优先更新与选股，离线时服务器接管。").font(.caption).foregroundStyle(.secondary)
                }
                Section("DeepSeek") {
                    Toggle("使用 AI 量价分析",isOn:$ai)
                    Picker("模型",selection:$model) { Text("V4 Flash").tag("deepseek-v4-flash");Text("V4 Pro").tag("deepseek-v4-pro") }
                    SecureField(store.daily?.settings.deepseekConfigured==true ? "已配置 · 输入新 API Key 可替换":"DeepSeek API Key",text:$key)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("与实时解读共用 Key 和模型。留空保留原 Key，保存后用于后续分析。只发送公开量价及候选摘要，调用费用由 DeepSeek 账户承担。").font(.caption).foregroundStyle(.secondary)
                }
                Section {
                    Button("用当前设置重做最新总结的 AI") { Task { if await store.dailyAction("generate",values:["retry_ai":true]) { dismiss() } } }.disabled(store.dailyBusy)
                    Text(store.dailyMessage).font(.caption).foregroundStyle(.secondary)
                }
            }.navigationTitle("总结设置")
                .toolbar {
                    ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement:.confirmationAction) {
                        Button("保存") { Task {
                            var values:[String:Any]=["enabled":enabled,"notification_enabled":notifications,"ai_enabled":ai,"model":model]
                            let secret=key.trimmingCharacters(in:.whitespacesAndNewlines)
                            if !secret.isEmpty { values["deepseek_key"]=secret }
                            if await store.dailyAction("settings",values:values) { key="";dismiss() }
                        } }.disabled(store.dailyBusy)
                    }
                }
        }.onAppear { if let value=store.daily?.settings { enabled=value.enabled;notifications=value.notificationEnabled;ai=value.aiEnabled;model=value.model } }
    }
}
