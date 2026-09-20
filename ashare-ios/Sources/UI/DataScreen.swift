import SwiftUI
import UniformTypeIdentifiers

struct MobileDataScreen:View {
    @EnvironmentObject var store:MobileStore
    @State private var importing=false
    var body:some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading,spacing:16) {
                    ResearchCard {
                        VStack(alignment:.leading,spacing:16) {
                            Label("Mac 优先，服务器备用",systemImage:"desktopcomputer").font(.headline)
                            HStack { statusDot(store.status?.macOnline);Text("Mac 计算节点");Spacer();Text(store.status==nil ? "检测中":(store.status?.macOnline==true ? "在线":"离线")).foregroundStyle(.secondary) }.font(.subheadline)
                            HStack { statusDot(store.status?.workerOnline);Text("服务器备用节点");Spacer();Text(store.status==nil ? "检测中":(store.status?.workerOnline==true ? "就绪":"暂不可用")).foregroundStyle(.secondary) }.font(.subheadline)
                            Text("任务先交给 Mac。只有 Mac 连不上或执行中失联超时，服务器才接管。结果校验通过后再同步到手机。").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                            if let job=store.status?.job,job.status != "idle" {
                                Divider()
                                HStack(alignment:.top) { if job.active { ProgressView().controlSize(.small) } else { Image(systemName:job.status=="completed" ? "checkmark.circle":"exclamationmark.circle").foregroundStyle(job.status=="completed" ? MobileTheme.teal:MobileTheme.amber) };Text(job.message).font(.subheadline) }
                            }
                        }
                    }
                    ResearchCard {
                        VStack(alignment:.leading,spacing:14) {
                            Text("数据操作").font(.headline)
                            if let provider=store.status?.marketProvider { Text("行情来源：\(provider)").font(.caption).foregroundStyle(.secondary) }
                            Button { Task { await store.synchronize() } } label: { Label("同步最新结果",systemImage:"arrow.down.circle").frame(maxWidth:.infinity,minHeight:32) }.buttonStyle(.borderedProminent).disabled(store.busy || !store.connected)
                            Button { Task { await store.startJob("recompute") } } label: { Label("重新选股",systemImage:"arrow.clockwise").frame(maxWidth:.infinity,minHeight:32) }.buttonStyle(.bordered).disabled(!canSubmit)
                            Button { Task { await store.startJob("refresh") } } label: { Label("更新行情并选股",systemImage:"externaldrive.badge.plus").frame(maxWidth:.infinity,minHeight:32) }.buttonStyle(.bordered).disabled(!canSubmit || store.status?.canRefresh != true)
                            Text("同步读取已发布结果；重新选股使用已有行情。更新会补齐必要日线及配套数据，再计算五套盘后策略。").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                        }
                    }
                    if let report=store.report {
                        ResearchCard {
                            VStack(alignment:.leading,spacing:16) {
                                HStack { Text("已同步的数据").font(.headline);Spacer();StatePill(text:dateText(report.asOf)) }
                                ForEach(report.sources) { source in VStack(alignment:.leading,spacing:6) { HStack { Text(source.title);Spacer();Text("\(source.rows.formatted()) 行").monospacedDigit() }.font(.subheadline);Text("\(dateText(source.start)) — \(dateText(source.end))").font(.caption).foregroundStyle(.secondary) } }
                                Text("五套盘后策略、价格和 K 线绑定同一数据版本。已下载的报告和最近查看的 K 线可离线使用。").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                            }
                        }
                    }
                    ResearchCard {
                        VStack(alignment:.leading,spacing:14) {
                            Button { store.openDailySummary() } label: {
                                Label("收盘总结与 DeepSeek 设置",systemImage:"sun.horizon").frame(maxWidth:.infinity,minHeight:32)
                            }.buttonStyle(.bordered)
                            Label("私人服务器连接",systemImage:"lock.shield").font(.headline)
                            Text(store.connected ? "106.14.125.189 · 已配置专用证书与访问凭据":"导入手机配对文件后开始使用。").font(.subheadline).foregroundStyle(.secondary)
                            Button(store.connected ? "更换连接配置":"导入连接配置") { importing=true }.buttonStyle(.bordered)
                            Text("访问凭据保存在设备钥匙串。手机不保存 root 密码或 ProMax 密钥。").font(.caption).foregroundStyle(.secondary).lineSpacing(3)
                        }
                    }
                    Text("普通 Apple ID 自用安装需定期重新签名。股票研究规则尚未完成独立样本外验证，观察列表保存在本设备。").font(.caption).foregroundStyle(.secondary).padding(.horizontal,4)
                }.padding(16)
            }.background(MobileTheme.background).navigationTitle("数据与连接").refreshable { await store.refreshStatus() }
            .fileImporter(isPresented:$importing,allowedContentTypes:[.json,UTType(filenameExtension:"guanlan") ?? .data]) { result in
                switch result { case .success(let url):Task { await store.importConnection(url) };case .failure(let error):store.error=error.localizedDescription }
            }
        }
    }
    private var canSubmit:Bool { store.connected && !store.busy && store.status?.job.active != true && store.status?.workerOnline==true }
    private func statusDot(_ online:Bool?)->some View { Image(systemName:online==nil ? "circle.dotted":(online==true ? "checkmark.circle.fill":"minus.circle")).foregroundStyle(online==true ? MobileTheme.teal:MobileTheme.muted) }
}
