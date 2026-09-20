import SwiftUI

struct StockDetail: View {
    @EnvironmentObject var store: AppStore
    let stock: Stock
    private var isFavorite:Bool { store.favorites.contains(stock.id) }
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                HStack(alignment:.top) {
                    VStack(alignment:.leading,spacing:5) {
                        Text(stock.name).font(.system(size:21,weight:.semibold))
                        Text("\(stock.tsCode)  ·  \(stock.industry)").font(.system(size:11)).foregroundStyle(Palette.muted)
                    }
                    Spacer()
                    Button { store.toggleFavorite(stock) } label: {
                        Image(systemName:isFavorite ? "star.fill":"star").foregroundStyle(isFavorite ? Palette.amber:Palette.muted)
                    }.buttonStyle(.plain).help(isFavorite ? "移出观察列表":"加入观察列表")
                        .accessibilityLabel(isFavorite ? "移出观察列表":"加入观察列表")
                }
                HStack(alignment:.firstTextBaseline,spacing:10) {
                    Text(decimal(stock.close)).font(.system(size:30,weight:.medium,design:.rounded)).monospacedDigit()
                    Text(String(format:"%+.2f%%",stock.change)).font(.system(size:13,weight:.medium)).foregroundStyle(stock.change>=0 ? Palette.up:Palette.down)
                    Spacer(); Badge(text:stock.state)
                }
                if stock.stale { Badge(text:"行情停留在 \(dateText(stock.tradeDate))",color:Palette.amber) }
                if !stock.adjusted || !stock.limitAvailable {
                    Text("复权或限制价尚有缺口，更新后再核对。").font(.system(size:11)).foregroundStyle(Palette.amber)
                }
                StockChart(loader:store.chartLoader,name:stock.name,signalDate:stock.tradeDate,
                    signalLabel:stock.state=="入选" ? "本次入选":"观察日",reference:stock.support,invalidation:stock.invalidation,retry:store.loadChart).id(stock.id)
                Divider()
                HStack {
                    Text(store.report?.isMomentum60==true ? "动量条件与排序":"条件匹配").font(.system(size:13,weight:.semibold))
                    Spacer()
                    Text("\(decimal(stock.score,digits:1)) / 100").font(.system(size:13,weight:.medium,design:.rounded)).foregroundStyle(Palette.teal)
                }
                VStack(spacing:9) {
                    if store.report?.isMomentum60==true {
                        condition("中期趋势",detail:"收盘高于 MA60",ok:stock.trendOk)
                        condition("六十日收益",detail:percent(stock.ret60),ok:stock.strengthOk)
                        condition("成交活跃",detail:"20 日均额前 40%",ok:stock.volumeOk)
                        condition("波动完整",detail:"60 日日波动 \(percent(stock.vol60))",ok:stock.pullbackOk)
                        condition("当日克制",detail:"当日涨幅 ≤5%",ok:stock.turnOk)
                        Text("原始动量比值 \(decimal(stock.momentumRatio)) · 分数为候选内排名，不是胜率")
                            .font(.system(size:10)).foregroundStyle(Palette.muted).frame(maxWidth:.infinity,alignment:.leading)
                    } else if store.report?.isOrderflow==true {
                        VStack(alignment:.leading,spacing:6) {
                            Text("大单净流入 " + (stock.flowNet.map { String(format:"%.0f万元",$0/10000) } ?? "未核验"))
                            Text("占成交额 " + (stock.flowNetRatio.map { String(format:"%.2f%%",$0*100) } ?? "—"))
                            Text("尾盘涨跌 " + (stock.flowLateReturn.map { String(format:"%+.2f%%",$0*100) } ?? "—"))
                            Text("尾盘成交量占比 " + (stock.flowLateVolume.map { String(format:"%.1f%%",$0*100) } ?? "—"))
                        }.font(.caption)
                    } else if store.report?.isLeft==true {
                        condition("中期约束",detail:"MA60 十日变化 \(percent(stock.leftMa60Slope10))",ok:stock.trendOk)
                        condition("短期超跌",detail:"RSI5 \(decimal(stock.leftRsi5))",ok:stock.strengthOk)
                        condition("低位区域",detail:"60 日回撤 \(percent(stock.leftDrawdown60))",ok:stock.pullbackOk)
                        condition("量能收敛",detail:"当日 / 前五日均量 \(decimal(stock.leftVolume5))",ok:stock.volumeOk)
                        condition("抛压收敛",detail:"未急跌、未追涨且未封跌停",ok:stock.turnOk)
                        Text("距20日低价 \(percent(stock.leftDistanceLow20)) · 左侧观察，尚未要求收复均线")
                            .font(.system(size:10)).foregroundStyle(Palette.muted)
                    } else if store.report?.isGoldenPit==true {
                        condition("长期趋势",detail:"MA60 五日变化 \(percent(stock.ma60Slope))",ok:stock.trendOk)
                        condition("前期上涨",detail:"60 日涨幅 \(percent(stock.ret60))",ok:stock.strengthOk)
                        condition("坑形修复",detail:"坑深 \(percent(stock.pitDepth)) · 反弹 \(percent(stock.pitRebound))",ok:stock.pullbackOk)
                        condition("坑底缩量",detail:"底部 / 峰顶均额 \(decimal(stock.pitContraction))",ok:stock.volumeOk)
                        condition("右侧确认",detail:"今日 / 前五日均额 \(decimal(stock.pitRecoveryVolume))",ok:stock.turnOk)
                        Text("高点 \(dateText(stock.pitPeakDate ?? "—")) → 低点 \(dateText(stock.pitTroughDate ?? "—")) · 距低点 \(decimal(stock.pitAge,digits:0)) 日")
                            .font(.system(size:10)).foregroundStyle(Palette.muted).frame(maxWidth:.infinity,alignment:.leading)
                    } else {
                    condition("趋势向上", detail:"收盘 > MA20 > MA60", ok:stock.trendOk)
                    condition("相对强势", detail:"20 日强度前 \(decimal((1-(stock.rs20 ?? 0))*100,digits:0))%", ok:stock.strengthOk)
                    if store.report?.isLeaders==true {
                        condition("位置克制",detail:"高于 MA20 \(percent(stock.extension))",ok:stock.pullbackOk)
                        condition("成交活跃",detail:"成交额前 \(decimal((1-(stock.liquidityRank ?? 0))*100,digits:0))%",ok:stock.volumeOk)
                        condition("短期延续",detail:"收盘 ≥ MA10 且未急涨",ok:stock.turnOk)
                    } else {
                        condition("回踩到位", detail:"距十日高点 \(percent(stock.pullback))", ok:stock.pullbackOk)
                        condition("量能收缩", detail:"三日 / 二十日 \(decimal(stock.volumeRatio))", ok:stock.volumeOk)
                        condition("收盘转强", detail:"上涨且收于日内较高处", ok:stock.turnOk)
                    }
                    }
                }
                if !stock.eligible {
                    Text("未通过基础股票池条件，或当前数据不足；不参与候选排名。").font(.system(size:11)).foregroundStyle(Palette.muted)
                }
                Divider()
                Text("下一交易日的观察计划").font(.system(size:13,weight:.semibold))
                VStack(spacing:11) {
                    priceRow(store.report?.isLeft==true ? "低位参考":(store.report?.isMomentum60==true ? "趋势参考":"回踩参考"),value:stock.support,note:store.report?.isLeft==true ? "近20日低价":(store.report?.isMomentum60==true ? "MA60 附近":"MA20 附近"))
                    priceRow(store.report?.isGoldenPit==true ? "坑口压力":"突破观察",value:stock.breakout,note:store.report?.isGoldenPit==true ? "回撤前高点":"信号日最高价")
                    priceRow("失效参考",value:stock.invalidation,note:store.report?.isLeft==true ? "20日低价下方2% / 2 ATR":(store.report?.isGoldenPit==true ? "坑底下方 1% / 1.5 ATR 较高者":"近五日低点 / 1.5 ATR"))
                }
                Text("仅作盘后观察。高开超过 3% 放弃追入，默认观察 3 个交易日。失效价不保证成交；历史检验未模拟盘中止损。").font(.system(size:10)).foregroundStyle(Palette.muted).lineSpacing(4)
                HStack {
                    Text("ATR / 价格  \(percent(stock.atr))")
                    Spacer()
                    Text("20 日成交  \(decimal((stock.amount20 ?? 0)/100000,digits:1)) 亿")
                }.font(.system(size:10)).foregroundStyle(Palette.muted)
                Text("价格截至 \(dateText(stock.tradeDate)) 收盘").font(.system(size:9)).foregroundStyle(Palette.muted)
            }.padding(22)
        }.background(.white)
    }
    private func condition(_ title:String,detail:String,ok:Bool)->some View {
        HStack(spacing:7) {
            Image(systemName:ok ? "checkmark.circle.fill":"circle").foregroundStyle(ok ? Palette.teal:Palette.line)
            Text(title).foregroundStyle(Palette.ink)
            Spacer()
            Text(detail).foregroundStyle(Palette.muted)
        }.font(.system(size:10))
    }
    private func priceRow(_ title:String,value:Double?,note:String)->some View {
        HStack {
            Text(title).font(.system(size:11)).foregroundStyle(Palette.muted)
            Text(decimal(value)).font(.system(size:14,weight:.semibold,design:.rounded)).monospacedDigit()
            Spacer()
            Text(note).font(.system(size:9)).foregroundStyle(Palette.muted)
        }
    }
}
