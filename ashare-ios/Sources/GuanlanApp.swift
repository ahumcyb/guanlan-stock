import SwiftUI

@main struct GuanlanMobileApp:App {
    @StateObject private var store=MobileStore()
    var body:some Scene {
        WindowGroup {
            MobileRoot().environmentObject(store)
                .onOpenURL { url in Task { await store.openURL(url) } }
        }
        #if os(macOS)
        .defaultSize(width:430,height:860)
        #endif
    }
}

struct MobileRoot:View {
    @EnvironmentObject var store:MobileStore
    @Environment(\.scenePhase) private var phase
    var body:some View {
        VStack(spacing:0) {
            if let error=store.error {
                HStack(alignment:.top,spacing:10) { Image(systemName:"exclamationmark.circle");Text(error).font(.caption).lineLimit(3);Spacer(minLength:0);Button { store.error=nil } label: { Image(systemName:"xmark").accessibilityLabel("关闭提示") } }.foregroundStyle(MobileTheme.amber).padding(12).background(MobileTheme.amber.opacity(0.10))
            } else if store.busy || store.status?.job.active==true {
                HStack(spacing:10) { ProgressView().controlSize(.small);Text(store.message).font(.caption).lineLimit(2);Spacer() }.padding(12).background(MobileTheme.teal.opacity(0.06))
            }
            TabView(selection:$store.selectedTab) {
                Workbench().tabItem { Label("选股",systemImage:"waveform.path.ecg") }.tag(0)
                RealtimeScreen().tabItem { Label("实时",systemImage:"bell.badge") }.tag(1)
                Workbench(favoritesOnly:true).tabItem { Label("观察",systemImage:"star") }.tag(2)
                MobileResearch().tabItem { Label("检验",systemImage:"chart.bar.xaxis") }.tag(3)
                MobileDataScreen().tabItem { Label("数据",systemImage:"externaldrive") }.tag(4)
            }.tint(MobileTheme.teal)
        }
        .task { await store.watchJob() }
        .sheet(isPresented:$store.dailyPresented) { DailySummaryScreen().environmentObject(store) }
        .onChange(of:phase) { _,value in if value == .active { Task { await store.synchronize() } } }
    }
}
