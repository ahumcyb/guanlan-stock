import SwiftUI

struct JevStockView:View {
    let review:JevStockReview
    var body:some View {
        TimelineView(.periodic(from:.now,by:1)) { _ in
        VStack(alignment:.leading,spacing:8) {
            HStack { Text(review.name).font(.headline);Spacer();Text(review.label).font(.headline).foregroundStyle(review.isExpired ? Color.secondary:(review.decision=="buy" ? Color.teal:Color.orange)) }
            Text(review.tsCode+" · "+(review.scope=="after_close" ? "收盘参考 "+dateText(review.priceDate ?? ""):"行情："+realtimeDate(review.quoteAt))+" · "+String(format:"%.2f",review.price)).font(.caption).foregroundStyle(.secondary)
            Text(review.isExpired ? "基于原始快照的回看判断，不适用于当前买入。":review.explanation).font(.subheadline)
            Text("模型原始分类："+(review.decisionNames[review.modelChoice] ?? "未完成")+String(format:" · 置信度 %.0f%%（非盈利概率）",review.confidence*100)).font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("核查条件与失效条件") {
                ForEach(review.conditions,id:\.self) { Text($0).font(.caption) }
                Text(review.invalidation).font(.caption)
                Text("仅依据本轮量价和规则；公告、财务与真实成交条件尚未完整核验。").font(.caption).foregroundStyle(.secondary)
            }
        }.padding(.vertical,5)
        }
    }
}
struct JevReviewView:View {
    let review:JevReview
    var codes:Set<String>?=nil
    var body:some View {
        VStack(alignment:.leading,spacing:10) {
            Text(review.message).font(.caption).foregroundStyle(.secondary)
            if let model=review.model { Text(model+" · "+(review.reviewedAt.map(realtimeDate) ?? "")).font(.caption2).foregroundStyle(.secondary) }
            if review.scope=="after_close" { Text("下一交易日的条件计划，开盘时需重新核价和核查风险。").font(.caption).foregroundStyle(.secondary) }
            ForEach(review.rows.filter { codes?.contains($0.tsCode) ?? true }) { row in JevStockView(review:row);Divider() }
        }
    }
}
