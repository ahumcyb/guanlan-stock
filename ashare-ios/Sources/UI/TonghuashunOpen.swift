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
        guard application.canOpenURL(url) else { return false }
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
        Button("用同花顺打开") { Task { await open() } }
        .alert("无法打开同花顺", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("好", role: .cancel) {}
        } message: {
            Text(failure ?? "")
        }
    }

    @MainActor
    private func open() async {
        guard let url = TonghuashunLink.url(tsCode: tsCode) else {
            failure = "这只股票暂时无法交给同花顺。"
            return
        }
        if await TonghuashunOpener.open(url) == false {
            failure = "未安装同花顺，或系统无法打开。"
        }
    }
}
