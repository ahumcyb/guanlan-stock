import SwiftUI

struct RealtimeScreen: View {
    @EnvironmentObject var store: MobileStore
    var body: some View {
        NavigationStack {
            List {
                // 1. 今日结果放最前：打开 App 首先看到候选。
                if let snapshot = store.realtime?.lastScreen, snapshot.complete {
                    Section {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(snapshot.message).font(.subheadline.weight(.medium))
                            HStack(spacing: 6) {
                                Text("\(realtimeSlot(snapshot.slot)) · \(realtimeDate(snapshot.generatedAt))")
                                if let change = snapshot.indexChange { Text("·");Text(String(format: "沪深300 %+.2f%%", change)).foregroundStyle(MobileTheme.change(change)) }
                            }.font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }.padding(.vertical, 2)
                        let notes = RealtimeWording.notable(snapshot.warnings)
                        if !snapshot.warnings.isEmpty {
                            DisclosureGroup {
                                Text(snapshot.quoteCoverageLabel).font(.caption).foregroundStyle(.secondary)
                                ForEach(snapshot.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    if notes.isEmpty { Label("数据正常", systemImage: "checkmark.circle").foregroundStyle(MobileTheme.teal) }
                                    ForEach(notes, id: \.self) { Label($0, systemImage: "exclamationmark.circle").foregroundStyle(MobileTheme.amber) }
                                }.font(.caption)
                            }
                        }
                    } header: { Text("今日尾盘结果 · \(dateText(snapshot.date))") }
                    ForEach(["overnight", "golden"], id: \.self) { strategy in
                        let candidates = snapshot.strategies[strategy] ?? []
                        Section {
                            if candidates.isEmpty { Text("本轮 0 只候选").font(.subheadline).foregroundStyle(.secondary) }
                            ForEach(candidates) { candidate in
                                NavigationLink { RealtimeCandidateDetail(candidate: candidate) } label: { RealtimeCandidateRow(candidate: candidate) }
                            }
                        } header: { HStack { Text(realtimeStrategy(strategy));Spacer();Text("\(candidates.count) 只") } }
                    }
                    if let ai = snapshot.ai {
                        Section("DeepSeek · 可选解读") { RealtimeAIText(ai: ai) }
                    }
                } else {
                    Section("今日尾盘结果") { Text("尚无完整筛选结果。交易日 14:30 起检查，数据核验完成后显示候选。").font(.subheadline).foregroundStyle(.secondary) }
                }
                // 2. 14:30 的两项观察。
                Section {
                    if let report=store.realtime?.lastBottom,let bottom=report.bottomVolume {
                        Text("\(dateText(report.date)) · 命中 \(bottom.matchedCount) 只 · \(bottom.ruleLabel)").font(.caption).foregroundStyle(.secondary)
                        ForEach(bottom.candidates) { candidate in NavigationLink { RealtimeCandidateDetail(candidate:candidate) } label: { RealtimeCandidateRow(candidate:candidate,trailing:String(format:"%.2f 倍",candidate.volumeMultiple)) } }
                        if bottom.candidates.isEmpty { Text("该轮 0 只候选").foregroundStyle(.secondary) }
                    } else { Text("等待下一交易日 14:30 检查").foregroundStyle(.secondary) }
                } header: { Text("14:30 · 底部放量") }
                Section {
                    if let report=store.realtime?.lastFlow,let flow=report.orderflow {
                        Text(dateText(report.date)+" · "+(flow.complete ? "命中 \(flow.matchedCount) 只":flow.message)).font(.caption).foregroundStyle(.secondary)
                        ForEach(flow.candidates) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: { RealtimeCandidateRow(candidate:row,trailing:String(format:"%.1f%%",(row.flowNetRatio ?? 0)*100)) } }
                        if flow.complete && flow.candidates.isEmpty { Text("该轮 0 只候选").foregroundStyle(.secondary) }
                    } else { Text("等待下一交易日 14:30 检查").foregroundStyle(.secondary) }
                } header: { Text("14:30 · 大单承接") } footer: { if store.realtime?.lastFlow?.orderflow?.candidates.isEmpty == false { Text("右侧数字为大单净流入占成交额比例。") } }
                if let reviews = store.realtime?.latest?.reviews, !reviews.isEmpty {
                    Section("昨日候选 · 早盘复查") {
                        ForEach(reviews) { row in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) { Text(row.name).font(.body.weight(.medium));Text("\(row.note) · 参考价 \(String(format: "%.2f", row.referencePrice))").font(.caption).foregroundStyle(.secondary) }
                                Spacer()
                                Text(String(format: "%+.2f%%", row.change)).font(.body.monospacedDigit()).foregroundStyle(MobileTheme.change(row.change))
                            }
                        }
                    }
                }
                Section("JEV · 买入判断") {
                    if let snapshot=store.realtime?.jevSnapshot {
                        if let review=snapshot.jev { JevReviewView(review:review) }
                        else { Text("启用后会自动分析实时与盘后精选；也可从历史轮次发起回看。").font(.caption).foregroundStyle(.secondary) }
                        Button { Task { await store.realtimeAction("jev",values:["slot":snapshot.slot]) } } label: { Label("分析本轮快照",systemImage:"sparkles") }
                            .disabled(store.realtime?.settings.jevEnabled != true || store.realtimeBusy)
                    } else { Text("等待筛选轮次；历史分析可在历史轮次中查看。").font(.caption).foregroundStyle(.secondary) }
                }
                // 3. 运行状态压成一行，详情放在设置里。
                Section {
                    if let state = store.realtime {
                        HStack(spacing: 10) {
                            Image(systemName: state.healthy ? "checkmark.circle.fill" : "exclamationmark.circle.fill").foregroundStyle(state.healthy ? MobileTheme.teal : MobileTheme.amber)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(state.statusLine).font(.subheadline)
                                if let latest = state.latest { Text("\(latest.executionLabel) · \(realtimeDate(latest.generatedAt))").font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                    } else { Text(store.realtimeMessage).font(.subheadline).foregroundStyle(.secondary) }
                    Button { Task { await store.realtimeAction("scan") } } label: { Label(store.realtimeBusy ? "正在检查…":"立即检查运行状态与行情", systemImage: "arrow.clockwise") }
                        .disabled(!store.connected || store.realtimeBusy)
                    NavigationLink { RealtimeGuideList() } label: { Label("策略说明", systemImage: "book") }
                    DisclosureGroup {
                        ForEach(store.realtimeHistory) { run in
                            Button { Task { await store.openRealtimeRun(run.slot) } } label: {
                                VStack(alignment:.leading,spacing:4) { Text(run.label).font(.subheadline);Text(run.runState=="waiting" ? "等待策略时段":RealtimeWording.eventBody(run.message)).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                            }.buttonStyle(.plain)
                        }
                        if store.realtimeHistory.isEmpty { Text("暂无已保存轮次").foregroundStyle(.secondary) }
                    } label: { Label("历史轮次", systemImage: "clock.arrow.circlepath") }
                } header: { Text("运行状态") } footer: {
                    Text("交易日 14:30 初筛、14:45 复核、14:50 提醒。Mac 优先计算，服务器备用；手机无需保持 App 打开。")
                }
                // 4. 提醒记录：只列最近几条，只在发送异常时显示推送状态。
                Section {
                    let events = store.realtime?.events ?? []
                    if events.isEmpty { Text("首次运行后，提醒会保存在这里").foregroundStyle(.secondary) }
                    ForEach(events.prefix(12)) { event in RealtimeEventRow(event: event) }
                    if events.count > 12 {
                        NavigationLink { RealtimeEventList() } label: { Text("查看全部 \(events.count) 条提醒").foregroundStyle(MobileTheme.teal) }
                    }
                } header: { Text("提醒记录") } footer: { Text("推送服务接受请求不等于手机已展示通知；可在设置中发送测试通知。") }
            }
            .navigationTitle("实时提醒")
            .toolbarTitleDisplayMode(.inlineLarge)
            .crispTopEdge()
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { store.realtimeSettingsPresented = true } label: { Image(systemName: "slider.horizontal.3").accessibilityLabel("实时提醒设置") } } }
            .refreshable { await store.refreshRealtime() }
            .task { await store.refreshRealtime();await store.refreshRealtimeHistory() }
            .sheet(isPresented: $store.realtimeSettingsPresented) { RealtimeSettingsScreen() }
            .sheet(isPresented:$store.realtimeDetailPresented,onDismiss:{store.closeRealtimeDetail()}) { RealtimeHistoryDetail() }
        }
        .id(store.realtimeNavigationRevision)
    }
}

struct RealtimeHistoryDetail:View {
    @EnvironmentObject var store:MobileStore
    var body:some View {
        NavigationStack {
            List {
                if let detail=store.realtimeEventDetail {
                    Section("通知原文") { Text(detail.event.title).font(.headline);Text(detail.event.body);Text(realtimeDate(detail.event.createdAt)).font(.caption).foregroundStyle(.secondary) }
                }
                Section { Text(store.realtimeDetailMessage).font(.subheadline).foregroundStyle(.secondary) }
                if let report=store.realtimeDetail {
                    Section("固定轮次 · \(dateText(report.date))") {
                        LabeledContent("检查轮次",value:realtimeSlot(report.slot))
                        LabeledContent("执行结果",value:report.executionLabel)
                        LabeledContent("完成时间",value:realtimeDate(report.generatedAt))
                        Text(report.message)
                    }
                    Section("JEV · 买入判断") {
                        if let review=report.jev { JevReviewView(review:review) }
                        Button("分析本轮快照") { Task { await store.realtimeAction("jev",values:["slot":report.slot]);await store.openRealtimeRun(report.slot) } }.disabled(!report.hasJevCandidates || store.realtime?.settings.jevEnabled != true || store.realtimeBusy)
                    }
                    if !report.warnings.isEmpty {
                        Section("数据说明") { ForEach(report.warnings,id:\.self) { raw in VStack(alignment:.leading,spacing:3) { Text(RealtimeWording.warning(raw)).font(.caption).foregroundStyle(MobileTheme.amber);if RealtimeWording.warning(raw) != raw { Text(raw).font(.caption2).foregroundStyle(.secondary) } } } }
                    }
                    if report.complete {
                        ForEach(["overnight","golden"],id:\.self) { strategy in
                            Section(realtimeStrategy(strategy)) {
                                if let change=report.changes?[strategy] {
                                    Text("较 \(realtimeSlot(change.previousSlot))：新增 \(change.added.count)、移出 \(change.removed.count)、保留 \(change.retainedCount)").font(.caption)
                                    if !change.added.isEmpty { Text("新增："+change.added.map(\.name).joined(separator:"、")).font(.caption) }
                                    if !change.removed.isEmpty { Text("移出："+change.removed.map(\.name).joined(separator:"、")).font(.caption).foregroundStyle(.secondary) }
                                }
                                let rows=report.strategies[strategy] ?? []
                                if rows.isEmpty { Text("本轮已完成筛选，0 只候选").foregroundStyle(.secondary) }
                                ForEach(rows) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: { HStack { Text(row.name);Spacer();Text(String(format:"%.2f  %+.2f%%",row.price,row.change)).monospacedDigit().foregroundStyle(MobileTheme.change(row.change)) } } }
                            }
                        }
                    }
                    if let flow=report.orderflow {
                        Section("14:30 · 大单承接") {
                            Text(flow.message)
                            ForEach(flow.candidates) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: { Text(row.name+" · "+String(format:"净流入 %.1f%%",(row.flowNetRatio ?? 0)*100)) } }
                        }
                    }
                    if let bottom=report.bottomVolume {
                        Section("14:30 · 底部放量") {
                            Text(bottom.ruleLabel).font(.caption).foregroundStyle(.secondary)
                            if bottom.complete {
                                Text("命中 \(bottom.matchedCount) 只，按放量倍数展示前 \(bottom.candidates.count) 只").font(.subheadline)
                                ForEach(bottom.candidates) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: { HStack { Text(row.name);Spacer();Text(String(format:"%.2f 倍",row.volumeMultiple)) } } }
                                if bottom.candidates.isEmpty { Text("该轮已完成，0只候选").foregroundStyle(.secondary) }
                            } else { Text(bottom.message).foregroundStyle(.secondary) }
                        }
                    }
                    if !report.reviews.isEmpty { Section("复查记录") { ForEach(report.reviews) { row in Text(row.name+" · "+row.note) } } }
                }
            }.navigationTitle("原始结果").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement:.topBarTrailing) { Button("完成") { store.closeRealtimeDetail() } } }
        }
    }
}

struct RealtimeStrategyDetail: View {
    let guide: RealtimeStrategyGuide
    var body: some View {
        List {
            Section {
                Text(guide.title).font(.title2.weight(.semibold))
                Text(guide.summary)
            }
            Section("执行时间") { Text(RealtimeStrategyGuide.schedule) }
            Section("筛选条件与口径") {
                ForEach(Array(guide.conditions.enumerated()), id: \.offset) { number, text in
                    HStack(alignment: .top, spacing: 12) {
                        Text(String(number + 1)).font(.headline.monospacedDigit()).foregroundStyle(MobileTheme.teal).frame(width: 20)
                        Text(text)
                    }.padding(.vertical, 4)
                }
            }
            Section("仍需复核") {
                ForEach(guide.review, id: \.self) { Text($0).foregroundStyle(MobileTheme.amber) }
            }
            Section("如何理解结果") { Text(guide.interpretation) }
            Section("股票与数据范围") { Text(RealtimeStrategyGuide.scope).font(.footnote) }
            Section("参考来源") { if let text=guide.sourceURL,let url=URL(string:text) { Link(guide.sourceName,destination:url) } else { Text(guide.sourceName) } }
        }
        .navigationTitle(realtimeStrategy(guide.id))
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct RealtimeCandidateDetail: View {
    let candidate: RealtimeCandidate
    var body: some View {
        List {
            Section {
                Text(String(format: "%.2f  %+.2f%%", candidate.price, candidate.change)).font(.largeTitle).monospacedDigit().foregroundStyle(MobileTheme.change(candidate.change))
                LabeledContent("代码", value: candidate.tsCode)
                OpenInTonghuashunButton(tsCode: candidate.tsCode)
                LabeledContent("状态", value: candidate.state)
                LabeledContent("行情时间", value: realtimeDate(candidate.quoteAt))
                NavigationLink {
                    MobileChartScreen(target:ChartTarget(code:candidate.tsCode,name:candidate.name,
                        focus:ChartFocus(date:ChartDate.key(Date(timeIntervalSince1970:candidate.quoteAt)),price:candidate.price,label:String(realtimeDate(candidate.quoteAt).suffix(8))+" 提醒"),through:nil))
                } label: { Label("查看K线并定位提醒",systemImage:"chart.xyaxis.line") }
                Text(candidate.timeBasis == "provider_updated_at" ? "时间依据为供应商更新时间，不是交易所逐笔时间。" : "时间依据为行情交易时间。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("可复算的指标") {
                LabeledContent("累计量 / 5日均量", value: String(format: "%.2f 倍", candidate.volumeMultiple))
                LabeledContent("按交易分钟计算量比", value: String(format: "%.2f", candidate.volumeRatio))
                LabeledContent("当日成交均价", value: String(format: "%.2f", candidate.vwap))
                if let low=candidate.low60,let distance=candidate.distanceLow60 {
                    LabeledContent("近60日最低价",value:decimal(low))
                    LabeledContent("距离低价",value:percent(distance))
                }
                if let turnover = candidate.turnover { LabeledContent("换手率（估算）", value: String(format: "%.2f%%", turnover)) }
                if let cap = candidate.marketCap { LabeledContent("流通市值（估算）", value: String(format: "%.1f 亿元", cap)) }
                LabeledContent("历史 / 股本参考日", value: dateText(candidate.referenceDate))
            }
            Section("已通过条件") { ForEach(candidate.checks, id: \.self) { Label($0, systemImage: "checkmark.circle").foregroundStyle(MobileTheme.teal) } }
            if let review=candidate.jev { Section("JEV · 买入判断") { JevStockView(review:review) } }
            Section("仍需核验") { ForEach(candidate.pending, id: \.self) { Label($0, systemImage: "exclamationmark.circle").foregroundStyle(MobileTheme.amber) } }
            Section { Text("这是规则匹配的研究候选。隔夜跳空或跌停可能无法按参考止损退出。软件不执行交易，也没有验证原文宣传的胜率。").font(.footnote).foregroundStyle(.secondary) }
        }.navigationTitle(candidate.name).navigationBarTitleDisplayMode(.inline)
    }
}

struct RealtimeSettingsScreen: View {
    @EnvironmentObject var store: MobileStore
    @Environment(\.dismiss) var dismiss
    @State private var enabled = true
    @State private var notifications = true
    @State private var ai = false
    @State private var model = "deepseek-v4-flash"
    @State private var bark = ""
    @State private var key = ""
    @State private var jevKey=""
    @State private var jevEnabled=false
    @State private var saved = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("交易日自动执行") {
                    Toggle("启用尾盘策略", isOn: $enabled)
                    Text("14:30 / 14:45 / 14:50。Mac 优先，离线后服务器备用；筛选完成再发送查看提醒。").font(.caption).foregroundStyle(.secondary)
                }
                Section("Bark 手机通知") {
                    Toggle("发送手机推送", isOn: $notifications)
                    SecureField(store.realtime?.settings.barkConfigured == true ? "已配置 · 输入新地址可替换" : "Bark 首页推送地址", text: $bark).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("保留免费安装方式。安装 Bark 并允许通知，把首页 https://api.day.app/ 开头的推送地址粘贴到这里。地址作为私密配置保存。点击通知可进入观澜。").font(.caption).foregroundStyle(.secondary)
                    Button("发送测试通知") { Task { await store.realtimeAction("test");saved = store.realtimeMessage } }
                        .disabled(store.realtime?.settings.barkConfigured != true || store.realtimeBusy)
                }
                Section("JEV · 买入判断") {
                    Toggle("分析实时与盘后精选",isOn:$jevEnabled)
                    SecureField(store.realtime?.settings.jevConfigured==true ? "JEV已配置 · 输入新Key替换":"TypeSafe JEV API Key",text:$jevKey).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("向TypeSafe发送实时与盘后精选的公开量价与规则条件，可能产生接口费用。提供可考虑买入、观望或暂不买的分类；置信度不是盈利概率。").font(.caption).foregroundStyle(.secondary)
                }
                Section("DeepSeek（可选）") {
                    Toggle("附加 AI 研究解读", isOn: $ai)
                    Picker("模型", selection: $model) { Text("V4 Flash").tag("deepseek-v4-flash");Text("V4 Pro").tag("deepseek-v4-pro") }
                    SecureField(store.realtime?.settings.deepseekConfigured == true ? "已配置 · 输入新 Key 可替换" : "DeepSeek API Key", text: $key).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("只向 DeepSeek 发送已筛选的公开量价和条件，可能产生 API 费用。AI 不决定入选，不联网代替公告核查；关闭后规则正常运行。").font(.caption).foregroundStyle(.secondary)
                }
                Section {
                    Button("保存设置") {
                        Task {
                            var values: [String: Any] = ["enabled": enabled, "notification_enabled": notifications, "ai_enabled": ai, "model": model]
                            values["jev_enabled"]=jevEnabled
                            if !jevKey.isEmpty { values["jev_key"]=jevKey.trimmingCharacters(in:.whitespacesAndNewlines) }
                            if !bark.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { values["bark_url"] = bark.trimmingCharacters(in: .whitespacesAndNewlines) }
                            if !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { values["deepseek_key"] = key.trimmingCharacters(in: .whitespacesAndNewlines) }
                            await store.realtimeAction("settings", values: values);bark = "";key = "";jevKey="";saved = store.realtimeMessage
                        }
                    }.disabled(store.realtimeBusy || !store.connected)
                    if !saved.isEmpty { Text(saved).font(.caption).foregroundStyle(.secondary) }
                }
            }.navigationTitle("实时提醒设置").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
                .onAppear { if let s = store.realtime?.settings { enabled = s.enabled;notifications = s.notificationEnabled;ai = s.aiEnabled;model = s.model;jevEnabled=s.jevEnabled ?? false } }
        }
    }
}

struct RealtimeEventRow:View {
    @EnvironmentObject var store:MobileStore
    let event:RealtimeEvent
    var body:some View {
        Button { Task { await store.openReminder(event) } } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(event.title.replacingOccurrences(of: "观澜 · ", with: "")).font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(realtimeDate(event.createdAt)).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
                Text(RealtimeWording.eventBody(event.body)).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                if event.status != "accepted" { Label(event.deliveryLabel, systemImage: "exclamationmark.triangle").font(.caption2).foregroundStyle(MobileTheme.amber) }
            }.padding(.vertical, 2).contentShape(Rectangle())
        }.buttonStyle(.plain)
    }
}

struct RealtimeEventList:View {
    @EnvironmentObject var store:MobileStore
    var body:some View {
        List { ForEach(store.realtime?.events ?? []) { RealtimeEventRow(event:$0) } }
            .navigationTitle("全部提醒").navigationBarTitleDisplayMode(.inline)
    }
}

/// AI 解读默认收起，避免长文把候选和 14:30 结果隔开。
struct RealtimeAIText:View {
    let ai:RealtimeAI
    @State private var expanded=false
    var body:some View {
        VStack(alignment:.leading,spacing:8) {
            Text(ai.summary).font(.subheadline).lineLimit(expanded ? nil:3)
            if expanded {
                ForEach(ai.risks,id:\.self) { Label($0,systemImage:"exclamationmark.circle").font(.caption).foregroundStyle(.secondary) }
                Text("AI 仅解释已计算的规则，未核查全部新闻，不改变筛选结果。").font(.caption2).foregroundStyle(.secondary)
            }
            Button(expanded ? "收起":"展开全文与风险提示") { withAnimation { expanded.toggle() } }.font(.caption).foregroundStyle(MobileTheme.teal)
        }.padding(.vertical,2)
    }
}
