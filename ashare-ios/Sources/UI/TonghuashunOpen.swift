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
        Menu {
            Text("打开后点搜索，粘贴代码")
            Button("复制代码并打开同花顺",systemImage:"magnifyingglass") { Task { await openSearch() } }
            if TonghuashunLink.pageURL(tsCode:tsCode) != nil {
                Button("查看同花顺个股网页",systemImage:"globe") { Task { await open() } }
            }
        } label: { Text("同花顺") }
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
    private func openSearch() async {
        guard let code=TonghuashunLink.searchCode(tsCode:tsCode) else {
            failure="股票代码无效，无法复制到同花顺。"
            return
        }
        if await TonghuashunOpener.copyCodeAndLaunch(code) == false {
            failure="未安装同花顺或无法唤起，请使用网页入口。"
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
