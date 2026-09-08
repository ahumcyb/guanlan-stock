import SwiftUI

struct StockChart:View {
    let candles:[Candle]
    let signalDate:String
    let signalLabel:String
    let reference:Double?
    let invalidation:Double?
    @State private var count=60
    @State private var hover: Int?
    private var visible:[Candle] { Array(candles.suffix(count)) }
    var body:some View {
        VStack(alignment:.leading,spacing:10) {
            HStack {
                Text("日 K").font(.system(size:12,weight:.semibold))
                Spacer()
                ForEach([30,60,120],id:\.self) { n in
                    Button("\(n) 日") { count=n; hover=nil }
                        .buttonStyle(.plain).font(.system(size:10,weight:count==n ? .semibold:.regular))
                        .foregroundStyle(count==n ? Palette.teal:Palette.muted)
                        .padding(.horizontal,5).padding(.vertical,3)
                        .background(count==n ? Palette.selected:Color.clear,in:RoundedRectangle(cornerRadius:3))
                }
            }
            HStack(spacing:12) {
                Text("MA10").foregroundStyle(.blue.opacity(0.65))
                Text("MA20").foregroundStyle(Palette.amber)
                Text("MA60").foregroundStyle(Palette.teal)
                Spacer()
                Text("连续价格").foregroundStyle(Palette.muted)
            }.font(.system(size:9))
            GeometryReader { geometry in
                Canvas { context,size in draw(context:context,size:size,bars:visible) }
                    .onContinuousHover { phase in
                        if case .active(let location)=phase {
                            hover = max(0,min(visible.count-1,Int(location.x / max(1,geometry.size.width-42) * Double(visible.count))))
                        } else { hover=nil }
                    }
            }.frame(height:215)
                .accessibilityLabel("\(visible.count) 个交易日日 K 线，包含均线、成交量、\(signalLabel)日期、位置参考与失效参考")
            HStack(spacing:10) {
                Text("\(signalLabel) \(dateText(signalDate))");Spacer()
                Text("参考 \(decimal(reference))").foregroundStyle(.blue)
                Text("失效 \(decimal(invalidation))").foregroundStyle(Palette.amber)
            }.font(.system(size:9)).foregroundStyle(Palette.muted)
            if let bar = hover.flatMap({ visible.indices.contains($0) ? visible[$0] : nil }) ?? visible.last {
                HStack(spacing:8) {
                    Text(dateText(bar.date))
                    Text("开 \(decimal(bar.open))")
                    Text("收 \(decimal(bar.close))")
                }.font(.system(size:9,design:.monospaced)).foregroundStyle(Palette.muted)
            }
        }
    }

    private func draw(context:GraphicsContext,size:CGSize,bars:[Candle]) {
        guard !bars.isEmpty else { return }
        let chartWidth=size.width-42, chartHeight=size.height-52
        let markers:[Double]=[reference,invalidation].compactMap{$0}.filter{$0.isFinite && $0>0}
        let barValues:[Double]=bars.flatMap { bar in [bar.high,bar.low,bar.ma20 ?? bar.close,bar.ma60 ?? bar.close] }
        let values=barValues+markers
        let minimum=(values.min() ?? 0)*0.99, maximum=(values.max() ?? 1)*1.01
        let span=max(maximum-minimum,0.01), step=chartWidth/Double(bars.count)
        func y(_ p:Double)->Double { 6+(maximum-p)/span*(chartHeight-12) }
        for i in 0...3 {
            let price=minimum+span*Double(i)/3, position=y(price)
            var path=Path(); path.move(to:CGPoint(x:0,y:position)); path.addLine(to:CGPoint(x:chartWidth,y:position))
            context.stroke(path,with:.color(Palette.line.opacity(0.6)),style:StrokeStyle(lineWidth:0.5,dash:[3,3]))
            context.draw(Text(decimal(price)).font(.system(size:9,design:.monospaced)).foregroundStyle(Palette.muted),
                         at:CGPoint(x:chartWidth+6,y:position),anchor:.leading)
        }
        let volumeMax=max(bars.map(\.volume).max() ?? 1,1)
        for (i,bar) in bars.enumerated() {
            let x=step*(Double(i)+0.5), color=bar.close>=bar.open ? Palette.up:Palette.down
            var wick=Path(); wick.move(to:CGPoint(x:x,y:y(bar.high))); wick.addLine(to:CGPoint(x:x,y:y(bar.low)))
            context.stroke(wick,with:.color(color),lineWidth:0.7)
            let body=CGRect(x:x-step*0.29,y:min(y(bar.open),y(bar.close)),width:max(step*0.58,1),height:max(abs(y(bar.open)-y(bar.close)),1))
            context.fill(Path(body),with:.color(color))
            let height=bar.volume/volumeMax*30
            context.fill(Path(CGRect(x:x-step*0.29,y:size.height-12-height,width:max(step*0.58,1),height:height)),with:.color(color.opacity(0.35)))
        }
        for (key,color) in [(\Candle.ma10,Color.blue.opacity(0.6)),(\Candle.ma20,Palette.amber),(\Candle.ma60,Palette.teal)] {
            var path=Path(); var started=false
            for (i,bar) in bars.enumerated() {
                if let value=bar[keyPath:key] {
                    let p=CGPoint(x:step*(Double(i)+0.5),y:y(value))
                    if started { path.addLine(to:p) } else { path.move(to:p); started=true }
                }
            }
            context.stroke(path,with:.color(color),lineWidth:1)
        }
        for (value,color) in [(reference,Color.blue),(invalidation,Palette.amber)] {
            if let value,value.isFinite,value>0 {
                var line=Path();line.move(to:CGPoint(x:0,y:y(value)));line.addLine(to:CGPoint(x:chartWidth,y:y(value)))
                context.stroke(line,with:.color(color.opacity(0.8)),style:StrokeStyle(lineWidth:1,dash:[5,3]))
            }
        }
        if let index=bars.firstIndex(where:{$0.date==signalDate}) {
            let x=step*(Double(index)+0.5)
            var marker=Path();marker.move(to:CGPoint(x:x,y:4));marker.addLine(to:CGPoint(x:x,y:chartHeight))
            context.stroke(marker,with:.color(Palette.ink.opacity(0.55)),style:StrokeStyle(lineWidth:1,dash:[2,3]))
            context.draw(Text(signalLabel).font(.system(size:9,weight:.semibold)),at:CGPoint(x:max(45,x-3),y:5),anchor:.topTrailing)
        }
        context.draw(Text(String(bars.first!.date.suffix(4))).font(.system(size:8)).foregroundStyle(Palette.muted),at:CGPoint(x:0,y:size.height-2),anchor:.leading)
        context.draw(Text(String(bars.last!.date.suffix(4))).font(.system(size:8)).foregroundStyle(Palette.muted),at:CGPoint(x:chartWidth,y:size.height-2),anchor:.trailing)
    }
}
