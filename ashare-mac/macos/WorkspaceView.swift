import SwiftUI

struct WorkspaceView:View {
    @EnvironmentObject var store:AppStore
    var favoritesOnly=false
    var onDaily:(()->Void)?=nil
    @State private var query=""
    @State private var filter="精选"
    @State private var order="匹配分"
    @State private var showStatistics=false
    @State private var showJev=false
    private var filtered:[Stock] {
        let text=query.trimmingCharacters(in:.whitespacesAndNewlines)
        var rows=(store.report?.stocks ?? []).filter { stock in
            let matches=text.isEmpty || [stock.name,stock.tsCode,stock.industry].contains(where:{$0.localizedCaseInsensitiveContains(text)})
            let included = favoritesOnly ? store.favorites.contains(stock.id) :
                (!text.isEmpty || filter=="全部" || (filter=="精选" && stock.state=="入选") ||
                 (filter=="转强" && ["入选","转强","符合"].contains(stock.state)) || (filter=="等待" && stock.state=="等待"))
            return matches && included
        }
        rows.sort { a,b in
            if order=="涨跌幅" { return a.change==b.change ? a.id<b.id:a.change>b.change }
            if order=="成交额" { return a.amount20==b.amount20 ? a.id<b.id:(a.amount20 ?? 0)>(b.amount20 ?? 0) }
            return a.score==b.score ? a.id<b.id:a.score>b.score
        }
        return rows
    }
    var body:some View {
        HSplitView {
            VStack(alignment:.leading,spacing:0) {
                overview
                if !favoritesOnly && store.publishedMode {
                    DisclosureGroup("JEV · 盘后精选判断",isExpanded:$showJev) {
                        ScrollView {
                            VStack(alignment:.leading,spacing:10) {
                                Button("分析本版精选") { Task { await store.requestDailyJev() } }.disabled(store.dailyJevBusy || store.realtimeState?.settings.jevEnabled != true)
                                if let review=store.selectedDailyJev { JevReviewView(review:review,codes:Set((store.report?.stocks ?? []).filter{$0.state=="入选"}.map(\.id))) }
                                else { Text("同步后自动分析五套策略精选，同一股票合并判断。").font(.caption).foregroundStyle(.secondary) }
                                if !store.dailyJevMessage.isEmpty { Text(store.dailyJevMessage).font(.caption).foregroundStyle(.secondary) }
                            }
                        }.frame(maxHeight:230)
                    }.padding(.horizontal,20).padding(.bottom,12)
                }
                controls
                table
                HStack {
                    Text("\(filtered.count) 只股票  ·  点击一行查看依据")
                    Spacer()
                    Button { store.export(filtered) } label: { Label("导出 CSV",systemImage:"square.and.arrow.up") }
                        .buttonStyle(.plain).disabled(filtered.isEmpty)
                }.font(.system(size:10)).foregroundStyle(Palette.muted).padding(16)
            }.frame(minWidth:460,idealWidth:620)
            if let selected=store.report?.stocks.first(where:{$0.id==store.selection}) {
                StockDetail(stock:selected).frame(minWidth:360,idealWidth:500,maxWidth:.infinity)
            } else {
                EmptyViewMessage(icon:"chart.xyaxis.line",title:"选择一只股票",message:"在左侧筛选或搜索，查看走势与入选依据。")
                    .frame(minWidth:360,idealWidth:500,maxWidth:.infinity).background(.white)
            }
        }
        .onChange(of:filtered.map(\.id)) { _,ids in
            if !ids.contains(store.selection ?? "") { store.select(ids.first) }
        }
        .onAppear { if !filtered.contains(where:{$0.id==store.selection}) { store.select(filtered.first?.id) } }
    }
    private var overview:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack(alignment:.top) {
                VStack(alignment:.leading,spacing:6) {
                    Text(favoritesOnly ? "我的观察":"短线工作台").font(.system(size:24,weight:.semibold))
                    Text(favoritesOnly ? "持续跟踪条件变化，保留自己的判断。":"\(store.report?.strategyName ?? "缩量回踩转强")  ·  1–5 个交易日")
                        .font(.system(size:11)).foregroundStyle(Palette.muted)
                }
                Spacer()
                Badge(text:"盘后研究")
            }
            if !favoritesOnly {
                Button { onDaily?() } label: {
                    HStack { Label("每日收盘总结",systemImage:"sun.horizon");Spacer();Text("16:10 自动复盘").foregroundStyle(Palette.muted);Image(systemName:"chevron.right") }
                        .font(.system(size:11)).padding(10).background(Palette.selected,in:RoundedRectangle(cornerRadius:6))
                }.buttonStyle(.plain)
                Picker("筛选策略",selection:Binding(get:{store.strategy},set:{store.changeStrategy($0)})) {
                    ForEach(AfterCloseStrategies.ids,id:\.self) { Text(AfterCloseStrategies.shortName($0)).tag($0) }
                }.pickerStyle(.segmented).font(.system(size:11)).disabled(store.busy)
            }
            if let report=store.report {
                if !favoritesOnly {
                    HStack(spacing:16) {
                        Metric(label:"最新候选",value:report.orderflowIncomplete ? "未完成":"\(report.shortlistCount) 只",note:dateText(report.asOf))
                        let performance=store.dailyState?.latest?.evidence.performance
                        let result=performance?.strategies.first(where:{$0.id==store.strategy})
                        Metric(label:"最近精选观察",value:result?.meanReturnPct.map(dailyChange) ?? "—",note:performance.map{dateText($0.evaluationDate)+" · 未计成本"} ?? "等待核验")
                        Metric(label:"下次尾盘检查",value:store.realtimeState?.settings.enabled==false ? "已暂停":(dailyTime(store.serverStatus?.marketStatus?.nextScreenAt).components(separatedBy:" ").last ?? "—"),note:store.realtimeState?.settings.enabled==false ? "可在实时提醒开启":String(dailyTime(store.serverStatus?.marketStatus?.nextScreenAt).prefix(5))+" · Mac 优先")
                    }
                } else { Text(store.favoritesMessage).font(.system(size:11)).foregroundStyle(Palette.muted) }
                if let status=report.orderflowStatus { Text(status.message).font(.system(size:11)).foregroundStyle(report.orderflowIncomplete ? Palette.amber:Palette.teal) }
                DisclosureGroup("股票池与规则概况",isExpanded:$showStatistics) {
                HStack(spacing:15) {
                    Metric(label:"有效股票池",value:report.eligibleCount.formatted(),note:"\(report.universeCount.formatted()) 只当日行情")
                    Metric(label:report.conditionLabel ? "符合条件":"转强确认",value:String(report.confirmedCount),note:report.isMomentum60 ? "精选最多 5 只":"精选最多 10 只")
                    Metric(label:report.isMomentum60 ? "环境参考":"市场宽度",value:percent(report.breadth),note:report.isMomentum60 ? "MA20 上方占比 · 不参与筛选":"MA20 上方占比 · \(report.regime)",color:Palette.teal)
                }
                if report.isOrderflow {
                    Text(OrderflowGuide.summary+" "+(report.orderflowStatus?.message ?? "等待数据核验")).font(.system(size:11)).foregroundStyle(Palette.muted)
                } else if report.isMomentum60 {
                    Text(Momentum60Guide.evidence).font(.system(size:10)).foregroundStyle(Palette.amber).lineSpacing(3)
                } else if report.isLeft {
                    Text(LeftReboundGuide.summary+" 市场宽度门槛为 20%。").font(.system(size:10)).foregroundStyle(Palette.muted).lineSpacing(3)
                }
                }.font(.system(size:11)).foregroundStyle(Palette.muted)
                Text(store.serverStatus?.marketStatus?.label(report.asOf) ?? "日线截至 \(dateText(report.asOf)) · 完整日期待核验")
                    .font(.system(size:11)).foregroundStyle(store.serverStatus?.marketStatus?.needsUpdate(report.asOf)==true ? Palette.amber:Palette.muted)
                if report.missingAdjustmentToday>0 || report.missingLimitsToday>0 {
                    HStack(alignment:.top,spacing:7) {
                        Image(systemName:"info.circle")
                        Text("复权或涨跌停价有缺口，近期结果仅作观察。")
                    }.font(.system(size:10)).foregroundStyle(Palette.amber).padding(10)
                        .frame(maxWidth:.infinity,alignment:.leading).background(Palette.amber.opacity(0.07),in:RoundedRectangle(cornerRadius:5))
                }
            }
        }.padding(20)
    }
    private var controls:some View {
        VStack(spacing:13) {
            HStack {
                HStack(spacing:8) {
                    Image(systemName:"magnifyingglass").foregroundStyle(Palette.muted)
                    TextField("搜索代码、名称或行业",text:$query).textFieldStyle(.plain).font(.system(size:12))
                        .accessibilityLabel("搜索股票")
                    if !query.isEmpty {
                        Button { query="" } label: { Image(systemName:"xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(Palette.muted).accessibilityLabel("清空搜索")
                    }
                }.padding(10).background(.white,in:RoundedRectangle(cornerRadius:6))
                    .overlay(RoundedRectangle(cornerRadius:6).stroke(Palette.line,lineWidth:0.7))
                Picker("排序",selection:$order) { ForEach(["匹配分","涨跌幅","成交额"],id:\.self) { Text($0) } }
                    .labelsHidden().frame(width:96).controlSize(.small)
            }
            if !favoritesOnly {
                HStack(spacing:4) {
                    ForEach(["精选","转强","等待","全部"],id:\.self) { item in
                        Button(item=="转强" && store.report?.conditionLabel==true ? "符合":item) { filter=item; query="" }
                            .buttonStyle(.plain).font(.system(size:11,weight:filter==item ? .semibold:.regular))
                            .padding(.horizontal,14).padding(.vertical,7)
                            .foregroundStyle(filter==item ? Palette.teal:Palette.muted)
                            .background(filter==item ? Palette.selected:Color.clear,in:RoundedRectangle(cornerRadius:5))
                    }
                    Spacer()
                    Text(query.isEmpty ? (store.report?.isMomentum60==true ? "原始动量比值排序 · 最多 5 只":"同一行业最多 2 只精选"):"搜索范围：全部股票").font(.system(size:9)).foregroundStyle(Palette.muted)
                }
            }
        }.padding(.horizontal,24).padding(.bottom,16)
    }
    private var table:some View {
        VStack(spacing:0) {
            HStack {
                Text("股票 / 行业").frame(maxWidth:.infinity,alignment:.leading)
                Text("收盘").frame(width:60,alignment:.trailing)
                Text("涨跌幅").frame(width:66,alignment:.trailing)
                Text("匹配分").frame(width:55,alignment:.trailing)
                Text("状态").frame(width:46,alignment:.trailing)
            }.font(.system(size:10)).foregroundStyle(Palette.muted).padding(.horizontal,24).padding(.vertical,11)
                .background(Palette.line.opacity(0.25))
            if filtered.isEmpty {
                EmptyViewMessage(icon:favoritesOnly ? "star":"line.3.horizontal.decrease.circle",
                    title:favoritesOnly ? "还没有观察中的股票":(store.report?.orderflowIncomplete==true ? "大单数据未完成":"暂无匹配股票"),
                    message:favoritesOnly ? "在股票详情点星标，加入观察列表。":"可以切换筛选条件或搜索股票。市场走弱时，策略也会主动留空。")
            } else {
                ScrollViewReader { proxy in
                    List(selection:Binding(get:{store.selection},set:{store.select($0)})) {
                        ForEach(filtered) { stock in
                            StockRow(stock:stock,starred:store.favorites.contains(stock.id))
                                .tag(stock.id).id(stock.id).listRowInsets(EdgeInsets(top:0,leading:16,bottom:0,trailing:16))
                                .listRowSeparator(.hidden)
                        }
                    }.listStyle(.plain).scrollContentBackground(.hidden).background(.white)
                        .onChange(of:query) { _,_ in if let first=filtered.first { proxy.scrollTo(first.id,anchor:.top) } }
                }
            }
        }.frame(maxWidth:.infinity,maxHeight:.infinity)
    }
}

struct StockRow:View {
    let stock:Stock; let starred:Bool
    var body:some View {
        HStack(spacing:8) {
            VStack(alignment:.leading,spacing:5) {
                HStack(spacing:5) {
                    Text(stock.name).font(.system(size:12,weight:.medium)).lineLimit(1)
                    if starred { Image(systemName:"star.fill").font(.system(size:8)).foregroundStyle(Palette.amber) }
                }
                Text("\(stock.symbol)  ·  \(stock.industry)").font(.system(size:9)).foregroundStyle(Palette.muted).lineLimit(1)
            }.frame(maxWidth:.infinity,alignment:.leading)
            Text(decimal(stock.close)).frame(width:60,alignment:.trailing)
            Text(String(format:"%+.2f%%",stock.change)).foregroundStyle(stock.change>=0 ? Palette.up:Palette.down).frame(width:66,alignment:.trailing)
            Text(stock.eligible ? decimal(stock.score,digits:1):"—").fontWeight(.semibold).foregroundStyle(Palette.teal).frame(width:55,alignment:.trailing)
            Badge(text:stock.state,color:stock.state=="等待" ? Palette.amber:(stock.state=="排除" ? Palette.muted:Palette.teal)).frame(width:46,alignment:.trailing)
        }.font(.system(size:11,design:.rounded)).monospacedDigit().padding(.vertical,13)
            .overlay(alignment:.bottom) { Rectangle().fill(Palette.line.opacity(0.45)).frame(height:0.5) }
            .accessibilityElement(children:.combine)
    }
}
