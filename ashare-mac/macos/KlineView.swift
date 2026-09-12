import SwiftUI

struct KlineView:View {
    let data:ChartDataset
    var focus:ChartFocus?=nil
    var reference:Double?=nil
    var invalidation:Double?=nil
    var referenceDate:String?=nil
    var through:String?=nil
    var compactHeight=false
    var plotHeight:CGFloat=320
    var initialState:ChartViewOptions?=nil
    var onExpand:((ChartViewOptions)->Void)?=nil
    @State private var period:ChartPeriod = .day
    @State private var basis:ChartPriceBasis = .continuous
    @State private var pane:ChartPane = .volume
    @State private var averages:Set<Int>=[10,20,60]
    @State private var series:ChartSeries?
    @State private var viewport=ChartViewport(total:0,count:60)
    @State private var selectedDate:String?
    @State private var cursorFraction:Double?
    @State private var pinned=false
    @State private var dragOrigin:ChartViewport?
    @State private var zoomOrigin:ChartViewport?
    @State private var renderedData:UUID?
    @State private var renderedPeriod:ChartPeriod?
    @FocusState private var chartFocused:Bool
    @Environment(\.dynamicTypeSize) private var typeSize
    init(data:ChartDataset,focus:ChartFocus?=nil,reference:Double?=nil,invalidation:Double?=nil,referenceDate:String?=nil,
         through:String?=nil,compactHeight:Bool=false,plotHeight:CGFloat=320,initialState:ChartViewOptions?=nil,
         onExpand:((ChartViewOptions)->Void)?=nil) {
        self.data=data;self.focus=focus;self.reference=reference;self.invalidation=invalidation;self.referenceDate=referenceDate
        self.through=through;self.compactHeight=compactHeight;self.plotHeight=plotHeight;self.initialState=initialState;self.onExpand=onExpand
        _period=State(initialValue:initialState?.period ?? .day);_basis=State(initialValue:initialState?.basis ?? .continuous)
        _pane=State(initialValue:initialState?.pane ?? .volume);_averages=State(initialValue:initialState?.averages ?? [10,20,60])
        _selectedDate=State(initialValue:initialState?.selectedDate)
        _pinned=State(initialValue:initialState?.selectedDate != nil)
    }
    private var renderKey:String { data.id.uuidString+period.rawValue+basis.rawValue+(through ?? "") }
    private var selectedIndex:Int? { selectedDate.flatMap{series?.index(for:$0)} }
    private var reading:ChartPoint? {
        guard let series,!series.bars.isEmpty else { return nil }
        if let index=selectedIndex,viewport.range.contains(index) { return series.bars[index] }
        return series.bars[min(max(0,viewport.range.upperBound-1),series.bars.count-1)]
    }
    var body:some View {
        VStack(alignment:.leading,spacing:compactHeight ? 5:10) {
            controls
            if let reading {
                readout(reading)
                HStack(spacing:8) {
                    ForEach([10,20,60],id:\.self) { value in
                        Button { if averages.contains(value) { averages.remove(value) } else { averages.insert(value) } } label: {
                            Text("MA\(value) \(chartPrice(reading.ma(value)))").font(.system(size:10,weight:.medium,design:.monospaced))
                        }.buttonStyle(.plain).foregroundStyle(averages.contains(value) ? KlineColors.ma(value):.secondary)
                            .accessibilityLabel("\(averages.contains(value) ? "隐藏":"显示")\(value)\(period.unit)均线")
                    }
                    Spacer(minLength:0)
                }
            }
            if let series,!series.bars.isEmpty {
                plot(series).frame(height:plotHeight)
                navigation
                paneReadout
                if reference != nil || invalidation != nil {
                    let date=referenceDate ?? data.bars.last?.date ?? data.asOf
                    HStack(spacing:16) {
                        if let reference { Text("参考 "+chartPrice(series.focusPrice(reference,date:date))).foregroundStyle(KlineColors.blue) }
                        if let invalidation { Text("失效 "+chartPrice(series.focusPrice(invalidation,date:date))).foregroundStyle(KlineColors.amber) }
                        Spacer()
                    }.font(.caption2.monospacedDigit())
                }
                if !compactHeight {
                    Text("日线截至 \(ChartDate.label(series.bars.last!.date)) · 可用 \(series.availableDates.count) 根日线\(period == .day ? "":" · 聚合末根截至数据日")")
                        .font(.caption2).foregroundStyle(.secondary)
                    if series.bars.last!.date<series.asOf {
                        Text("该股末根日线早于 \(ChartDate.label(series.asOf)) 的数据版本，可能停牌或数据未齐。").font(.caption2).foregroundStyle(KlineColors.amber)
                    }
                    if let focus {
                        Text("\(focus.label) · \(ChartDate.label(focus.date))\(focus.price.map{" · 原始价 "+chartPrice($0)} ?? "")")
                            .font(.caption2).foregroundStyle(KlineColors.accent)
                        if series.index(for:focus.date)==nil { Text("当前历史未包含该日期，未将标记移到其他日期。").font(.caption2).foregroundStyle(KlineColors.amber) }
                        else if focus.price != nil && series.focusPrice(focus.price!,date:focus.date)==nil {
                            Text("这个旧归档只能定位日期，无法把原始提醒价换算到连续价图。").font(.caption2).foregroundStyle(KlineColors.amber)
                        }
                    }
                    if let note=series.notice { Text(note).font(.caption2).foregroundStyle(KlineColors.amber) }
                    DisclosureGroup("价格与指标口径") {
                        Text("连续价按日涨跌链衔接并归一到图表最新收盘，历史数值不等于当时原始成交价。原始价用于价格核对。成交量单位为手；参考/失效价超出视野时以箭头提示。")
                        Text("MA按当前日/周/月周期计算。MACD(12,26,9)柱=2×(DIF−DEA)，前33期不展示；RSI14采用Wilder平滑，历史不足显示—。指标不改变选股规则。")
                        Text("Mac悬停查看、拖拽浏览；手机长按查看，横向滑动浏览。双指缩放，也可使用＋／−与日期导航。")
                    }.font(.caption2).foregroundStyle(.secondary)
                }
            } else if let series { Text(series.notice ?? "没有可显示的K线。").font(.caption).foregroundStyle(.secondary).frame(maxWidth:.infinity,minHeight:180) }
            else { ProgressView("准备图表…").frame(maxWidth:.infinity,minHeight:180) }
        }
        .task(id:renderKey) {
            if basis == .raw && !data.canUseRaw { basis = .continuous;return }
            let input=data,p=period,b=basis,cutoff=through
            let initial=renderedData==nil ? initialState:nil
            let preserved=renderedData==input.id && renderedPeriod==p ? viewport:nil
            let preferred=renderedData==input.id ? selectedDate:(initial != nil ? initial!.selectedDate:focus?.date)
            series=nil
            let result=await Task.detached(priority:.userInitiated) { ChartSeries.make(input,period:p,basis:b,through:cutoff) }.value
            guard !Task.isCancelled else { return }
            series=result;renderedData=input.id;renderedPeriod=p
            viewport=ChartViewport(total:result.bars.count,count:preserved?.count ?? initial?.count ?? (p == .month ? 24:60))
            selectedDate=preferred;cursorFraction=nil;dragOrigin=nil;zoomOrigin=nil
            if let start=preserved?.start ?? initial?.start { viewport.pan(by:start-viewport.start) }
            else if let preferred,let index=result.index(for:preferred) { viewport.focus(index:index) }
        }
    }
    private var controls:some View {
        HStack(spacing:8) {
            Picker("K线周期",selection:$period) { ForEach(ChartPeriod.allCases) { Text($0.label).tag($0) } }
                .pickerStyle(.segmented).frame(maxWidth:190)
            Menu {
                Button("连续价格") { basis = .continuous }
                Button("原始价格") { basis = .raw }.disabled(!data.canUseRaw)
            } label: { Text(basis.label).font(.caption) }
            Spacer(minLength:0)
            if let onExpand {
                Button { onExpand(ChartViewOptions(period:period,basis:basis,pane:pane,averages:averages,count:viewport.count,start:viewport.start,selectedDate:selectedDate)) } label: { Image(systemName:"arrow.up.left.and.arrow.down.right") }
                    .buttonStyle(.plain).frame(minWidth:32,minHeight:32).accessibilityLabel("打开K线大图").disabled(series?.bars.isEmpty != false)
            }
        }
    }
    private func readoutDate(_ point:ChartPoint)->String {
        let prefix=selectedDate==nil ? "窗口末日 ":"选中 "
        if period == .day { return prefix+ChartDate.label(point.date) }
        let end=String(point.date.dropFirst(4).prefix(2))+"/"+String(point.date.suffix(2))
        return prefix+ChartDate.label(point.startDate)+"–"+end
    }
    private func readout(_ point:ChartPoint)->some View {
        VStack(alignment:.leading,spacing:7) {
            HStack {
                Text(readoutDate(point)).font(.caption.monospacedDigit())
                if period != .day { Text("\(point.observations)根日线").font(.caption2).foregroundStyle(.secondary) }
                Spacer(minLength:0)
                Text(point.change.map{String(format:"%+.2f%%",$0)} ?? "—").font(.caption.weight(.semibold)).foregroundStyle(point.change.map(KlineColors.change) ?? .secondary)
            }
            if compactHeight {
                HStack { Text("开 "+chartPrice(point.open));Text("高 "+chartPrice(point.high));Text("低 "+chartPrice(point.low));Text("收 "+chartPrice(point.close));Spacer() }.font(.caption2.monospacedDigit())
            } else {
                LazyVGrid(columns:Array(repeating:GridItem(.flexible(),spacing:8),count:typeSize.isAccessibilitySize ? 2:4),alignment:.leading,spacing:8) {
                    item("开",chartPrice(point.open));item("高",chartPrice(point.high));item("低",chartPrice(point.low));item("收",chartPrice(point.close))
                }
                HStack { item("成交量",chartVolume(point.volume)).frame(maxWidth:.infinity,alignment:.leading);item("成交额",chartAmount(point.amount)).frame(maxWidth:.infinity,alignment:.leading) }
            }
        }
    }
    private func item(_ title:String,_ value:String)->some View {
        VStack(alignment:.leading,spacing:3) { Text(title).font(.caption2).foregroundStyle(.secondary);Text(value).font(.system(size:12,weight:.medium,design:.monospaced)).lineLimit(1).minimumScaleFactor(0.8) }
    }
    private var navigation:some View {
        HStack(spacing:10) {
            Menu("\(viewport.count)根") {
                ForEach([30,60,120,250,500],id:\.self) { count in Button("最近 \(count) 根") { setCount(count) }.disabled((series?.bars.count ?? 0)<count) }
                Button("全部 \(series?.bars.count ?? 0) 根") { setCount(series?.bars.count ?? 1) }
            }.font(.caption)
            Button { setCount(max(10,Int(Double(viewport.count)*0.72))) } label: { Image(systemName:"plus.magnifyingglass") }.accessibilityLabel("放大K线").disabled(viewport.count<=10)
            Button { setCount(max(viewport.count+1,Int(Double(viewport.count)*1.4))) } label: { Image(systemName:"minus.magnifyingglass") }.accessibilityLabel("缩小K线").disabled(viewport.count>=viewport.total)
            Spacer(minLength:0)
            if focus != nil { Button("定位") { locateFocus() }.font(.caption).disabled(focus.flatMap{series?.index(for:$0.date)}==nil).accessibilityLabel("定位原始信号日期") }
            Button("最新") { viewport.latest();selectedDate=nil;cursorFraction=nil;pinned=false }.font(.caption).accessibilityLabel("回到最新K线")
            Button { move(-1) } label: { Image(systemName:"chevron.left") }.accessibilityLabel("上一根K线")
            Button { move(1) } label: { Image(systemName:"chevron.right") }.accessibilityLabel("下一根K线")
        }.buttonStyle(.plain).frame(minHeight:32)
    }
    private var paneReadout:some View {
        HStack(spacing:10) {
            Picker("副图",selection:$pane) { ForEach(ChartPane.allCases) { Text($0.label).tag($0) } }.pickerStyle(.menu).frame(maxWidth:110)
            if pane == .macd {
                if let value=reading?.macd { Text("DIF \(chartPrice(value.dif))  DEA \(chartPrice(value.dea))").font(.caption2.monospacedDigit()) }
                else { Text("至少34根\(period.unit)K").font(.caption2).foregroundStyle(.secondary) }
            } else if pane == .rsi { Text(reading?.rsi.map{String(format:"RSI14 %.2f",$0)} ?? "至少15根\(period.unit)K").font(.caption2.monospacedDigit()) }
            else if let reading { Text("振幅 "+(reading.amplitude.map{String(format:"%.2f%%",$0)} ?? "—")).font(.caption2).foregroundStyle(.secondary) }
            Spacer(minLength:0)
        }.font(.caption)
    }
    private func setCount(_ value:Int) { viewport.zoom(to:value,anchor:viewport.range.upperBound==series?.bars.count ? 1:0.5);cursorFraction=nil }
    private func locateFocus() {
        if let focus,let index=series?.index(for:focus.date) { selectedDate=focus.date;viewport.focus(index:index);cursorFraction=nil;pinned=true }
    }
    private func move(_ offset:Int) {
        guard let series,!series.bars.isEmpty else { return }
        let current=selectedIndex ?? max(0,viewport.range.upperBound-1),next=max(0,min(series.bars.count-1,current+offset))
        selectedDate=series.bars[next].date;cursorFraction=nil;pinned=true
        if !viewport.range.contains(next) { viewport.focus(index:next) }
    }
    private func inspect(_ point:CGPoint,size:CGSize) {
        guard let series else { return };let layout=KlineLayout(size)
        if let index=viewport.index(at:Double(point.x-layout.price.minX),width:Double(layout.price.width)),series.bars.indices.contains(index) {
            selectedDate=series.bars[index].date
            cursorFraction=layout.price.contains(point) ? Double((point.y-layout.price.minY)/layout.price.height):nil
        }
    }
    private func pan(_ translation:CGFloat,size:CGSize) {
        guard translation.isFinite else { return }
        if dragOrigin==nil { dragOrigin=viewport }
        var moved=dragOrigin!;let layout=KlineLayout(size)
        moved.pan(by:Int((-translation/max(1,layout.price.width)*CGFloat(moved.count)).rounded()))
        viewport=moved;selectedDate=nil;cursorFraction=nil;pinned=false
    }
    private func zoom(_ scale:CGFloat,anchor:CGFloat) {
        guard scale.isFinite,anchor.isFinite else { return }
        if zoomOrigin==nil { zoomOrigin=viewport }
        var zoom=zoomOrigin!;zoom.zoom(to:max(10,Int(Double(zoom.count)/Double(max(scale,0.1)))),anchor:Double(anchor))
        viewport=zoom;cursorFraction=nil
    }
    private func plot(_ series:ChartSeries)->some View {
        GeometryReader { proxy in
            let date=referenceDate ?? data.bars.last?.date ?? data.asOf
            KlinePlot(series:series,range:viewport.range,averages:averages,pane:pane,selected:selectedIndex,cursorFraction:cursorFraction,
                reference:reference.flatMap{series.focusPrice($0,date:date)},invalidation:invalidation.flatMap{series.focusPrice($0,date:date)},
                focusIndex:focus.flatMap{series.index(for:$0.date)},focusPrice:focus.flatMap { f in f.price.flatMap{series.focusPrice($0,date:f.date)} },focusLabel:focus?.label ?? "")
                .contentShape(Rectangle())
                #if os(macOS)
                .focusable().focused($chartFocused)
                .onKeyPress(.leftArrow) { move(-1);return .handled }
                .onKeyPress(.rightArrow) { move(1);return .handled }
                .onKeyPress(.escape) {
                    guard selectedDate != nil else { return .ignored }
                    selectedDate=nil;cursorFraction=nil;pinned=false;return .handled
                }
                .simultaneousGesture(SpatialTapGesture().onEnded { value in pinned=true;chartFocused=true;inspect(value.location,size:proxy.size) })
                .simultaneousGesture(DragGesture(minimumDistance:12).onChanged { value in
                    guard ChartGestureDirection.horizontal(x:Double(value.translation.width),y:Double(value.translation.height)) else { return }
                    pan(value.translation.width,size:proxy.size)
                }.onEnded { _ in dragOrigin=nil })
                .simultaneousGesture(MagnifyGesture().onChanged { value in
                    zoom(value.magnification,anchor:value.startAnchor.x)
                }.onEnded { _ in zoomOrigin=nil })
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let point):if dragOrigin==nil && zoomOrigin==nil && !pinned { inspect(point,size:proxy.size) }
                    case .ended:if !pinned { selectedDate=nil;cursorFraction=nil }
                    }
                }
                #else
                .overlay {
                    KlineTouchSurface(inspect:{ point in pinned=true;inspect(point,size:proxy.size) },
                        pan:{ pan($0,size:proxy.size) },panEnd:{ dragOrigin=nil },
                        zoom:{ scale,anchor in zoom(scale,anchor:anchor) },zoomEnd:{ zoomOrigin=nil })
                        .accessibilityHidden(true)
                }
                #endif
                .accessibilityElement(children:.ignore)
                .accessibilityLabel("\(period.label)，\(basis.label)，\(viewport.count)根，\(reading.map{ChartDate.label($0.date)+"收盘"+chartPrice($0.close)} ?? "")")
                .accessibilityValue(reading.map{ChartDate.label($0.date)+"，开盘"+chartPrice($0.open)+"，最高"+chartPrice($0.high)+"，最低"+chartPrice($0.low)+"，收盘"+chartPrice($0.close)} ?? "暂无数据")
                .accessibilityAdjustableAction { direction in move(direction == .increment ? 1:-1) }
        }.background(Color.primary.opacity(0.015),in:RoundedRectangle(cornerRadius:6))
            .overlay(RoundedRectangle(cornerRadius:6).stroke(KlineColors.grid))
    }
}

struct ExpandedKlineView:View {
    let name:String;let data:ChartDataset
    var focus:ChartFocus?=nil;var reference:Double?=nil;var invalidation:Double?=nil;var referenceDate:String?=nil;var through:String?=nil
    var initialState:ChartViewOptions?=nil
    @Environment(\.dismiss) private var dismiss
    var body:some View {
        VStack(spacing:0) {
            HStack { Text(name+" · K线").font(.headline);Spacer();Button("完成") { dismiss() }.keyboardShortcut(.cancelAction) }.padding()
            GeometryReader { proxy in
                ScrollView {
                    KlineView(data:data,focus:focus,reference:reference,invalidation:invalidation,referenceDate:referenceDate,through:through,
                        compactHeight:proxy.size.height<480,plotHeight:proxy.size.height<480 ? max(150,proxy.size.height-190):max(300,proxy.size.height-290),initialState:initialState)
                        .padding(.horizontal,16).padding(.bottom,16)
                }
            }
        }
        #if os(macOS)
        .frame(minWidth:850,idealWidth:1050,minHeight:630,idealHeight:760)
        #endif
    }
}
