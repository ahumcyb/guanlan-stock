import SwiftUI

struct MobileResearch:View {
    @EnvironmentObject var store:MobileStore
    @State private var horizon=3
    var body:some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading,spacing:16) {
                    if let report=store.report {
                        ResearchCard { VStack(alignment:.leading,spacing:12) { Text(report.strategyName ?? "短线研究").font(.title3.weight(.semibold));Text("\(dateText(report.backtest.start)) — \(dateText(report.backtest.end))").font(.caption).foregroundStyle(.secondary);Text("次日开盘进入，往返成本 0.30%。多个信号可能重叠，以下为单次事件统计。").font(.subheadline).foregroundStyle(.secondary).lineSpacing(4) } }
                        if report.isMomentum60 {
                            ResearchCard { Text(Momentum60Guide.evidence + " 下列动态指标是另一口径的事后事件观察。").font(.subheadline).foregroundStyle(MobileTheme.amber).lineSpacing(4) }
                        }
                        Picker("持有期",selection:$horizon) { ForEach([1,3,5],id:\.self) { Text("持有 \($0) 日").tag($0) } }.pickerStyle(.segmented)
                        if let result=report.backtest.horizons.first(where:{$0.horizon==horizon}) {
                            ResearchCard { VStack(alignment:.leading,spacing:18) { HStack { Metric(label:"平均单次净收益",value:percent(result.mean,signed:true),color:MobileTheme.change(result.mean ?? 0));Metric(label:"获利事件占比",value:percent(result.winRate)) };HStack { Metric(label:"可结算事件",value:"\(result.count) / \(result.total)");Metric(label:"成本提高至 0.60%",value:percent(result.stressMean,signed:true),color:MobileTheme.change(result.stressMean ?? 0)) };Divider();HStack { Text("简单流动性参照").font(.subheadline);Spacer();Text(percent(result.benchmark.mean,signed:true)).font(.headline.monospacedDigit()).foregroundStyle(MobileTheme.change(result.benchmark.mean ?? 0)) };Text(report.backtest.benchmarkLabel).font(.caption).foregroundStyle(.secondary) } }
                            ResearchCard { VStack(alignment:.leading,spacing:12) { Text("样本审计").font(.headline);ForEach(result.statuses.keys.sorted(),id:\.self) { key in HStack { Text(statusName(key));Spacer();Text(String(result.statuses[key] ?? 0)).monospacedDigit() }.font(.subheadline) } } }
                        }
                        ResearchCard {
                            VStack(alignment:.leading,spacing:14) {
                                Text("分月结果 · 持有 3 日").font(.headline)
                                ForEach(report.backtest.monthly) { month in HStack { Text(month.displayMonth).font(.subheadline.monospaced());Spacer();Text(month.sampleLabel).font(.caption).foregroundStyle(.secondary);Text(percent(month.mean,signed:true)).font(.subheadline.monospacedDigit()).foregroundStyle(MobileTheme.change(month.mean ?? 0)).frame(width:86,alignment:.trailing) } }
                            }
                        }
                        ResearchCard {
                            VStack(alignment:.leading,spacing:12) {
                                Text("策略和验证边界").font(.headline)
                                if report.isMomentum60 {
                                    Text(Momentum60Guide.summary).font(.subheadline).foregroundStyle(.secondary).lineSpacing(4)
                                } else {
                                    Text("流动性趋势：成交额前20%、20日强度前50%，收盘 > MA20 > MA60，短期延续且不过热。\n\n缩量回踩：20日强度前35%，距离近10日高点回撤1%–10%，近3日成交额收缩后收盘转强。\n\n基础池要求沪深非ST、充足日线、日均成交额≥1亿元、价格≥3元、ATR≤6%；市场宽度至少40%，每行业最多2只，共10只候选。").font(.subheadline).foregroundStyle(.secondary).lineSpacing(4)
                                }
                                ForEach(report.warnings,id:\.self) { Label($0,systemImage:"info.circle").font(.caption).foregroundStyle(MobileTheme.amber) }
                            }
                        }
                    } else { EmptyMessage(title:"同步后查看历史检验",text:"手机和 Mac 使用同一份研究结果。") }
                }.padding(16)
            }.background(MobileTheme.background).navigationTitle("历史检验")
        }
    }
    private func statusName(_ value:String)->String { ["settled":"可结算","pending":"观察期未结束","gap":"高开超过3%","limit_up":"开盘涨停","missing_signal":"信号日缺数","missing_entry":"进入日缺数","missing_exit":"退出日缺数","unresolved":"延期后仍无法结算","censored":"延迟窗口未结束"][value] ?? value }
}
