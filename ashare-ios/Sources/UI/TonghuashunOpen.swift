import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

enum TonghuashunOpener {
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
            .accessibilityLabel("复制股票代码并打开同花顺")
            .accessibilityHint("打开后在同花顺中点搜索并粘贴代码")
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
        if await TonghuashunOpener.copyCodeAndLaunch(code) == false {
            failure="未安装同花顺或无法唤起。"
        }
    }
}
