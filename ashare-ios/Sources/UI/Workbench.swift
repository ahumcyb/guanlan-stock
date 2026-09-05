import SwiftUI

struct Workbench:View {
    @EnvironmentObject var store:MobileStore
    var favoritesOnly=false
    @State private var query=""
    @State private var filter="精选"
    @State private var sort="匹配分"
    @State private var exportURL:URL?
    private var stocks:[Stock] {
        var rows=store.report?.stocks ?? []
        if favoritesOnly { rows=rows.filter{store.favorites.contains($0.id)} }
        else {
            switch filter {
            case "精选":rows=rows.filter{$0.state=="入选"}
            case "转强":rows=rows.filter{["入选","转强"].contains($0.state)}
            case "等待":rows=rows.filter{$0.state=="等待"}
            default:break
            }
        }
        let needle=query.trimmingCharacters(in:.whitespacesAndNewlines)
        if !needle.isEmpty { rows=rows.filter{[$0.name,$0.tsCode,$0.industry].contains{$0.localizedCaseInsensitiveContains(needle)}} }
        return rows.sorted { a,b in
            if sort=="涨跌幅" { return a.change==b.change ? a.id<b.id:a.change>b.change }
            return a.score==b.score ? a.id<b.id:a.score>b.score
        }
    }
    var body:some View {
        NavigationStack {
            Group {
                if let report=store.report,let manifest=store.snapshot?.manifest {
                    List {
                        if !favoritesOnly {
                            Section {
                                VStack(alignment:.leading,spacing:14) {
                                    HStack { Label("盘后研究",systemImage:"sun.horizon").font(.caption);Spacer();Text(dateText(report.asOf)).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
                                    HStack { Metric(label:"有效股票池",value:report.eligibleCount.formatted());Metric(label:"转强确认",value:report.confirmedCount.formatted());Metric(label:"市场宽度",value:percent(report.breadth),color:MobileTheme.teal) }
                                    Picker("策略",selection:Binding(get:{store.strategy},set:{store.changeStrategy($0)})) {
                                        Text("流动性趋势").tag("leaders");Text("缩量回踩").tag("pullback");Text("黄金坑").tag("golden_pit")
                                    }.pickerStyle(.segmented).disabled(store.busy)
                                    HStack { Text("持有研究 1–5 日");Spacer();Text(report.regime) }.font(.caption).foregroundStyle(.secondary)
                                    if report.isGoldenPit {
                                        DisclosureGroup("黄金坑策略说明") {
                                            VStack(alignment:.leading,spacing:12) {
                                                Text(GoldenPitGuide.summary).font(.subheadline)
                                                ForEach(GoldenPitGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                                            }.padding(.top,8)
                                        }.font(.subheadline).tint(MobileTheme.teal)
                                    }
                                }.padding(.vertical,4)
                            }
                            Section {
                                Picker("筛选",selection:$filter) { ForEach(["精选","转强","等待","全部"],id:\.self) { Text($0) } }.pickerStyle(.segmented)
                            }.listRowSeparator(.hidden)
                        }
                        Section {
                            ForEach(stocks) { stock in
                                NavigationLink { MobileStockDetail(stock:stock,manifest:manifest) } label: { StockRow(stock:stock) }
                                    .swipeActions { Button { store.toggleFavorite(stock) } label: { Label(store.favorites.contains(stock.id) ? "移出观察":"加入观察",systemImage:"star") }.tint(MobileTheme.teal) }
                            }
                            if stocks.isEmpty { EmptyMessage(title:favoritesOnly ? "建立你的观察列表":"没有符合条件的股票",text:favoritesOnly ? "在股票详情点星标，或向左轻扫股票加入观察。":"可以切换筛选条件或搜索名称、代码和行业。",icon:"magnifyingglass").listRowSeparator(.hidden) }
                        } header: { HStack { Text("\(stocks.count) 只股票");Spacer();Text(favoritesOnly ? "设备内保存":"每行业最多 2 只精选") } }
                        Section { Text("研究规则尚未证明稳定优势；匹配分不代表胜率。").font(.caption).foregroundStyle(.secondary) }.listRowSeparator(.hidden)
                    }.listStyle(.plain).refreshable { await store.synchronize() }
                } else {
                    VStack(spacing:16) {
                        Picker("策略",selection:Binding(get:{store.strategy},set:{store.changeStrategy($0)})) {
                            Text("流动性趋势").tag("leaders");Text("缩量回踩").tag("pullback");Text("黄金坑").tag("golden_pit")
                        }.pickerStyle(.segmented).disabled(store.busy).padding(.horizontal,16)
                        EmptyMessage(title:store.busy ? "正在同步你的工作台":"暂未下载这套策略",text:store.busy ? store.message:"可切换其他策略，或到“数据”页同步最新结果。首次使用需导入连接配置。")
                    }
                }
            }
            .navigationTitle(favoritesOnly ? "我的观察":"观澜")
            .searchable(text:$query,prompt:"代码、名称或行业")
            .toolbar {
                ToolbarItem(placement:.primaryAction) {
                    Menu {
                        Picker("排序",selection:$sort) { Text("匹配分").tag("匹配分");Text("涨跌幅").tag("涨跌幅") }
                        Button("导出当前列表 CSV",systemImage:"square.and.arrow.up") {
                            do { exportURL=try store.export(stocks) } catch { store.error=error.localizedDescription }
                        }.disabled(stocks.isEmpty)
                    } label: { Image(systemName:"ellipsis.circle").accessibilityLabel("排序与导出") }
                }
            }
            .sheet(isPresented:Binding(get:{exportURL != nil},set:{if !$0 { exportURL=nil }})) {
                VStack(spacing:24) { Text("导出选股列表").font(.title2.weight(.semibold));Text("包含代码、评分、日期和观察价格。").foregroundStyle(.secondary);if let url=exportURL { ShareLink(item:url) { Label("分享 CSV 文件",systemImage:"square.and.arrow.up") }.buttonStyle(.borderedProminent) };Button("完成") { exportURL=nil } }.padding(32).presentationDetents([.medium])
            }
        }
    }
}

struct StockRow:View {
    let stock:Stock
    var body:some View {
        HStack(spacing:12) {
            VStack(alignment:.leading,spacing:6) { Text(stock.name).font(.body.weight(.medium)).lineLimit(1);Text("\(stock.symbol) · \(stock.industry)").font(.caption).foregroundStyle(.secondary).lineLimit(1) }
            Spacer(minLength:6)
            VStack(alignment:.trailing,spacing:6) { Text(decimal(stock.close)).font(.body.monospacedDigit());Text(String(format:"%+.2f%%",stock.change)).font(.caption.monospacedDigit()).foregroundStyle(MobileTheme.change(stock.change)) }
            VStack(alignment:.trailing,spacing:6) { Text(decimal(stock.score,digits:1)).font(.body.weight(.semibold)).monospacedDigit().foregroundStyle(MobileTheme.teal);Text(stock.state).font(.caption2).foregroundStyle(.secondary) }.frame(width:48)
        }.padding(.vertical,8).accessibilityElement(children:.combine)
    }
}
