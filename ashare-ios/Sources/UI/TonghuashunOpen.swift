import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

enum TonghuashunOpener {
    /// Returns false when 同花顺 is not installed or the system refuses the scheme.
    @MainActor
    static func open(_ url: URL) async -> Bool {
        #if canImport(UIKit)
        let application = UIApplication.shared
        return await application.open(url)
        #else
        return false
        #endif
    }
}

struct OpenInTonghuashunButton: View {
    let tsCode: String
    @State private var failure: String?
    var body: some View {
        Button("查看同花顺个股页") { Task { await open() } }
        .alert("无法打开同花顺", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("好", role: .cancel) {}
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
        if await TonghuashunOpener.open(url) == false {
            failure = "无法打开同花顺个股网页，请稍后重试。"
        }
    }
}
