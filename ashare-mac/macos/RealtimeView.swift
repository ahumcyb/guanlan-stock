import SwiftUI
import Foundation

@MainActor final class RealtimeDesktopStore: ObservableObject {
    @Published var state: RealtimeState?
    @Published var busy = false
    @Published var message = "连接实时策略服务…"
    func request(_ action: String, runtime: Runtime, values: [String: Any] = [:]) async {
        guard !busy else { return }
        busy = true;defer { busy = false }
        do {
            let input = try JSONSerialization.data(withJSONObject: values)
            let data = try await Task.detached(priority: .utility) {
                let process = Process();let output = Pipe();let source = Pipe()
                process.executableURL = URL(fileURLWithPath: runtime.python)
                process.currentDirectoryURL = URL(fileURLWithPath: runtime.projectRoot)
                process.arguments = ["-m", "mobile_server.realtime_control", "--config", runtime.projectRoot + "/settings/mobile-viewer.json", action]
                process.standardOutput = output;process.standardError = FileHandle.nullDevice;process.standardInput = source
                try process.run()
                source.fileHandleForWriting.write(input);try source.fileHandleForWriting.close()
                let data = output.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit()
                guard process.terminationStatus == 0, data.count <= 2 * 1024 * 1024 else { throw CocoaError(.fileReadUnknown) }
                return data
            }.value
            if action == "state" {
                let decoder = JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
                let value = try decoder.decode(RealtimeState.self, from: data)
                guard value.schemaVersion == 1 else { throw CocoaError(.fileReadCorruptFile) }
                state = value;message = "已同步服务器的实时策略与提醒记录"
            } else {
                message = action == "settings" ? "设置已保存" : (action == "test" ? "测试通知已提交，请在 iPhone 查看 Bark" : "行情检查已提交，优先由 Mac 执行")
            }
        } catch { message = "实时服务暂不可用，请检查 Mac 节点和服务器连接。" }
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
                if showSettings { settings }
                if let latest = store.state?.latest {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(latest.message).font(.headline)
                            Text("最近检查 \(realtimeDate(latest.generatedAt)) · \(latest.executor == "mac" ? "Mac" : "服务器")")
                                .font(.caption).foregroundStyle(Palette.muted)
                            ForEach(latest.reviews) { r in
                                Text("\(r.name)  \(String(format: "%+.2f%%", r.change))   \(r.note) · 相对昨日筛选价")
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                    }
                }
                if let report = store.state?.lastScreen {
                    HStack {
                        Text("最近尾盘结果 · \(dateText(report.date))").font(.headline)
                        Spacer()
                        Text("新鲜行情 \(report.freshCount ?? 0) / \(report.universeCount ?? 0)").font(.caption).foregroundStyle(Palette.muted)
                    }
                    ForEach(report.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(Palette.amber) }
                    HStack(alignment: .top, spacing: 18) {
                        candidateColumn(report, "overnight")
                        candidateColumn(report, "golden")
                    }
                    if let analysis = report.ai {
                        GroupBox("DeepSeek · 可选解读") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(analysis.summary)
                                ForEach(analysis.risks, id: \.self) { Text($0).font(.caption).foregroundStyle(Palette.muted) }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                        }
                    }
                } else {
                    Text("交易日定时执行后，将显示两套策略的行情时间、候选与待核验条件。").padding(28).frame(maxWidth: .infinity).background(Palette.selected, in: RoundedRectangle(cornerRadius: 12))
                }
                Text("提醒记录").font(.headline)
                ForEach(store.state?.events ?? []) { e in
                    VStack(alignment: .leading, spacing: 7) {
                        HStack { Text(e.title).font(.headline);Spacer();Text(e.deliveryLabel).foregroundStyle(Palette.muted) }
                        Text(e.body).font(.system(size: 12))
                        Text(realtimeDate(e.createdAt)).font(.caption).foregroundStyle(Palette.muted)
                        Divider()
                    }
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
    }
    private func candidateColumn(_ report: RealtimeSnapshot, _ strategy: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(realtimeStrategy(strategy)).font(.headline)
            if (report.strategies[strategy] ?? []).isEmpty { Text("本轮无符合条件的候选").foregroundStyle(Palette.muted).padding(.vertical, 16) }
            ForEach(report.strategies[strategy, default: []]) { row in
                GroupBox {
                    VStack(alignment: .leading, spacing: 9) {
                        HStack { Text(row.name).font(.headline);Spacer();Text(String(format: "%.2f  %+.2f%%", row.price, row.change)).foregroundStyle(Palette.up).monospacedDigit() }
                        Text("\(row.tsCode) · \(row.state)").font(.caption).foregroundStyle(Palette.muted)
                        Text("行情 \(realtimeDate(row.quoteAt))\(row.timeBasis == "provider_updated_at" ? " · 供应商更新时间" : "")").font(.caption2).foregroundStyle(Palette.muted)
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
