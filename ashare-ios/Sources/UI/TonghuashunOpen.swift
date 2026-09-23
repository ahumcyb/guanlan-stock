import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

enum TonghuashunOpener {
    @MainActor
    static func openInApp(_ url: URL) async -> Bool {
        #if canImport(UIKit)
        return await UIApplication.shared.open(url,options:[.universalLinksOnly:true])
        #else
        return false
        #endif
    }

    @MainActor
    static func openWebPage(_ url: URL) async -> Bool {
        #if canImport(UIKit)
        return await UIApplication.shared.open(url)
        #else
        return false
        #endif
    }
}

struct OpenInTonghuashunButton: View {
    let tsCode: String
    @State private var failure: String?
    var body: some View {
        Button("在同花顺打开") { Task { await open() } }
        .alert("无法直接打开同花顺", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            if TonghuashunLink.pageURL(tsCode:tsCode) != nil {
                Button("查看同花顺网页") { Task { await openWeb() } }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text(failure ?? "")
        }
    }

    @MainActor
    private func open() async {
        guard let url = TonghuashunLink.url(tsCode: tsCode) else {
            failure = "这只股票暂时没有可核验的同花顺个股页。"
            return
        }
        if await TonghuashunOpener.openInApp(url) == false {
            failure = "同花顺未接受该股票的直接跳转。你仍可查看官网个股页。"
        }
    }

    @MainActor
    private func openWeb() async {
        guard let url=TonghuashunLink.pageURL(tsCode:tsCode) else { return }
        _=await TonghuashunOpener.openWebPage(url)
    }
}
