import SwiftUI

struct RealtimeScreen: View {
    @EnvironmentObject var store: MobileStore
    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Image(systemName: "clock.badge.checkmark").foregroundStyle(MobileTheme.teal)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("尾盘有提醒，判断有依据").font(.headline)
                            Text("14:30 初筛 · 14:45 复核 · 14:50 提醒").font(.caption).foregroundStyle(.secondary)
                        }
                    }.padding(.vertical, 5)
                    if let state = store.realtime {
                        LabeledContent("计算节点", value: state.running ? (state.executor == "mac" ? "Mac 正在计算" : "服务器正在接管") : (state.macOnline ? "Mac 在线 · 优先计算" : (state.serverOnline ? "服务器备用就绪" : "节点暂时离线")))
                            .font(.subheadline)
                        LabeledContent("自动运行", value: state.settings.enabled ? "已开启 · 仅交易日" : "已暂停")
                        LabeledContent("手机推送", value: state.settings.barkConfigured && state.settings.notificationEnabled ? "Bark 已配置" : "尚未启用 Bark")
                        if let latest = state.latest {
                            Text(latest.executionLabel).font(.subheadline.weight(.semibold))
                            Text(latest.message).font(.subheadline)
                            Text("最近检查 \(realtimeDate(latest.generatedAt)) · \(latest.executor == "mac" ? "Mac" : "服务器")")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    } else {
                        Text(store.realtimeMessage).font(.subheadline).foregroundStyle(.secondary)
                    }
                    Button { Task { await store.realtimeAction("scan") } } label: { Label("立即检查运行状态与行情", systemImage: "arrow.clockwise") }
                        .disabled(!store.connected || store.realtimeBusy)
                    if store.realtime != nil { Text(store.realtimeMessage).font(.caption).foregroundStyle(.secondary) }
                } footer: {
                    Text("到点由 Mac 或备用服务器筛选，完成后手机收到提醒，点击查看结果。手机无需保持 App 打开。")
                }
                Section("选股策略说明") {
                    ForEach(RealtimeStrategyGuide.all) { guide in
                        NavigationLink { RealtimeStrategyDetail(guide: guide) } label: {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(guide.title).font(.headline)
                                Text(guide.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }.padding(.vertical, 3)
                        }
                    }
                }
                Section("JEV · 买入判断") {
                    if let snapshot=store.realtime?.jevSnapshot {
                        if let review=snapshot.jev { JevReviewView(review:review) }
                        else { Text("启用后会自动分析实时与盘后精选；也可从历史轮次发起回看。").font(.caption) }
                        Button("分析本轮快照") { Task { await store.realtimeAction("jev",values:["slot":snapshot.slot]) } }.disabled(store.realtime?.settings.jevEnabled != true || store.realtimeBusy)
                    } else { Text("等待筛选轮次；历史分析可在原始结果中查看。").font(.caption) }
                }
                Section("历史轮次") {
                    DisclosureGroup("查看初筛、复核与最终结果") {
                        ForEach(store.realtimeHistory) { run in
                            Button { Task { await store.openRealtimeRun(run.slot) } } label: {
                                VStack(alignment:.leading,spacing:5) { Text(run.label);Text(run.runState=="waiting" ? "等待策略时段":run.message).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                            }.buttonStyle(.plain)
                        }
                        if store.realtimeHistory.isEmpty { Text("暂无已保存轮次").foregroundStyle(.secondary) }
                    }
                }
                Section("14:30 · 大单承接") {
                    if let report=store.realtime?.lastFlow,let flow=report.orderflow {
                        Text(dateText(report.date)+" · "+flow.message+(flow.complete ? " 命中\(flow.matchedCount)只，展示\(flow.candidates.count)只。":"")).font(.subheadline)
                        ForEach(flow.candidates) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: {
                            HStack { Text(row.name);Spacer();Text(String(format:"净流入 %.1f%%",(row.flowNetRatio ?? 0)*100)) }
                        } }
                        if flow.complete && flow.candidates.isEmpty { Text("该轮检查完成，0只候选").foregroundStyle(.secondary) }
                    } else { Text("等待下一交易日14:30检查").foregroundStyle(.secondary) }
                }
                Section("14:30 · 底部放量2.5倍上涨") {
                    if let report=store.realtime?.lastBottom,let bottom=report.bottomVolume {
                        Text("\(dateText(report.date)) · 命中 \(bottom.matchedCount) 只，展示 \(bottom.candidates.count) 只").font(.subheadline)
                        Text(bottom.ruleLabel).font(.caption).foregroundStyle(.secondary)
                        ForEach(bottom.candidates) { candidate in NavigationLink { RealtimeCandidateDetail(candidate:candidate) } label: { HStack { Text(candidate.name);Spacer();Text(String(format:"%.2f 倍",candidate.volumeMultiple)).foregroundStyle(MobileTheme.teal) } } }
                        if bottom.candidates.isEmpty { Text("该轮已完成检查，0只候选").foregroundStyle(.secondary) }
                    } else { Text("尚无有效结果；下一交易日14:30检查，未记为0只。").foregroundStyle(.secondary) }
                }
                if let snapshot = store.realtime?.lastScreen,snapshot.complete {
                    Section("最近尾盘检查 · \(dateText(snapshot.date))") {
                        Text(snapshot.message).font(.subheadline)
                        HStack {
                            Text(snapshot.quoteCoverageLabel)
                            Spacer()
                            if let change = snapshot.indexChange { Text(String(format: "沪深300 %+.2f%%", change)) }
                        }.font(.caption).foregroundStyle(.secondary)
                        ForEach(snapshot.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(MobileTheme.amber) }
                    }
                    ForEach(["overnight", "golden"], id: \.self) { strategy in
                        Section(realtimeStrategy(strategy)) {
                            let candidates = snapshot.strategies[strategy] ?? []
                            if candidates.isEmpty {
                                Text("本轮已完成筛选，0 只候选").foregroundStyle(.secondary)
                            }
                            ForEach(candidates) { candidate in
                                NavigationLink { RealtimeCandidateDetail(candidate: candidate) } label: {
                                    VStack(alignment: .leading, spacing: 7) {
                                        HStack {
                                            Text(candidate.name).font(.headline)
                                            Spacer()
                                            Text(String(format: "%.2f  %+.2f%%", candidate.price, candidate.change)).monospacedDigit().foregroundStyle(MobileTheme.up)
                                        }
                                        Text("\(candidate.tsCode) · \(candidate.state)").font(.caption).foregroundStyle(.secondary)
                                        Text("行情 \(realtimeDate(candidate.quoteAt))").font(.caption2).foregroundStyle(.secondary)
                                    }.padding(.vertical, 3)
                                }
                            }
                        }
                    }
                    if let ai = snapshot.ai {
                        Section("DeepSeek · 可选解读") {
                            Text(ai.summary)
                            ForEach(ai.risks, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                            Text("AI 仅解释已计算的规则，未核查全部新闻，不改变筛选结果。").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                } else { Section { Text("尚无完整筛选结果。等待策略时段与数据核验完成后，再展示候选数量。").foregroundStyle(.secondary) } }
                if let reviews = store.realtime?.latest?.reviews, !reviews.isEmpty {
                    Section("昨日候选 · 早盘复查") {
                        ForEach(reviews) { row in
                            VStack(alignment: .leading, spacing: 5) {
                                Text("\(row.name)  \(String(format: "%+.2f%%", row.change))").font(.headline)
                                Text("\(row.note) · 参考价 \(String(format: "%.2f", row.referencePrice))").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section {
                    if store.realtime?.events.isEmpty != false { Text("首次运行后，提醒会保存在这里").foregroundStyle(.secondary) }
                    ForEach(store.realtime?.events ?? []) { event in
                        Button { Task { await store.openReminder(event) } } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(event.title).font(.headline)
                            Text(event.body).font(.subheadline)
                            Text("\(realtimeDate(event.createdAt)) · \(event.deliveryLabel)").font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 4)
                        }.buttonStyle(.plain)
                    }
                } header: { Text("提醒记录") } footer: { Text("Bark 接受请求不等于手机已经展示通知；请用设置中的测试按钮验证。") }
            }
            .navigationTitle("实时提醒")
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
                    ForEach(report.warnings,id:\.self) { Text($0).font(.caption).foregroundStyle(MobileTheme.amber) }
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
                                ForEach(rows) { row in NavigationLink { RealtimeCandidateDetail(candidate:row) } label: { HStack { Text(row.name);Spacer();Text(String(format:"%.2f  %+.2f%%",row.price,row.change)).monospacedDigit() } } }
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
                Text(String(format: "%.2f  %+.2f%%", candidate.price, candidate.change)).font(.largeTitle).monospacedDigit()
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
