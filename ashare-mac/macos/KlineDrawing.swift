import SwiftUI

enum KlineColors {
    private static func adaptive(_ light:(Double,Double,Double),_ dark:(Double,Double,Double))->Color {
        #if os(iOS)
        return Color(uiColor:UIColor { traits in
            let c=traits.userInterfaceStyle == .dark ? dark:light
            return UIColor(red:CGFloat(c.0),green:CGFloat(c.1),blue:CGFloat(c.2),alpha:1)
        })
        #else
        return Color(nsColor:NSColor(name:nil) { appearance in
            let c=appearance.bestMatch(from:[.darkAqua,.aqua]) == .darkAqua ? dark:light
            return NSColor(srgbRed:CGFloat(c.0),green:CGFloat(c.1),blue:CGFloat(c.2),alpha:1)
        })
        #endif
    }
    static let up=adaptive((0.79,0.25,0.22),(0.98,0.46,0.42))
    static let down=adaptive((0.13,0.51,0.38),(0.33,0.78,0.59))
    static let accent=adaptive((0.12,0.43,0.37),(0.43,0.79,0.69))
    static let amber=adaptive((0.65,0.42,0.10),(0.94,0.71,0.34))
    static let blue=adaptive((0.12,0.40,0.75),(0.45,0.72,1.0))
    static let tagSurface=adaptive((0.96,0.98,0.97),(0.13,0.18,0.17))
    static let selectionSurface=adaptive((0.86,0.94,0.90),(0.18,0.34,0.29))
    static let grid=Color.primary.opacity(0.10)
    static func change(_ value:Double)->Color { value>=0 ? up:down }
    static func ma(_ value:Int)->Color { value==10 ? blue:(value==20 ? amber:accent) }
}

struct KlineLayout {
    let price:CGRect;let secondary:CGRect;let axisY:CGFloat
    init(_ size:CGSize) {
        let width=max(1,size.width-76),usable=max(100,size.height-38)
        let priceHeight=usable*0.72
        price=CGRect(x:5,y:8,width:width,height:priceHeight)
        secondary=CGRect(x:5,y:price.maxY+17,width:width,height:max(25,usable-priceHeight-17))
        axisY=size.height-9
    }
    func x(_ index:Int,in range:Range<Int>)->CGFloat {
        price.minX+price.width*(CGFloat(index-range.lowerBound)+0.5)/CGFloat(max(1,range.count))
    }
}

struct KlinePlot:View {
    let series:ChartSeries;let range:Range<Int>;let averages:Set<Int>;let pane:ChartPane
    let selected:Int?;let cursorFraction:Double?;let reference:Double?;let invalidation:Double?
    let focusIndex:Int?;let focusPrice:Double?;let focusLabel:String
    private var bars:[ChartPoint] { Array(series.bars[range]) }
    private var domain:ChartDomain {
        ChartDomain(prices:bars.flatMap { [$0.high,$0.low]+averages.compactMap($0.ma) })
    }
    var body:some View {
        Canvas { context,size in
            guard !range.isEmpty,range.lowerBound>=0,range.upperBound<=series.bars.count else { return }
            let layout=KlineLayout(size),scale=domain
            drawPrice(context,layout:layout,scale:scale)
            drawPane(context,layout:layout)
            drawDates(context,layout:layout)
            if let selected,range.contains(selected) {
                let x=layout.x(selected,in:range)
                var cross=Path();cross.move(to:CGPoint(x:x,y:layout.price.minY));cross.addLine(to:CGPoint(x:x,y:layout.secondary.maxY))
                context.stroke(cross,with:.color(.primary.opacity(0.55)),style:StrokeStyle(lineWidth:1,dash:[3,3]))
                let price=cursorFraction.map(scale.price) ?? series.bars[selected].close
                let y=layout.price.minY+CGFloat(scale.fraction(price))*layout.price.height
                horizontal(context,y:y,rect:layout.price,color:.primary.opacity(0.45),dash:[3,3])
                tag(context,text:chartPrice(price),at:CGPoint(x:layout.price.maxX+4,y:y),color:KlineColors.accent)
                let day=series.bars[selected].date
                let label=series.period == .month ? shortDate(day):String(day.dropFirst(2).prefix(2))+"/"+String(day.dropFirst(4).prefix(2))+"/"+String(day.suffix(2))
                let labelX=min(max(x,32),layout.price.maxX-30)
                context.fill(Path(roundedRect:CGRect(x:labelX-30,y:layout.axisY-9,width:60,height:18),cornerRadius:3),with:.color(KlineColors.selectionSurface))
                context.draw(Text(label).font(.system(size:10,weight:.medium,design:.monospaced)).foregroundStyle(.primary),at:CGPoint(x:labelX,y:layout.axisY))
            }
        }
    }
    private func horizontal(_ context:GraphicsContext,y:CGFloat,rect:CGRect,color:Color,dash:[CGFloat]=[]) {
        var path=Path();path.move(to:CGPoint(x:rect.minX,y:y));path.addLine(to:CGPoint(x:rect.maxX,y:y))
        context.stroke(path,with:.color(color),style:StrokeStyle(lineWidth:0.7,dash:dash))
    }
    private func tag(_ context:GraphicsContext,text:String,at point:CGPoint,color:Color) {
        let box=CGRect(x:point.x,y:point.y-8,width:66,height:16)
        context.fill(Path(roundedRect:box,cornerRadius:3),with:.color(KlineColors.tagSurface))
        context.draw(Text(text).font(.system(size:9,weight:.medium,design:.monospaced)).foregroundStyle(color),at:CGPoint(x:point.x+3,y:point.y),anchor:.leading)
    }
    private func drawPrice(_ context:GraphicsContext,layout:KlineLayout,scale:ChartDomain) {
        let rect=layout.price,step=rect.width/CGFloat(range.count)
        func y(_ price:Double)->CGFloat { rect.minY+CGFloat(scale.fraction(price))*rect.height }
        let markers:[(String,Double,Color)]=[("参考",reference,KlineColors.blue),("失效",invalidation,KlineColors.amber)]
            .compactMap { name,value,color in value.map{(name,$0,color)} }
        let markerYs=markers.map{min(rect.maxY-8,max(rect.minY+8,y($0.1)))}
        for price in scale.ticks {
            let position=y(price)
            horizontal(context,y:position,rect:rect,color:KlineColors.grid,dash:[3,4])
            if !markerYs.contains(where:{abs($0-position)<13}) {
                context.draw(Text(String(format:"%.*f",max(2,scale.decimals),price)).font(.system(size:10,design:.monospaced)).foregroundStyle(.secondary),at:CGPoint(x:rect.maxX+6,y:position),anchor:.leading)
            }
        }
        var layer=context;layer.clip(to:Path(rect))
        for index in range {
            let bar=series.bars[index],x=layout.x(index,in:range),color=KlineColors.change(bar.close-bar.open)
            var wick=Path();wick.move(to:CGPoint(x:x,y:y(bar.high)));wick.addLine(to:CGPoint(x:x,y:y(bar.low)))
            layer.stroke(wick,with:.color(color),lineWidth:step<2 ? 0.6:1)
            let width=max(0.5,min(step*0.65,16)),height=max(1,abs(y(bar.close)-y(bar.open)))
            layer.fill(Path(CGRect(x:x-width/2,y:min(y(bar.close),y(bar.open)),width:width,height:height)),with:.color(color))
        }
        for period in averages.sorted() {
            var path=Path(),started=false
            for index in range {
                guard let value=series.bars[index].ma(period) else { started=false;continue }
                let point=CGPoint(x:layout.x(index,in:range),y:y(value))
                if started { path.addLine(to:point) } else { path.move(to:point);started=true }
            }
            layer.stroke(path,with:.color(KlineColors.ma(period)),lineWidth:1.15)
        }
        if let latest=series.bars.last,range.upperBound==series.bars.count {
            horizontal(layer,y:y(latest.close),rect:rect,color:KlineColors.change(latest.change ?? 0).opacity(0.5),dash:[2,4])
            if selected==nil && !markerYs.contains(where:{abs($0-y(latest.close))<16}) {
                tag(context,text:chartPrice(latest.close),at:CGPoint(x:rect.maxX+4,y:y(latest.close)),color:KlineColors.change(latest.change ?? 0))
            }
        }
        let ordered=markers.sorted(by:{$0.1>$1.1})
        var positions=ordered.map { min(rect.maxY-8,max(rect.minY+8,y($0.1))) }
        if positions.count>1 { for index in 1..<positions.count { positions[index]=max(positions[index],positions[index-1]+18) } }
        let overflow=max(0,(positions.last ?? 0)-(rect.maxY-8))
        for (index,item) in ordered.enumerated() {
            let (name,price,color)=item,actual=y(price)
            let at=min(rect.maxY-8,max(rect.minY+8,actual))
            horizontal(layer,y:at,rect:rect,color:color.opacity(0.7),dash:[5,4])
            let labelY=positions[index]-overflow
            let direction=actual<rect.minY ? "↑":(actual>rect.maxY ? "↓":"")
            let cursorY=selected.flatMap { index -> CGFloat? in
                guard range.contains(index) else { return nil }
                return y(cursorFraction.map(scale.price) ?? series.bars[index].close)
            }
            if cursorY.map({abs($0-labelY)>=17}) ?? true {
                tag(context,text:direction+name+chartPrice(price),at:CGPoint(x:rect.maxX+4,y:labelY),color:color)
            }
        }
        if let index=focusIndex,range.contains(index) {
            let x=layout.x(index,in:range)
            var path=Path();path.move(to:CGPoint(x:x,y:rect.minY));path.addLine(to:CGPoint(x:x,y:layout.secondary.maxY))
            context.stroke(path,with:.color(KlineColors.accent.opacity(0.65)),style:StrokeStyle(lineWidth:1,dash:[2,5]))
            if let focusPrice {
                let position=min(rect.maxY-4,max(rect.minY+4,y(focusPrice)))
                context.fill(Path(ellipseIn:CGRect(x:x-3,y:position-3,width:6,height:6)),with:.color(KlineColors.accent))
            }
            let point=CGPoint(x:min(max(x,45),rect.maxX-45),y:rect.minY+5)
            context.draw(Text(focusLabel).font(.system(size:10,weight:.semibold)).foregroundStyle(KlineColors.accent),at:point,anchor:.top)
        }
    }
    private func drawPane(_ context:GraphicsContext,layout:KlineLayout) {
        let rect=layout.secondary,step=rect.width/CGFloat(range.count)
        horizontal(context,y:rect.minY-7,rect:rect,color:KlineColors.grid)
        if pane == .volume {
            let actualMaximum=bars.map(\.volume).max() ?? 0,maximum=max(actualMaximum,1)
            for index in range {
                let bar=series.bars[index],height=CGFloat(bar.volume/maximum)*rect.height,width=max(0.5,min(step*0.65,16))
                context.fill(Path(CGRect(x:layout.x(index,in:range)-width/2,y:rect.maxY-height,width:width,height:height)),with:.color(KlineColors.change(bar.close-bar.open).opacity(index==selected ? 0.9:0.5)))
            }
            context.draw(Text(chartVolume(actualMaximum)).font(.system(size:9,design:.monospaced)).foregroundStyle(.secondary),at:CGPoint(x:rect.maxX+5,y:rect.minY+5),anchor:.leading)
        } else if pane == .rsi {
            for value in [30.0,70.0] {
                let y=rect.maxY-CGFloat(value/100)*rect.height
                horizontal(context,y:y,rect:rect,color:KlineColors.grid,dash:[3,3])
                context.draw(Text(String(Int(value))).font(.system(size:9,design:.monospaced)).foregroundStyle(.secondary),at:CGPoint(x:rect.maxX+5,y:y),anchor:.leading)
            }
            drawLine(context,layout:layout,values:series.bars.map(\.rsi),color:KlineColors.accent) { rect.maxY-CGFloat($0/100)*rect.height }
        } else {
            let values=bars.compactMap(\.macd),scale=ChartDomain(prices:values.flatMap{[$0.dif,$0.dea,$0.histogram]}+[0],tickCount:3,includeZero:true)
            func y(_ value:Double)->CGFloat { rect.minY+CGFloat(scale.fraction(value))*rect.height }
            horizontal(context,y:y(0),rect:rect,color:KlineColors.grid)
            for index in range {
                guard let value=series.bars[index].macd?.histogram else { continue }
                let width=max(0.5,min(step*0.65,16))
                context.fill(Path(CGRect(x:layout.x(index,in:range)-width/2,y:min(y(0),y(value)),width:width,height:max(0.5,abs(y(value)-y(0))))),with:.color(KlineColors.change(value).opacity(0.65)))
            }
            drawLine(context,layout:layout,values:series.bars.map{$0.macd?.dif},color:KlineColors.blue,y:y)
            drawLine(context,layout:layout,values:series.bars.map{$0.macd?.dea},color:KlineColors.amber,y:y)
            context.draw(Text("0").font(.system(size:9)).foregroundStyle(.secondary),at:CGPoint(x:rect.maxX+5,y:y(0)),anchor:.leading)
        }
    }
    private func drawLine(_ context:GraphicsContext,layout:KlineLayout,values:[Double?],color:Color,y:(Double)->CGFloat) {
        var path=Path(),started=false
        for index in range {
            guard let value=values[index] else { started=false;continue }
            let point=CGPoint(x:layout.x(index,in:range),y:y(value))
            if started { path.addLine(to:point) } else { path.move(to:point);started=true }
        }
        context.stroke(path,with:.color(color),lineWidth:1.1)
    }
    private func shortDate(_ date:String)->String {
        let crossesYear=series.bars[range.lowerBound].date.prefix(4) != series.bars[range.upperBound-1].date.prefix(4)
        return series.period == .month || crossesYear ? String(date.prefix(4))+"/"+String(date.dropFirst(4).prefix(2)):String(date.dropFirst(4).prefix(2))+"/"+String(date.suffix(2))
    }
    private func drawDates(_ context:GraphicsContext,layout:KlineLayout) {
        let count=min(layout.price.width>600 ? 6:3,range.count-1)
        for step in 0...count {
            let index=count==0 ? range.lowerBound:range.lowerBound+Int((Double(range.count-1)*Double(step)/Double(count)).rounded())
            let x=layout.x(index,in:range),anchor:UnitPoint=count==0 ? .center:(step==0 ? .leading:(step==count ? .trailing:.center))
            context.draw(Text(shortDate(series.bars[index].date)).font(.system(size:9,design:.monospaced)).foregroundStyle(.secondary),at:CGPoint(x:x,y:layout.axisY),anchor:anchor)
        }
    }
}
