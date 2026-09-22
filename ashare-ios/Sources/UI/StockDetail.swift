import SwiftUI

struct MobileStockDetail:View {
    @EnvironmentObject var store:MobileStore
    let stock:Stock
    let manifest:MobileManifest
    @StateObject private var chart=ChartLoadState()
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                ResearchCard {
                    VStack(alignment:.leading,spacing:12) {
                        HStack { Text("\(stock.tsCode) · \(stock.industry)").font(.subheadline).foregroundStyle(.secondary);Spacer();StatePill(text:stock.state) }
                        HStack(alignment:.firstTextBaseline,spacing:12) { Text(decimal(stock.close)).font(.system(size:36,weight:.semibold,design:.rounded)).monospacedDigit();Text(String(format:"%+.2f%%",stock.change)).font(.headline).foregroundStyle(MobileTheme.change(stock.change)) }
                        Text("\(dateText(stock.tradeDate)) 收盘 · 匹配分 \(decimal(stock.score,digits:1))").font(.caption).foregroundStyle(.secondary)
                        OpenInTonghuashunButton(tsCode: stock.tsCode).buttonStyle(.bordered).tint(MobileTheme.teal)
                    }
                }
                if stock.state=="入选",let review=store.selectedDailyJev,review.bound(to:manifest),let row=review.rows.first(where:{$0.tsCode==stock.id}) {
                    ResearchCard { VStack(alignment:.leading,spacing:10) { Text("JEV · 盘后精选判断").font(.headline);JevStockView(review:row) } }
                }
                ResearchCard {
                    if let data=chart.data { MobileCandleChart(data:data,name:stock.name,tsCode:stock.tsCode,signalDate:stock.tradeDate,signalLabel:stock.state=="入选" ? "本次入选":"观察日",reference:stock.support,invalidation:stock.invalidation) }
                    else if let error=chart.error { VStack(alignment:.leading,spacing:12) { Text(error).font(.subheadline).foregroundStyle(.secondary);Button("重试 K 线") { Task { await load() } } } }
                    else { ProgressView("正在读取 K 线…").frame(maxWidth:.infinity,minHeight:220) }
                }
                ResearchCard {
                    VStack(alignment:.leading,spacing:16) {
                        Text("为什么进入观察").font(.headline)
                        if manifest.strategy=="momentum_60" {
                            condition("中期趋势",detail:"收盘高于 MA60",passed:stock.trendOk)
                            condition("六十日收益",detail:percent(stock.ret60),passed:stock.strengthOk)
                            condition("成交活跃",detail:"20 日均成交额位于主板基础池前 40%",passed:stock.volumeOk)
                            condition("波动数据完整",detail:"60 日日收益波动 \(percent(stock.vol60))",passed:stock.pullbackOk)
                            condition("当日克制",detail:"当天涨幅不超过 5%",passed:stock.turnOk)
                            Text("原始动量比值 \(decimal(stock.momentumRatio))\n首页分数为候选内相对排名，不是胜率。").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                        } else if manifest.strategy=="orderflow" {
                        VStack(alignment:.leading,spacing:6) {
                            Text("大单净流入 " + (stock.flowNet.map { String(format:"%.0f万元",$0/10000) } ?? "未核验"))
                            Text("占成交额 " + (stock.flowNetRatio.map { String(format:"%.2f%%",$0*100) } ?? "—"))
                            Text("尾盘涨跌 " + (stock.flowLateReturn.map { String(format:"%+.2f%%",$0*100) } ?? "—"))
                            Text("尾盘成交量占比 " + (stock.flowLateVolume.map { String(format:"%.1f%%",$0*100) } ?? "—"))
                        }.font(.caption)
                    } else if manifest.strategy=="left_rebound" {
                            condition("中期约束",detail:"MA60 十日变化 \(percent(stock.leftMa60Slope10))，跌幅不超过3%",passed:stock.trendOk)
                            condition("短期超跌",detail:"RSI5 \(decimal(stock.leftRsi5))，最近5日下跌3%–12%",passed:stock.strengthOk)
                            condition("低位区域",detail:"60日回撤 \(percent(stock.leftDrawdown60)) · 距20日低价 \(percent(stock.leftDistanceLow20))",passed:stock.pullbackOk)
                            condition("量能收敛",detail:"当日 / 前五日均量 \(decimal(stock.leftVolume5))",passed:stock.volumeOk)
                            condition("抛压收敛",detail:"涨跌-4%至+2%，收于振幅上部60%且未封跌停",passed:stock.turnOk)
                            Text("这是左侧观察条件，尚未要求收复 MA10 或放量转强。").font(.caption).foregroundStyle(.secondary)
                        } else if manifest.strategy=="golden_pit" {
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
                        HStack { Metric(label:manifest.strategy=="left_rebound" ? "20日低价参考":(manifest.strategy=="momentum_60" ? "趋势参考 MA60":"回踩参考"),value:decimal(stock.support));Metric(label:manifest.strategy=="golden_pit" ? "坑口压力":"突破观察",value:decimal(stock.breakout));Metric(label:"失效参考",value:decimal(stock.invalidation),color:MobileTheme.amber) }
                        if manifest.strategy=="left_rebound" { Text("失效参考取20日低价下方2%与收盘价减2 ATR的较高者；尚未模拟盘中止损。").font(.caption).foregroundStyle(.secondary) }
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
        await chart.load(key:manifest.generation+stock.id) { try await store.chartData(manifest,code:stock.id) }
    }
    private func condition(_ title:String,detail:String,passed:Bool)->some View {
        HStack(alignment:.top,spacing:12) { Image(systemName:passed ? "checkmark.circle.fill":"circle").foregroundStyle(passed ? MobileTheme.teal:.secondary);VStack(alignment:.leading,spacing:4) { Text(title).font(.subheadline.weight(.medium));Text(detail).font(.caption).foregroundStyle(.secondary) };Spacer() }.accessibilityElement(children:.combine).accessibilityLabel("\(title)，\(passed ? "满足":"未满足")，\(detail)")
    }
}
