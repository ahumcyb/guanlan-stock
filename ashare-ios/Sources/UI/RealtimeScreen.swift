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
                if let snapshot = store.realtime?.lastScreen {
                    Section("最近尾盘检查 · \(dateText(snapshot.date))") {
                        Text(snapshot.message).font(.subheadline)
                        HStack {
                            Text("新鲜行情 \(snapshot.freshCount ?? 0) / \(snapshot.universeCount ?? 0)")
                            Spacer()
                            if let change = snapshot.indexChange { Text(String(format: "沪深300 %+.2f%%", change)) }
                        }.font(.caption).foregroundStyle(.secondary)
                        ForEach(snapshot.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(MobileTheme.amber) }
                    }
                    ForEach(["overnight", "golden"], id: \.self) { strategy in
                        Section(realtimeStrategy(strategy)) {
                            let candidates = snapshot.strategies[strategy] ?? []
                            if candidates.isEmpty {
                                Text("本轮没有符合条件的候选").foregroundStyle(.secondary)
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
                }
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
                        VStack(alignment: .leading, spacing: 6) {
                            Text(event.title).font(.headline)
                            Text(event.body).font(.subheadline)
                            Text("\(realtimeDate(event.createdAt)) · \(event.deliveryLabel)").font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 4)
                    }
                } header: { Text("提醒记录") } footer: { Text("Bark 接受请求不等于手机已经展示通知；请用设置中的测试按钮验证。") }
            }
            .navigationTitle("实时提醒")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { store.realtimeSettingsPresented = true } label: { Image(systemName: "slider.horizontal.3").accessibilityLabel("实时提醒设置") } } }
            .refreshable { await store.refreshRealtime() }
            .task { await store.refreshRealtime() }
            .sheet(isPresented: $store.realtimeSettingsPresented) { RealtimeSettingsScreen() }
        }
        .id(store.realtimeNavigationRevision)
    }
}

struct RealtimeCandidateDetail: View {
    let candidate: RealtimeCandidate
    var body: some View {
        List {
            Section {
                Text(String(format: "%.2f  %+.2f%%", candidate.price, candidate.change)).font(.largeTitle).monospacedDigit()
                LabeledContent("代码", value: candidate.tsCode)
                LabeledContent("状态", value: candidate.state)
                LabeledContent("行情时间", value: realtimeDate(candidate.quoteAt))
                Text(candidate.timeBasis == "provider_updated_at" ? "时间依据为供应商更新时间，不是交易所逐笔时间。" : "时间依据为行情交易时间。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("可复算的指标") {
                LabeledContent("累计量 / 5日均量", value: String(format: "%.2f 倍", candidate.volumeMultiple))
                LabeledContent("按交易分钟计算量比", value: String(format: "%.2f", candidate.volumeRatio))
                LabeledContent("当日成交均价", value: String(format: "%.2f", candidate.vwap))
                if let turnover = candidate.turnover { LabeledContent("换手率（估算）", value: String(format: "%.2f%%", turnover)) }
                if let cap = candidate.marketCap { LabeledContent("流通市值（估算）", value: String(format: "%.1f 亿元", cap)) }
                LabeledContent("历史 / 股本参考日", value: dateText(candidate.referenceDate))
            }
            Section("已通过条件") { ForEach(candidate.checks, id: \.self) { Label($0, systemImage: "checkmark.circle").foregroundStyle(MobileTheme.teal) } }
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
                            if !bark.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { values["bark_url"] = bark.trimmingCharacters(in: .whitespacesAndNewlines) }
                            if !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { values["deepseek_key"] = key.trimmingCharacters(in: .whitespacesAndNewlines) }
                            await store.realtimeAction("settings", values: values);bark = "";key = "";saved = store.realtimeMessage
                        }
                    }.disabled(store.realtimeBusy || !store.connected)
                    if !saved.isEmpty { Text(saved).font(.caption).foregroundStyle(.secondary) }
                }
            }.navigationTitle("实时提醒设置").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
                .onAppear { if let s = store.realtime?.settings { enabled = s.enabled;notifications = s.notificationEnabled;ai = s.aiEnabled;model = s.model } }
        }
    }
}
