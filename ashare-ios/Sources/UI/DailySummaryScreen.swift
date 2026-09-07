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
                        marketCard(report.evidence)
                        analysisCard(report.analysis)
                        sectorsCard("相对较强行业",report.evidence.sectorsStrong)
                        sectorsCard("相对较弱行业",report.evidence.sectorsWeak)
                        ForEach(report.evidence.strategies) { strategy in strategyCard(strategy) }
                        ForEach(report.evidence.warnings,id:\.self) { Text($0).font(.caption).foregroundStyle(MobileTheme.amber) }
                        Text("生成于 \(dailyTime(report.generatedAt))。数据来自已核验的 ProMax 收盘行情；行业为成分股等权均值，非行业指数。AI 只作量价解读，未核验新闻或财务，不改变候选。")
                            .font(.caption).foregroundStyle(.secondary).lineSpacing(4).padding(.horizontal,4)
                    } else {
                        EmptyMessage(title:"等待收盘后的完整总结",text:"核对当日行情与四策略结果后，再生成复盘。可在右上角设置中更换 DeepSeek API Key。",icon:"sun.horizon")
                    }
                    Button { Task { await store.dailyAction("generate") } } label: {
                        Label("补生成最近收盘日",systemImage:"arrow.clockwise").frame(maxWidth:.infinity,minHeight:32)
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
    private func analysisCard(_ analysis:DailyAnalysis)->some View {
        ResearchCard { VStack(alignment:.leading,spacing:16) {
            Label(analysis.status=="ready" ? "DeepSeek 量价解读":"量价摘要",systemImage:"text.alignleft").font(.headline)
            if analysis.status=="pending" { ProgressView("正在生成分析…") }
            paragraph("市场",analysis.marketView);paragraph("行业",analysis.sectorView)
            paragraph("策略",analysis.strategyView);paragraph("下一交易日",analysis.watchNext)
            ForEach(analysis.risks,id:\.self) { Text("· "+$0).font(.caption).foregroundStyle(MobileTheme.amber).lineSpacing(4) }
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
            Text("符合条件 \(strategy.confirmedCount) 只 · 等待 \(strategy.watchingCount) 只").font(.caption).foregroundStyle(.secondary)
            if strategy.marketFilterApplies==true && strategy.marketFilterPassed==false { Text("市场宽度未达到 40% 门槛，暂停新候选。").font(.caption).foregroundStyle(MobileTheme.amber) }
            if strategy.picks.isEmpty { Text("当日暂无符合全部条件的精选候选。").font(.subheadline).foregroundStyle(.secondary) }
            ForEach(strategy.picks) { row in HStack { VStack(alignment:.leading,spacing:4) { Text(row.name);Text(String(row.tsCode.prefix(6))).font(.caption).foregroundStyle(.secondary) };Spacer();Text(decimal(row.close)).monospacedDigit();Text(dailyChange(row.change)).monospacedDigit().foregroundStyle(MobileTheme.change(row.change)) }.font(.subheadline) }
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
