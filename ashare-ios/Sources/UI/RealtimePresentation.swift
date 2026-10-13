import SwiftUI

/// 把服务端的工程诊断改写成直白说明；原文仍在“数据说明”里保留，便于核对。
enum RealtimeWording {
    static func warning(_ raw:String)->String {
        if raw.contains("分钟接口") { return "分时数据缺失，七步法“尾盘回踩”一步未核验" }
        if raw.contains("暂无可用快照") { return "少数股票行情未及时更新，未纳入本轮" }
        if raw.contains("回退全池D6") { return "批量行情异常，已改为逐股行情，结果不受影响" }
        if raw.contains("流通股本不可用") { return "缺少前日流通股本，七步法本轮未生成候选" }
        if raw.contains("新浪备用") { return "沪深300 使用备用行情源" }
        if let match=raw.firstMatch(of:/批量覆盖\s*(\d+)\s*\/\s*(\d+)/) { return "行情覆盖 \(match.1)/\(match.2) 只" }
        if let match=raw.firstMatch(of:/有效报价[^\d]*(\d+)\s*只/) { return "有效行情 \(match.1) 只" }
        return raw
    }
    /// 去掉纯覆盖率类说明，只保留会影响结果解读的提示。
    static func notable(_ warnings:[String])->[String] {
        var seen=Set<String>()
        return warnings.map(warning).filter { !$0.hasPrefix("行情覆盖") && !$0.hasPrefix("有效行情") && seen.insert($0).inserted }
    }
    static func eventBody(_ raw:String)->String {
        if let match=raw.firstMatch(of:/分钟核验\s*(\d+)\s*\/\s*(\d+)/),match.1=="0" { return "分时数据缺失，本轮未生成隔夜研究结果。" }
        return raw
    }
}

extension RealtimeState {
    var nodeLabel:String { running ? (executor=="mac" ? "Mac 正在计算":"服务器正在接管"):(macOnline ? "Mac 在线":(serverOnline ? "服务器备用":"节点离线")) }
    var pushReady:Bool { settings.barkConfigured && settings.notificationEnabled }
    var healthy:Bool { (macOnline || serverOnline) && settings.enabled && pushReady }
    var statusLine:String { [nodeLabel,settings.enabled ? "自动运行":"已暂停",pushReady ? "推送已开启":"推送未开启"].joined(separator:" · ") }
}

struct RealtimeCandidateRow:View {
    let candidate:RealtimeCandidate
    var trailing:String?=nil
    var body:some View {
        HStack(spacing:12) {
            VStack(alignment:.leading,spacing:4) {
                Text(candidate.name).font(.body.weight(.medium)).lineLimit(1)
                Text(String(candidate.tsCode.prefix(6))+" · "+candidate.state).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength:8)
            if let trailing {
                Text(trailing).font(.body.weight(.semibold).monospacedDigit()).foregroundStyle(MobileTheme.teal)
            } else {
                VStack(alignment:.trailing,spacing:4) {
                    Text(decimal(candidate.price)).font(.body.monospacedDigit())
                    Text(String(format:"%+.2f%%",candidate.change)).font(.caption.monospacedDigit()).foregroundStyle(MobileTheme.change(candidate.change))
                }
            }
        }.padding(.vertical,2).accessibilityElement(children:.combine)
    }
}

struct RealtimeGuideList:View {
    var body:some View {
        List {
            Section { Text(RealtimeStrategyGuide.schedule).font(.subheadline) } header: { Text("执行时间") }
            Section("各策略规则") {
                ForEach(RealtimeStrategyGuide.all) { guide in
                    NavigationLink { RealtimeStrategyDetail(guide:guide) } label: {
                        VStack(alignment:.leading,spacing:4) { Text(guide.title).font(.headline);Text(guide.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) }.padding(.vertical,2)
                    }
                }
            }
        }.navigationTitle("策略说明").navigationBarTitleDisplayMode(.inline)
    }
}
