import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

enum TonghuashunOpener {
    @MainActor
    static func open(_ url:URL) async -> Bool {
        #if canImport(UIKit)
        guard let scheme=URL(string:"amihexin://"),UIApplication.shared.canOpenURL(scheme) else { return false }
        return await UIApplication.shared.open(url)
        #else
        return false
        #endif
    }

    @MainActor
    static func copyCodeAndLaunch(_ code:String) async -> Bool {
        #if canImport(UIKit)
        guard let scheme=URL(string:"amihexin://"),UIApplication.shared.canOpenURL(scheme) else { return false }
        UIPasteboard.general.string=code
        return await UIApplication.shared.open(scheme)
        #else
        return false
        #endif
    }
}

struct OpenInTonghuashunButton: View {
    let tsCode: String
    @State private var failure: String?
    var body: some View {
        Button("同花顺") { Task { await openSearch() } }
            .accessibilityLabel("在同花顺打开这只股票")
            .accessibilityHint("看完可点左上角返回观澜")
        .alert("无法打开同花顺", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("好", role: .cancel) {}
        } message: {
            Text(failure ?? "")
        }
    }

    @MainActor
    private func openSearch() async {
        guard let code=TonghuashunLink.searchCode(tsCode:tsCode) else {
            failure="股票代码无效，无法复制到同花顺。"
            return
        }
        // 先直达原生个股页；北交所或无法唤起时退回“复制代码并打开”。
        if let url=TonghuashunLink.nativeQuoteURL(tsCode:tsCode),await TonghuashunOpener.open(url) { return }
        if await TonghuashunOpener.copyCodeAndLaunch(code) == false {
            failure="未安装同花顺或无法唤起。"
        }
    }
}
