import SwiftUI

struct MobileStockDetail:View {
    @EnvironmentObject var store:MobileStore
    let stock:Stock
    let manifest:MobileManifest
    @State private var candles:[Candle]=[]
    @State private var chartError:String?
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                ResearchCard {
                    VStack(alignment:.leading,spacing:12) {
                        HStack { Text("\(stock.tsCode) · \(stock.industry)").font(.subheadline).foregroundStyle(.secondary);Spacer();StatePill(text:stock.state) }
                        HStack(alignment:.firstTextBaseline,spacing:12) { Text(decimal(stock.close)).font(.system(size:36,weight:.semibold,design:.rounded)).monospacedDigit();Text(String(format:"%+.2f%%",stock.change)).font(.headline).foregroundStyle(MobileTheme.change(stock.change)) }
                        Text("\(dateText(stock.tradeDate)) 收盘 · 匹配分 \(decimal(stock.score,digits:1))").font(.caption).foregroundStyle(.secondary)
                    }
                }
                ResearchCard {
                    if !candles.isEmpty { MobileCandleChart(candles:candles) }
                    else if let chartError { VStack(alignment:.leading,spacing:12) { Text(chartError).font(.subheadline).foregroundStyle(.secondary);Button("重试 K 线") { Task { await load() } } } }
                    else { ProgressView("正在读取 K 线…").frame(maxWidth:.infinity,minHeight:220) }
                }
                ResearchCard {
                    VStack(alignment:.leading,spacing:16) {
                        Text("为什么进入观察").font(.headline)
                        if manifest.strategy=="golden_pit" {
                            condition("长期趋势",detail:"收盘 > MA60，MA60 五日变化 \(percent(stock.ma60Slope))",passed:stock.trendOk)
                            condition("前期上涨",detail:"60 日涨幅 \(percent(stock.ret60))",passed:stock.strengthOk)
                            condition("坑形修复",detail:"坑深 \(percent(stock.pitDepth)) · 反弹 \(percent(stock.pitRebound))",passed:stock.pullbackOk)
                            condition("坑底缩量",detail:"底部 / 峰顶平均成交额 \(decimal(stock.pitContraction))",passed:stock.volumeOk)
                            condition("右侧确认",detail:"收复 MA20 并收高；今日 / 前五日均额 \(decimal(stock.pitRecoveryVolume))",passed:stock.turnOk)
                            Text("高点 \(dateText(stock.pitPeakDate ?? "—")) → 低点 \(dateText(stock.pitTroughDate ?? "—"))\n下跌 \(decimal(stock.pitFallDays,digits:0)) 日 · 距低点 \(decimal(stock.pitAge,digits:0)) 日")
                                .font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                        } else {
                        condition("趋势向上",detail:"收盘 > MA20 > MA60",passed:stock.trendOk)
                        condition("相对强势",detail:"20 日强度前 \(decimal((1-(stock.rs20 ?? 0))*100,digits:0))%",passed:stock.strengthOk)
                        condition("位置克制",detail:"高于 MA20 \(percent(stock.extension))",passed:stock.pullbackOk)
                        condition(manifest.strategy=="leaders" ? "成交活跃":"量能收缩",detail:manifest.strategy=="leaders" ? "成交额前 \(decimal((1-(stock.liquidityRank ?? 0))*100,digits:0))%":"近3日 / 20日成交额 \(decimal(stock.volumeRatio))",passed:stock.volumeOk)
                        condition("收盘确认",detail:manifest.strategy=="leaders" ? "收盘 ≥ MA10，单日未急涨":"当日上涨，收盘靠近日内高点",passed:stock.turnOk)
                        }
                    }
                }
                ResearchCard {
                    VStack(alignment:.leading,spacing:14) {
                        Text("下一交易日的观察计划").font(.headline)
                        HStack { Metric(label:"回踩参考",value:decimal(stock.support));Metric(label:manifest.strategy=="golden_pit" ? "坑口压力":"突破观察",value:decimal(stock.breakout));Metric(label:"失效参考",value:decimal(stock.invalidation),color:MobileTheme.amber) }
                        if manifest.strategy=="golden_pit" { Text("MA20 为回踩参考，回撤前高点为坑口压力。失效参考取坑底下方 1% 与收盘价减 1.5 ATR 的较高者。").font(.caption).foregroundStyle(.secondary).lineSpacing(3) }
                        Text("高开超过 3% 放弃追入，默认研究持有 3 日。价格仅作观察参考，历史检验未模拟盘中止损。").font(.caption).foregroundStyle(.secondary).lineSpacing(3)
                        Divider()
                        HStack { Text("ATR / 价格");Spacer();Text(percent(stock.atr)) }.font(.subheadline)
                        HStack { Text("20 日平均成交额");Spacer();Text("\(decimal((stock.amount20 ?? 0)/100000)) 亿") }.font(.subheadline)
                        if stock.stale || !stock.adjusted || !stock.limitAvailable { Label("部分日期或约束数据缺失，请先更新。",systemImage:"exclamationmark.triangle").font(.caption).foregroundStyle(MobileTheme.amber) }
                    }
                }
            }.padding(16)
        }
        .background(MobileTheme.background)
        .navigationTitle(stock.name)
        .toolbar { ToolbarItem(placement:.primaryAction) { Button { store.toggleFavorite(stock) } label: { Image(systemName:store.favorites.contains(stock.id) ? "star.fill":"star").accessibilityLabel(store.favorites.contains(stock.id) ? "移出观察列表":"加入观察列表") }.tint(MobileTheme.teal) } }
        .task(id:manifest.generation+stock.id) { await load() }
    }
    private func load() async {
        chartError=nil
        do { candles=try await store.candles(manifest,code:stock.id) }
        catch is CancellationError {}
        catch { chartError=error.localizedDescription }
    }
    private func condition(_ title:String,detail:String,passed:Bool)->some View {
        HStack(alignment:.top,spacing:12) { Image(systemName:passed ? "checkmark.circle.fill":"circle").foregroundStyle(passed ? MobileTheme.teal:.secondary);VStack(alignment:.leading,spacing:4) { Text(title).font(.subheadline.weight(.medium));Text(detail).font(.caption).foregroundStyle(.secondary) };Spacer() }.accessibilityElement(children:.combine).accessibilityLabel("\(title)，\(passed ? "满足":"未满足")，\(detail)")
    }
}
