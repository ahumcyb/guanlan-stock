import SwiftUI
import AppKit

final class AppDelegate:NSObject,NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification:Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps:true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
}

@main struct GuanlanApp:App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var store=AppStore()
    var body:some Scene {
        WindowGroup("观澜选股",id:"main") {
            RootView().environmentObject(store).preferredColorScheme(.light)
                .frame(minWidth:1180,minHeight:720)
        }
        .defaultSize(width:1320,height:830)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing:.newItem) {}
            CommandMenu("研究") {
                Button("重新选股") { store.run(update:false) }.keyboardShortcut("r").disabled(store.busy)
                Button("更新数据") { store.run(update:true) }.keyboardShortcut("u").disabled(store.busy)
                Divider()
                Button("查看报告目录") { store.revealReport() }
            }
        }
    }
}

struct RootView:View {
    @EnvironmentObject var store:AppStore
    @State private var page="选股工作台"
    private let items=[("选股工作台","square.grid.2x2"),("我的观察","star"),("历史检验","chart.bar.xaxis"),("数据管理","externaldrive"),("策略说明","text.book.closed")]
    var body:some View {
        HStack(spacing:0) {
            sidebar.frame(width:184)
            Rectangle().fill(Palette.line).frame(width:0.7)
            VStack(spacing:0) {
                header
                Rectangle().fill(Palette.line).frame(height:0.7)
                if let error=store.error {
                    HStack(spacing:10) {
                        Image(systemName:"exclamationmark.circle")
                        Text(error).lineLimit(3).textSelection(.enabled)
                        Spacer()
                        Button("重试") { store.retry() }.disabled(store.busy)
                        Button { store.error=nil } label: { Image(systemName:"xmark") }.buttonStyle(.plain).accessibilityLabel("关闭错误提示")
                    }.font(.system(size:11)).foregroundStyle(Palette.amber).padding(12).background(Palette.amber.opacity(0.07))
                }
                Group {
                    if store.report == nil && page != "数据管理" && page != "策略说明" {
                        EmptyViewMessage(icon:store.busy ? "waveform.path":"externaldrive.badge.questionmark",
                            title:store.busy ? "正在准备你的选股工作台":"尚未载入日线数据",
                            message:store.busy ? store.progress:"前往数据管理选择行情目录，或点击重新选股。")
                    } else {
                        switch page {
                        case "我的观察": WorkspaceView(favoritesOnly:true).id("favorites")
                        case "历史检验": ResearchView()
                        case "数据管理": DataView()
                        case "策略说明": StrategyView()
                        default: WorkspaceView().id("workspace")
                        }
                    }
                }.frame(maxWidth:.infinity,maxHeight:.infinity)
                Rectangle().fill(Palette.line).frame(height:0.7)
                footer
            }
        }.background(Palette.canvas).foregroundStyle(Palette.ink).tint(Palette.teal)
    }
    private var sidebar:some View {
        VStack(alignment:.leading,spacing:0) {
            HStack(spacing:10) {
                Image(systemName:"waveform.path").font(.system(size:24,weight:.medium)).foregroundStyle(Palette.teal)
                VStack(alignment:.leading,spacing:4) {
                    Text("观澜").font(.system(size:23,weight:.semibold))
                    Text("GUANLAN").font(.system(size:8,weight:.medium,design:.monospaced)).tracking(2).foregroundStyle(Palette.muted)
                }
            }.padding(.horizontal,22).padding(.top,52).padding(.bottom,36)
            Text("研 究 空 间").font(.system(size:9,weight:.medium)).foregroundStyle(Palette.muted).padding(.horizontal,24).padding(.bottom,12)
            ForEach(items,id:\.0) { name,icon in
                Button { page=name } label: {
                    HStack(spacing:11) {
                        Image(systemName:icon).font(.system(size:14)).frame(width:20)
                        Text(name).font(.system(size:12,weight:page==name ? .semibold:.regular))
                        Spacer()
                        if name=="我的观察", !store.favorites.isEmpty { Text(String(store.favorites.count)).font(.system(size:10)) }
                    }.foregroundStyle(page==name ? Palette.teal:Palette.muted).padding(.horizontal,12).padding(.vertical,12)
                        .background(page==name ? Palette.selected:Color.clear,in:RoundedRectangle(cornerRadius:6))
                }.buttonStyle(.plain).padding(.horizontal,12).padding(.bottom,4)
            }
            Spacer()
            VStack(alignment:.leading,spacing:9) {
                Rectangle().fill(Palette.line).frame(height:1).padding(.bottom,6)
                HStack(spacing:6) { Circle().fill(Palette.teal).frame(width:5,height:5); Text("本机研究引擎").font(.system(size:10)) }
                Text("短线 1–5 日\n让每个判断都有依据。").font(.system(size:10)).foregroundStyle(Palette.muted).lineSpacing(6)
                Text("v1.1  /  Apple Silicon").font(.system(size:8,design:.monospaced)).foregroundStyle(Palette.muted.opacity(0.7)).padding(.top,8)
            }.padding(24)
        }
    }
    private var header:some View {
        HStack(spacing:12) {
            Text(page).font(.system(size:12,weight:.medium))
            Spacer()
            if let report=store.report {
                HStack(spacing:5) { Circle().fill(report.staleSessions==0 ? Palette.teal:Palette.amber).frame(width:5,height:5); Text("\(dateText(report.asOf)) 收盘") }
                    .font(.system(size:11)).foregroundStyle(Palette.muted)
            }
            Button { store.run(update:false) } label: { Label("重新选股",systemImage:"arrow.clockwise") }
                .controlSize(.small).disabled(store.busy)
            Button { store.run(update:true) } label: { Label(store.remoteEnabled ? "同步服务器":"更新数据",systemImage:"arrow.down.to.line") }
                .buttonStyle(.borderedProminent).tint(Palette.teal).controlSize(.small).disabled(store.busy)
        }.padding(.horizontal,24).frame(height:62)
    }
    private var footer:some View {
        HStack(spacing:9) {
            if store.busy { ProgressView().controlSize(.mini).scaleEffect(0.7) }
            else { Image(systemName:"checkmark.circle").foregroundStyle(Palette.teal) }
            Text(store.progress).lineLimit(1)
            Spacer()
            if store.busy { Button("取消") { store.cancel() }.buttonStyle(.plain) }
            Text("仅供研究 · 匹配分不代表胜率").foregroundStyle(Palette.muted)
        }.font(.system(size:9)).foregroundStyle(Palette.muted).padding(.horizontal,18).frame(height:31)
    }
}
