import SwiftUI
import Foundation

@MainActor final class RealtimeDesktopStore: ObservableObject {
    @Published var state: RealtimeState?
    @Published var busy = false
    @Published var message = "连接实时策略服务…"
    @Published var history:[RealtimeRunSummary]=[]
    @Published var detail:RealtimeSnapshot?
    @Published var eventDetail:RealtimeEventDetail?
    private var api:MobileAPI?
    func request(_ action:String,runtime:Runtime,values:[String:Any]=[:]) async {
        guard !busy else { return };busy=true;defer{busy=false}
        do {
            if api==nil {
                let file=URL(fileURLWithPath:runtime.projectRoot).appendingPathComponent("settings/mobile-viewer.json")
                api=try MobileAPI(JSONDecoder().decode(Pairing.self,from:Data(contentsOf:file)))
            }
            guard let api else { return }
            if action=="state" {
                let value=try mobileDecoder().decode(RealtimeState.self,from:await api.request("/v1/realtime",limit:2*1024*1024))
                guard value.schemaVersion==1 else { throw MobileFailure.invalidData };state=value
                let records=try mobileDecoder().decode(RealtimeHistory.self,from:await api.request("/v1/realtime/history",limit:128*1024))
                guard records.schemaVersion==1,records.runs.count<=90 else { throw MobileFailure.invalidData }
                history=records.runs;message="已同步实时状态与原始轮次"
            } else if action=="run",let slot=values["slot"] as? String,validRealtimeSlot(slot) {
                detail=nil
                let value=try mobileDecoder().decode(RealtimeSnapshot.self,from:await api.request("/v1/realtime/runs/"+slot,limit:256*1024))
                try value.validateArchive(slot);detail=value;message="已载入固定轮次"
            } else if action=="event",let id=values["id"] as? String,UUID(uuidString:id) != nil {
                eventDetail=nil
                let value=try mobileDecoder().decode(RealtimeEventDetail.self,from:await api.request("/v1/realtime/events/"+id,limit:256*1024))
                guard value.event.id==id else { throw MobileFailure.invalidData }
                guard value.report==nil || value.event.runId==value.report?.slot else { throw MobileFailure.invalidData }
                try value.report?.validateArchive(value.event.runId);eventDetail=value;message=value.message
            } else if ["settings","scan","test"].contains(action) {
                let body=try JSONSerialization.data(withJSONObject:values)
                _=try await api.request("/v1/realtime/"+action,method:"POST",body:body,limit:65536)
                message=action=="settings" ? "设置已保存":(action=="test" ? "测试通知已提交":"行情检查已提交，优先由 Mac 执行")
            } else { throw MobileFailure.invalidData }
        } catch { message="这次读取或操作未完成，已保留现有记录，请稍后重试。" }
    }
}

struct RealtimeView: View {
    @EnvironmentObject var app: AppStore
    @StateObject private var store = RealtimeDesktopStore()
    @State private var enabled = true
    @State private var notifications = true
    @State private var ai = false
    @State private var model = "deepseek-v4-flash"
    @State private var bark = ""
    @State private var deepseek = ""
    @State private var showSettings = false
    @State private var selectedSlot=""
    @State private var showEvent=false
    private var displayed:RealtimeSnapshot? { selectedSlot.isEmpty ? store.state?.lastScreen:(store.detail?.slot==selectedSlot ? store.detail:nil) }
    private var eventDailyDate:String? {
        guard let text=store.eventDetail?.event.url,let url=URL(string:text),let target=notificationTarget(url),case .daily(let date)=target else { return nil }
        return date
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("把尾盘留给判断").font(.system(size: 26, weight: .semibold))
                        Text("14:30 初筛   /   14:45 复核   /   14:50 提醒").font(.system(size: 12, design: .monospaced)).foregroundStyle(Palette.muted)
                    }
                    Spacer()
                    Button("检查行情") { Task { await store.request("scan", runtime: app.runtime) } }.disabled(store.busy)
                    Button("提醒设置") {
                        if let s = store.state?.settings { enabled = s.enabled;notifications = s.notificationEnabled;ai = s.aiEnabled;model = s.model }
                        showSettings.toggle()
                    }
                }
                HStack(spacing: 20) {
                    Label(store.state?.macOnline == true ? "Mac 在线，优先计算" : "Mac 离线时服务器接管", systemImage: "desktopcomputer")
                    Label(store.state?.settings.barkConfigured == true ? "Bark 已配置" : "等待配置 Bark", systemImage: "bell")
                    if store.state?.running == true { ProgressView().controlSize(.small);Text("正在计算") }
                    Spacer()
                    Text(store.state?.settings.enabled == true ? "自动运行已开启" : "自动运行已暂停")
                }.font(.system(size: 12)).foregroundStyle(Palette.teal)
                Text(store.message).font(.system(size: 11)).foregroundStyle(Palette.muted)
                DisclosureGroup("三套选股策略如何筛选") { RealtimeStrategyDescriptions().padding(.top, 12) }
                if showSettings { settings }
                if let latest = store.state?.latest {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(latest.executionLabel).font(.headline)
                            Text(latest.message).font(.system(size:12))
                            Text("最近检查 \(realtimeDate(latest.generatedAt)) · \(latest.executor == "mac" ? "Mac" : "服务器")")
                                .font(.caption).foregroundStyle(Palette.muted)
                            ForEach(latest.reviews) { r in
                                Text("\(r.name)  \(String(format: "%+.2f%%", r.change))   \(r.note) · 相对昨日筛选价")
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                    }
                }
                Picker("查看轮次",selection:$selectedSlot) {
                    Text("最近完整筛选").tag("")
                    ForEach(store.history) { run in Text(run.label).tag(run.slot) }
                }.frame(maxWidth:460).disabled(store.busy)
                if selectedSlot.isEmpty {
                    GroupBox("14:30 · 底部放量3倍") {
                        if let report=store.state?.lastBottom { bottomSection(report).padding(12) }
                        else { Text("下一交易日14:30开始检查。尚无这套策略的完整结果，未记为0只。").font(.system(size:12)).foregroundStyle(Palette.muted).frame(maxWidth:.infinity,alignment:.leading).padding(12) }
                    }
                }
                if let report = displayed {
                    HStack {
                        Text("\(dateText(report.date)) · \(realtimeSlot(report.slot)) · \(report.executionLabel)").font(.headline)
                        Spacer()
                        Text("新鲜行情 \(report.freshCount ?? 0) / \(report.universeCount ?? 0)").font(.caption).foregroundStyle(Palette.muted)
                    }
                    ForEach(report.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(Palette.amber) }
                    if report.complete { HStack(alignment: .top, spacing: 18) {
                        candidateColumn(report, "overnight")
                        candidateColumn(report, "golden")
                    } } else { Text(report.message).font(.system(size:13)).foregroundStyle(Palette.muted) }
                    if !selectedSlot.isEmpty,report.bottomVolume != nil { bottomSection(report) }
                    if let analysis = report.ai {
                        GroupBox("DeepSeek · 可选解读") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(analysis.summary)
                                ForEach(analysis.risks, id: \.self) { Text($0).font(.caption).foregroundStyle(Palette.muted) }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                        }
                    }
                } else {
                    Text(selectedSlot.isEmpty ? "尚无完整筛选结果。等待策略时段与数据核验完成后，再展示候选数量。":(store.busy ? "正在读取所选历史轮次…":"所选轮次暂不可读取，请稍后重试；未用最新结果替代。")).padding(28).frame(maxWidth: .infinity).background(Palette.selected, in: RoundedRectangle(cornerRadius: 12))
                }
                Text("提醒记录").font(.headline)
                ForEach(store.state?.events ?? []) { e in
                    Button { Task { await store.request("event",runtime:app.runtime,values:["id":e.id]);showEvent=true } } label: {
                    VStack(alignment: .leading, spacing: 7) {
                        HStack { Text(e.title).font(.headline);Spacer();Text(e.deliveryLabel).foregroundStyle(Palette.muted) }
                        Text(e.body).font(.system(size: 12))
                        Text(realtimeDate(e.createdAt)).font(.caption).foregroundStyle(Palette.muted)
                        Divider()
                    }
                    }.buttonStyle(.plain).disabled(store.busy)
                }
                Text("仅供研究。分时和公告未核验的条件会明确标示。筛选完成后手机收到查看提醒；Bark 已接受不等于手机已经展示通知。")
                    .font(.caption).foregroundStyle(Palette.muted)
            }.padding(28)
        }
        .task {
            while !Task.isCancelled {
                await store.request("state", runtime: app.runtime)
                do { try await Task.sleep(for: .seconds(15)) } catch { return }
            }
        }
        .onChange(of:selectedSlot) { _,slot in if !slot.isEmpty { Task { await store.request("run",runtime:app.runtime,values:["slot":slot]) } } }
        .sheet(isPresented:$showEvent) {
            VStack(alignment:.leading,spacing:16) {
                HStack { Text("通知对应的原始结果").font(.title2);Spacer();Button("完成") { showEvent=false } }
                if let date=eventDailyDate { DailySummaryView(initialDate:date).environmentObject(app) }
                else {
                ScrollView { VStack(alignment:.leading,spacing:16) {
                    if let detail=store.eventDetail {
                        Text(detail.event.title).font(.headline);Text(detail.event.body)
                        Text(realtimeDate(detail.event.createdAt)).font(.caption).foregroundStyle(Palette.muted)
                        Text(detail.message).font(.caption).foregroundStyle(Palette.muted)
                        if let report=detail.report {
                            Text("\(dateText(report.date)) · \(realtimeSlot(report.slot)) · \(report.executionLabel)").font(.headline)
                            if report.complete { HStack(alignment:.top,spacing:18) { candidateColumn(report,"overnight");candidateColumn(report,"golden") } }
                            else { Text(report.message) }
                            if report.bottomVolume != nil { bottomSection(report) }
                        }
                    } else { Text(store.message) }
                }.frame(maxWidth:.infinity,alignment:.leading) }
                }
            }.padding(24).frame(width:860,height:600)
        }
    }
    private func candidateColumn(_ report: RealtimeSnapshot, _ strategy: String) -> some View {
        let candidates=strategy=="bottom_volume" ? (report.bottomVolume?.candidates ?? []):report.strategies[strategy,default:[]]
        return VStack(alignment: .leading, spacing: 12) {
            Text(realtimeStrategy(strategy)).font(.headline)
            if let change=report.changes?[strategy] {
                Text("较 \(realtimeSlot(change.previousSlot))：新增 \(change.added.count)、移出 \(change.removed.count)、保留 \(change.retainedCount)").font(.caption).foregroundStyle(Palette.muted)
                if !change.added.isEmpty { Text("新增："+change.added.map(\.name).joined(separator:"、")).font(.caption) }
                if !change.removed.isEmpty { Text("移出："+change.removed.map(\.name).joined(separator:"、")).font(.caption).foregroundStyle(Palette.muted) }
            }
            if candidates.isEmpty { Text("本轮已完成筛选，0 只候选").foregroundStyle(Palette.muted).padding(.vertical, 16) }
            ForEach(candidates) { row in
                GroupBox {
                    VStack(alignment: .leading, spacing: 9) {
                        HStack { Text(row.name).font(.headline);Spacer();Text(String(format: "%.2f  %+.2f%%", row.price, row.change)).foregroundStyle(Palette.up).monospacedDigit() }
                        Text("\(row.tsCode) · \(row.state)").font(.caption).foregroundStyle(Palette.muted)
                        Text("行情 \(realtimeDate(row.quoteAt))\(row.timeBasis == "provider_updated_at" ? " · 供应商更新时间" : "")").font(.caption2).foregroundStyle(Palette.muted)
                        if let low=row.low60,let distance=row.distanceLow60 { Text("60日低价 \(decimal(low)) · 距低价 \(percent(distance)) · 放量 \(decimal(row.volumeMultiple)) 倍").font(.caption).foregroundStyle(Palette.teal) }
                        DisclosureGroup("查看指标与核验条件") {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(String(format: "累计量 / 5日均量 %.2f倍 · 量比 %.2f · 均价 %.2f", row.volumeMultiple, row.volumeRatio, row.vwap))
                                ForEach(row.checks, id: \.self) { Text("✓ " + $0).foregroundStyle(Palette.teal) }
                                ForEach(row.pending, id: \.self) { Text("待核验：" + $0).foregroundStyle(Palette.amber) }
                                Text("历史/股本参考日：\(dateText(row.referenceDate))").foregroundStyle(Palette.muted)
                            }.font(.caption).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                        }.font(.caption)
                    }.padding(6)
                }
            }
        }.frame(maxWidth: .infinity, alignment: .topLeading)
    }
    @ViewBuilder private func bottomSection(_ report:RealtimeSnapshot)->some View {
        if let bottom=report.bottomVolume {
            VStack(alignment:.leading,spacing:12) {
                Text("\(dateText(report.date)) · 14:30 原始结果").font(.headline)
                if bottom.complete {
                    Text("命中 \(bottom.matchedCount) 只 · 展示 \(bottom.candidates.count) 只 · 按放量倍数排序").font(.system(size:12)).foregroundStyle(Palette.muted)
                    candidateColumn(report,"bottom_volume")
                } else { Text(bottom.message).font(.system(size:12)).foregroundStyle(Palette.amber) }
            }.frame(maxWidth:.infinity,alignment:.leading)
        }
    }
    private var settings: some View {
        GroupBox("实时策略与私人通知") {
            VStack(alignment: .leading, spacing: 12) {
                HStack { Toggle("启用交易日定时策略", isOn: $enabled);Toggle("发送 Bark 手机通知", isOn: $notifications);Spacer() }
                SecureField(store.state?.settings.barkConfigured == true ? "Bark 已配置，输入新地址替换" : "Bark 首页 https://api.day.app/设备密钥", text: $bark)
                HStack { Toggle("附加 DeepSeek 解读", isOn: $ai);Picker("模型", selection: $model) { Text("V4 Flash").tag("deepseek-v4-flash");Text("V4 Pro").tag("deepseek-v4-pro") }.frame(width: 220);Spacer() }
                SecureField(store.state?.settings.deepseekConfigured == true ? "DeepSeek 已配置，输入新 Key 替换" : "DeepSeek API Key（可选）", text: $deepseek)
                Text("AI 只解释已筛选的公开量价与条件，可能产生 API 费用；不改变入选结果，也不代替公告核查。凭据通过配对 HTTPS 保存，不进入 Git。").font(.caption).foregroundStyle(Palette.muted)
                HStack {
                    Button("保存设置") {
                        Task {
                            var values: [String: Any] = ["enabled": enabled, "notification_enabled": notifications, "ai_enabled": ai, "model": model]
                            if !bark.isEmpty { values["bark_url"] = bark.trimmingCharacters(in: .whitespacesAndNewlines) }
                            if !deepseek.isEmpty { values["deepseek_key"] = deepseek.trimmingCharacters(in: .whitespacesAndNewlines) }
                            await store.request("settings", runtime: app.runtime, values: values);bark = "";deepseek = ""
                        }
                    }.buttonStyle(.borderedProminent)
                    Button("发送测试通知") { Task { await store.request("test", runtime: app.runtime) } }
                        .disabled(store.state?.settings.barkConfigured != true)
                }.disabled(store.busy)
            }.padding(12)
        }
    }
}

struct RealtimeStrategyDescriptions: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(RealtimeStrategyGuide.schedule).font(.system(size: 12)).foregroundStyle(Palette.muted)
            HStack(alignment: .top, spacing: 18) {
                ForEach(RealtimeStrategyGuide.all) { guide in
                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(guide.title).font(.system(size: 18, weight: .semibold))
                            Text(guide.summary).font(.system(size: 12)).foregroundStyle(Palette.muted)
                            Divider()
                            ForEach(Array(guide.conditions.enumerated()), id: \.offset) { number, text in
                                HStack(alignment: .top, spacing: 10) {
                                    Text(String(number + 1)).foregroundStyle(Palette.teal).frame(width: 16)
                                    Text(text).frame(maxWidth: .infinity, alignment: .leading)
                                }.font(.system(size: 12)).lineSpacing(4)
                            }
                            Text("仍需复核").font(.system(size: 12, weight: .semibold)).padding(.top, 5)
                            ForEach(guide.review, id: \.self) { Text($0).font(.system(size: 11)).foregroundStyle(Palette.amber).lineSpacing(3) }
                            Text(guide.interpretation).font(.system(size: 11)).foregroundStyle(Palette.muted).lineSpacing(4)
                            if let text=guide.sourceURL,let url=URL(string:text) { Link(guide.sourceName,destination:url).font(.system(size:11)) }
                            else { Text(guide.sourceName).font(.system(size:11)).foregroundStyle(Palette.muted) }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                    }.frame(maxWidth: .infinity, alignment: .topLeading)
                }
            }
            Text(RealtimeStrategyGuide.scope).font(.system(size: 11)).foregroundStyle(Palette.muted).lineSpacing(4)
        }
    }
}
