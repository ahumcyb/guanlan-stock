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
        else if query.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty {
            switch filter {
            case "精选":rows=rows.filter{$0.state=="入选"}
            case "转强":rows=rows.filter{["入选","转强","符合"].contains($0.state)}
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
                                Button { store.openDailySummary() } label: {
                                    HStack(spacing:12) {
                                        Image(systemName:"sun.horizon").foregroundStyle(MobileTheme.teal)
                                        VStack(alignment:.leading,spacing:5) {
                                            Text("每日收盘总结").font(.subheadline.weight(.semibold))
                                            Text(store.daily?.latest.map { dateText($0.date)+" · "+$0.analysis.headline } ?? "16:10 起核验行情，自动生成复盘")
                                                .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                        }
                                        Spacer();Image(systemName:"chevron.right").font(.caption).foregroundStyle(.secondary)
                                    }.padding(.vertical,5)
                                }.buttonStyle(.plain)
                            }
                            Section {
                                VStack(alignment:.leading,spacing:14) {
                                    HStack { Label("盘后研究",systemImage:"sun.horizon").font(.caption);Spacer();Text(dateText(report.asOf)).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
                                    Picker("策略",selection:Binding(get:{store.strategy},set:{store.changeStrategy($0)})) {
                                        ForEach(AfterCloseStrategies.ids,id:\.self) { Text(AfterCloseStrategies.shortName($0)).tag($0) }
                                    }.pickerStyle(.segmented).disabled(store.busy)
                                    HStack(alignment:.top) {
                                        Metric(label:"最新候选",value:report.orderflowIncomplete ? "未完成":"\(report.shortlistCount) 只")
                                        let result=store.daily?.latest?.evidence.performance?.strategies.first(where:{$0.id==store.strategy})
                                        Metric(label:"最近精选结算",value:result?.meanReturnPct.map(dailyChange) ?? "—")
                                        VStack(alignment:.leading,spacing:4) {
                                            Metric(label:"下次检查",value:store.realtime?.settings.enabled==false ? "已暂停":(dailyTime(store.status?.marketStatus?.nextScreenAt).components(separatedBy:" ").last ?? "—"))
                                            if store.realtime?.settings.enabled != false { Text(String(dailyTime(store.status?.marketStatus?.nextScreenAt).prefix(5))).font(.caption2).foregroundStyle(.secondary) }
                                        }
                                    }
                                    if let status=report.orderflowStatus { Text(status.message).font(.caption).foregroundStyle(report.orderflowIncomplete ? MobileTheme.amber:MobileTheme.teal) }
                                    Text(store.status?.marketStatus?.label(report.asOf) ?? "日线截至 \(dateText(report.asOf)) · 完整日期待核验").font(.caption).foregroundStyle(.secondary)
                                    if let date=store.daily?.latest?.evidence.performance?.evaluationDate { Text("精选观察结算截至 \(dateText(date))，未计费用及成交约束。").font(.caption2).foregroundStyle(.secondary) }
                                    DisclosureGroup("股票池与规则概况") {
                                    HStack { Metric(label:"有效股票池",value:report.eligibleCount.formatted());Metric(label:report.conditionLabel ? "符合条件":"转强确认",value:report.confirmedCount.formatted());Metric(label:"市场宽度",value:percent(report.breadth),color:MobileTheme.teal) }
                                    HStack { Text("持有研究 1–5 日");Spacer();Text(report.regime) }.font(.caption).foregroundStyle(.secondary)
                                    if report.isOrderflow {
                                        DisclosureGroup("大单承接 · 规则与覆盖") {
                                            Text(OrderflowGuide.summary).font(.subheadline)
                                            if let status=report.orderflowStatus { Text(status.message).foregroundStyle(MobileTheme.amber) }
                                            ForEach(OrderflowGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                                        }
                                    } else if report.isMomentum60 {
                                        Text("市场宽度仅作环境参考，不参与本策略筛选。").font(.caption).foregroundStyle(.secondary)
                                        Text(Momentum60Guide.evidence).font(.caption).foregroundStyle(MobileTheme.amber).lineSpacing(3)
                                        DisclosureGroup("60 日风险调整动量说明") {
                                            VStack(alignment:.leading,spacing:12) {
                                                Text(Momentum60Guide.summary).font(.subheadline)
                                                ForEach(Momentum60Guide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                                            }.padding(.top,8)
                                        }.font(.subheadline).tint(MobileTheme.teal)
                                    } else if report.isLeft {
                                        DisclosureGroup("左侧低吸策略说明") {
                                            VStack(alignment:.leading,spacing:12) {
                                                Text(LeftReboundGuide.summary).font(.subheadline)
                                                ForEach(LeftReboundGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                                            }.padding(.top,8)
                                        }.font(.subheadline).tint(MobileTheme.teal)
                                    } else if report.isGoldenPit {
                                        DisclosureGroup("黄金坑策略说明") {
                                            VStack(alignment:.leading,spacing:12) {
                                                Text(GoldenPitGuide.summary).font(.subheadline)
                                                ForEach(GoldenPitGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                                            }.padding(.top,8)
                                        }.font(.subheadline).tint(MobileTheme.teal)
                                    }
                                    }.font(.subheadline)
                                }.padding(.vertical,4)
                            }
                            Section("JEV · 盘后精选判断") {
                                DisclosureGroup("查看本策略的 JEV 判断") {
                                    if let review=store.selectedDailyJev { JevReviewView(review:review,codes:Set(report.stocks.filter{$0.state=="入选"}.map(\.id))) }
                                    else { Text("同步后自动分析五套策略精选，同一股票合并判断。").font(.caption).foregroundStyle(.secondary) }
                                }
                                Button("分析本版精选") { Task { await store.requestDailyJev() } }.disabled(store.dailyJevBusy || store.realtime?.settings.jevEnabled != true)
                                if !store.dailyJevMessage.isEmpty { Text(store.dailyJevMessage).font(.caption).foregroundStyle(.secondary) }
                            }
                            Section {
                                Picker("筛选",selection:$filter) { ForEach(["精选","转强","等待","全部"],id:\.self) { Text($0=="转强" && report.conditionLabel ? "符合":$0).tag($0) } }.pickerStyle(.segmented)
                            }.listRowSeparator(.hidden)
                        }
                        Section {
                            ForEach(stocks) { stock in
                                NavigationLink { MobileStockDetail(stock:stock,manifest:manifest) } label: { StockRow(stock:stock) }
                                    .swipeActions { Button { store.toggleFavorite(stock) } label: { Label(store.favorites.contains(stock.id) ? "移出观察":"加入观察",systemImage:"star") }.tint(MobileTheme.teal) }
                            }
                            if stocks.isEmpty { EmptyMessage(title:favoritesOnly ? "建立你的观察列表":(store.report?.orderflowIncomplete==true ? "大单数据未完成":"没有符合条件的股票"),text:favoritesOnly ? "在股票详情点星标，或向左轻扫股票加入观察。":"可以切换筛选条件或搜索名称、代码和行业。",icon:"magnifyingglass").listRowSeparator(.hidden) }
                        } header: { HStack { Text("\(stocks.count) 只股票");Spacer();Text(favoritesOnly ? store.favoritesMessage:(!query.isEmpty ? "搜索范围：全部股票":"每行业最多 2 只精选")) } }
                        Section { Text("研究规则尚未证明稳定优势；匹配分不代表胜率。").font(.caption).foregroundStyle(.secondary) }.listRowSeparator(.hidden)
                    }.listStyle(.plain).refreshable { await store.synchronize() }
                } else {
                    VStack(spacing:16) {
                        Picker("策略",selection:Binding(get:{store.strategy},set:{store.changeStrategy($0)})) {
                            ForEach(AfterCloseStrategies.ids,id:\.self) { Text(AfterCloseStrategies.shortName($0)).tag($0) }
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
