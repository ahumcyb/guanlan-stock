import SwiftUI

struct Workbench:View {
    @EnvironmentObject var store:MobileStore
    var favoritesOnly=false
    @State private var query=""
    @State private var debouncedQuery=""
    @State private var filter="精选"
    @State private var sort="匹配分"
    @State private var exportURL:URL?
    @State private var searchTask:Task<Void,Never>?
    private var searchIndex:StockSearchIndex { StockSearchIndex(stocks:store.report?.stocks ?? []) }
    private var stocks:[Stock] {
        let ids=searchIndex.matching(debouncedQuery)
        return StockListFilter.apply(stocks:store.report?.stocks ?? [],favoritesOnly:favoritesOnly,favorites:store.favorites,filter:filter,queryIds:ids,sort:sort)
    }
    /// 值放时间，标签带日期，避免一行挤下“10-14 14:30”。
    private var nextCheck:(label:String,value:String) {
        if store.realtime?.settings.enabled==false { return ("下次检查","已暂停") }
        let parts=dailyTime(store.status?.marketStatus?.nextScreenAt).components(separatedBy:" ")
        return parts.count==2 ? ("下次检查 · "+parts[0],parts[1]):("下次检查",parts.last ?? "—")
    }
    private func statusLine(_ report:Report)->String {
        var text=store.status?.marketStatus?.label(report.asOf) ?? "日线截至 \(dateText(report.asOf))"
        if let date=store.daily?.latest?.evidence.performance?.evaluationDate { text+=" · 精选结算截至 \(dateText(date))，未计费用" }
        return text
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
                                        VStack(alignment:.leading,spacing:4) {
                                            Text("每日收盘总结").font(.subheadline.weight(.semibold))
                                            Text(store.daily?.latest.map { dateText($0.date)+" · "+$0.analysis.headline } ?? "16:10 起核验行情，自动生成复盘")
                                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                        }
                                        Spacer();Image(systemName:"chevron.right").font(.caption).foregroundStyle(.tertiary)
                                    }.contentShape(Rectangle())
                                }.buttonStyle(.plain)
                            }
                            Section {
                                VStack(alignment:.leading,spacing:14) {
                                    HStack { Text("盘后策略").font(.caption).foregroundStyle(.secondary);Spacer();Text("日线 "+dateText(report.asOf)).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
                                    StrategyChips(selection:store.strategy,disabled:store.busy) { store.changeStrategy($0) }
                                    HStack(alignment:.top) {
                                        Metric(label:"最新候选",value:report.orderflowIncomplete ? "未完成":"\(report.shortlistCount) 只")
                                        let result=store.daily?.latest?.evidence.performance?.strategies.first(where:{$0.id==store.strategy})
                                        Metric(label:"最近精选结算",value:result?.meanReturnPct.map(dailyChange) ?? "暂无",color:result?.meanReturnPct.map{MobileTheme.change($0)} ?? .secondary)
                                        Metric(label:nextCheck.label,value:nextCheck.value)
                                    }
                                    if let status=report.orderflowStatus { Text(status.message).font(.caption).foregroundStyle(report.orderflowIncomplete ? MobileTheme.amber:MobileTheme.teal) }
                                    Text(statusLine(report)).font(.caption).foregroundStyle(.secondary)
                                    NavigationLink { StrategyInfoScreen() } label: {
                                        Label("规则、股票池与 JEV 判断",systemImage:"info.circle").font(.subheadline)
                                    }
                                }.padding(.vertical,4)
                            }
                        }
                        Section {
                            ForEach(stocks,id:\.id) { stock in
                                NavigationLink { MobileStockDetail(stock:stock,manifest:manifest) } label: { StockRow(stock:stock) }
                                    .swipeActions { Button { store.toggleFavorite(stock) } label: { Label(store.favorites.contains(stock.id) ? "移出观察":"加入观察",systemImage:"star") }.tint(MobileTheme.teal) }
                            }
                            if stocks.isEmpty { EmptyMessage(title:favoritesOnly ? "建立你的观察列表":(store.report?.orderflowIncomplete==true ? "大单数据未完成":"没有符合条件的股票"),text:favoritesOnly ? "在股票详情点星标，或向左轻扫股票加入观察。":"可以切换筛选条件或搜索名称、代码和行业。",icon:"magnifyingglass").listRowSeparator(.hidden) }
                        } header: {
                            VStack(spacing:10) {
                                if !favoritesOnly {
                                    Picker("筛选",selection:$filter) { ForEach(["精选","转强","等待","全部"],id:\.self) { Text($0=="转强" && report.conditionLabel ? "符合":$0).tag($0) } }.pickerStyle(.segmented)
                                }
                                HStack { Text("\(stocks.count) 只股票");Spacer();Text(favoritesOnly ? store.favoritesMessage:(!debouncedQuery.isEmpty ? "搜索范围：全部股票":"每行业最多 2 只精选")) }
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            .textCase(nil).padding(.vertical,8)
                            .listRowInsets(EdgeInsets(top:0,leading:16,bottom:0,trailing:16))
                            .background(Color(uiColor:.systemBackground))
                        }
                        Section { Text("研究规则尚未证明稳定优势；匹配分不代表胜率。").font(.caption).foregroundStyle(.secondary) }.listRowSeparator(.hidden)
                    }.listStyle(.plain).refreshable { await store.synchronize() }
                } else {
                    VStack(spacing:16) {
                        StrategyChips(selection:store.strategy,disabled:store.busy) { store.changeStrategy($0) }.padding(.horizontal,16)
                        EmptyMessage(title:store.busy ? "正在同步你的工作台":"暂未下载这套策略",text:store.busy ? store.message:"可切换其他策略，或到“数据”页同步最新结果。首次使用需导入连接配置。")
                    }
                }
            }
            .navigationTitle(favoritesOnly ? "我的观察":"观澜")
            .toolbarTitleDisplayMode(.inlineLarge)
            .crispTopEdge()
            .searchable(text:$query,prompt:"代码、名称或行业")
            .onChange(of:query) { _,value in
                searchTask?.cancel()
                searchTask=Task { try? await Task.sleep(for:.milliseconds(220));guard !Task.isCancelled else { return };debouncedQuery=value }
            }
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
            VStack(alignment:.trailing,spacing:6) {
                // 被排除的股票分数没有意义，用灰色区分，避免看成正常匹配分。
                Text(excluded ? "—":decimal(stock.score,digits:1)).font(.body.weight(.semibold)).monospacedDigit().foregroundStyle(excluded ? Color.secondary:MobileTheme.teal)
                Text(stock.state).font(.caption2.weight(stock.state=="入选" ? .semibold:.regular)).foregroundStyle(stock.state=="入选" ? MobileTheme.teal:.secondary)
            }.frame(width:48)
        }.padding(.vertical,6).accessibilityElement(children:.combine)
    }
    private var excluded:Bool { stock.state=="排除" }
}

/// 原来堆在选股页头部的规则概况、策略说明和 JEV 判断，集中到这里。
struct StrategyInfoScreen:View {
    @EnvironmentObject var store:MobileStore
    var body:some View {
        List {
            if let report=store.report {
                Section("股票池与规则") {
                    HStack { Metric(label:"有效股票池",value:report.eligibleCount.formatted());Metric(label:report.conditionLabel ? "符合条件":"转强确认",value:report.confirmedCount.formatted());Metric(label:"市场宽度",value:percent(report.breadth),color:MobileTheme.teal) }.padding(.vertical,4)
                    LabeledContent("持有研究",value:"1–5 日")
                    LabeledContent("市场状态",value:report.regime)
                    if report.isOrderflow {
                        Text(OrderflowGuide.summary).font(.subheadline)
                        if let status=report.orderflowStatus { Text(status.message).font(.caption).foregroundStyle(MobileTheme.amber) }
                        ForEach(OrderflowGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                    } else if report.isMomentum60 {
                        Text("市场宽度仅作环境参考，不参与本策略筛选。").font(.caption).foregroundStyle(.secondary)
                        Text(Momentum60Guide.evidence).font(.caption).foregroundStyle(MobileTheme.amber).lineSpacing(3)
                        Text(Momentum60Guide.summary).font(.subheadline)
                        ForEach(Momentum60Guide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                    } else if report.isLeft {
                        Text(LeftReboundGuide.summary).font(.subheadline)
                        ForEach(LeftReboundGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                    } else if report.isGoldenPit {
                        Text(GoldenPitGuide.summary).font(.subheadline)
                        ForEach(GoldenPitGuide.rules,id:\.self) { Text($0).font(.caption).foregroundStyle(.secondary).lineSpacing(4) }
                    }
                }
                Section {
                    if let review=store.selectedDailyJev { JevReviewView(review:review,codes:Set(report.stocks.filter{$0.state=="入选"}.map(\.id))) }
                    else { Text("同步后自动分析五套策略精选，同一股票合并判断。").font(.caption).foregroundStyle(.secondary) }
                    Button { Task { await store.requestDailyJev() } } label: { Label(store.dailyJevBusy ? "正在分析…":"分析本版精选",systemImage:"sparkles") }
                        .disabled(store.dailyJevBusy || store.realtime?.settings.jevEnabled != true)
                    if !store.dailyJevMessage.isEmpty { Text(store.dailyJevMessage).font(.caption).foregroundStyle(.secondary) }
                } header: { Text("JEV · 盘后精选判断") } footer: {
                    if store.realtime?.settings.jevEnabled != true { Text("在“实时”页右上角设置中开启 JEV 后可用。") }
                }
            } else { Text("同步后查看策略说明").foregroundStyle(.secondary) }
        }
        .navigationTitle(AfterCloseStrategies.shortName(store.strategy))
        .navigationBarTitleDisplayMode(.inline)
    }
}
