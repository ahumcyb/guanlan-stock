import SwiftUI

struct MobileCandleChart:View {
    let candles:[Candle]
    @State private var count=60
    @State private var selected:Int?
    private var bars:[Candle] { Array(candles.suffix(count)) }
    var body:some View {
        VStack(alignment:.leading,spacing:10) {
            HStack { Text("日 K").font(.headline);Spacer();ForEach([30,60,120],id:\.self) { value in Button("\(value)日") { count=value;selected=nil }.font(.caption.weight(count==value ? .bold:.regular)).frame(minWidth:44,minHeight:44).buttonStyle(.plain).foregroundStyle(count==value ? MobileTheme.teal:.secondary) } }
            HStack(spacing:14) { Text("MA10").foregroundStyle(.blue);Text("MA20").foregroundStyle(MobileTheme.amber);Text("MA60").foregroundStyle(MobileTheme.teal);Spacer();Text("拖动查看").foregroundStyle(.secondary) }.font(.caption2)
            GeometryReader { geometry in
                Canvas { context,size in draw(context,size:size) }
                    .contentShape(Rectangle())
                    .simultaneousGesture(DragGesture(minimumDistance:0).onChanged { value in selected=max(0,min(bars.count-1,Int(value.location.x/max(1,geometry.size.width-44)*Double(bars.count)))) })
            }.frame(height:240).accessibilityLabel("\(bars.count) 个交易日日 K、均线和成交量；下方显示选中日期价格")
            if let bar=selected.flatMap({bars.indices.contains($0) ? bars[$0]:nil}) ?? bars.last {
                VStack(alignment:.leading,spacing:5) {
                    Text(dateText(bar.date)).font(.caption.weight(.medium))
                    HStack { Text("开 \(decimal(bar.open))");Text("高 \(decimal(bar.high))");Text("低 \(decimal(bar.low))");Text("收 \(decimal(bar.close))") }.font(.caption2.monospacedDigit()).foregroundStyle(.secondary).minimumScaleFactor(0.7).lineLimit(1)
                }
            }
        }
    }
    private func draw(_ context:GraphicsContext,size:CGSize) {
        guard !bars.isEmpty else { return }
        let width=max(1,size.width-44),height=size.height-48
        let values=bars.flatMap{[$0.high,$0.low,$0.ma10 ?? $0.close,$0.ma20 ?? $0.close,$0.ma60 ?? $0.close]}
        let low=(values.min() ?? 0)*0.99,high=(values.max() ?? 1)*1.01,span=max(0.01,high-low),step=width/Double(bars.count)
        func y(_ price:Double)->Double { 6+(high-price)/span*(height-12) }
        for index in 0...3 {
            let price=low+span*Double(index)/3,position=y(price)
            var path=Path();path.move(to:CGPoint(x:0,y:position));path.addLine(to:CGPoint(x:width,y:position))
            context.stroke(path,with:.color(MobileTheme.line),style:StrokeStyle(lineWidth:0.5,dash:[3,3]))
            context.draw(Text(decimal(price)).font(.system(size:9,design:.monospaced)).foregroundStyle(.secondary),at:CGPoint(x:width+5,y:position),anchor:.leading)
        }
        let maxVolume=max(bars.map(\.volume).max() ?? 1,1)
        for (index,bar) in bars.enumerated() {
            let x=step*(Double(index)+0.5),color=bar.close>=bar.open ? MobileTheme.up:MobileTheme.down
            var wick=Path();wick.move(to:CGPoint(x:x,y:y(bar.high)));wick.addLine(to:CGPoint(x:x,y:y(bar.low)))
            context.stroke(wick,with:.color(color),lineWidth:0.8)
            let rect=CGRect(x:x-step*0.3,y:min(y(bar.open),y(bar.close)),width:max(1,step*0.6),height:max(1,abs(y(bar.open)-y(bar.close))))
            context.fill(Path(rect),with:.color(color))
            let volume=bar.volume/maxVolume*30
            context.fill(Path(CGRect(x:x-step*0.3,y:size.height-8-volume,width:max(1,step*0.6),height:volume)),with:.color(color.opacity(0.4)))
        }
        for (key,color) in [(\Candle.ma10,Color.blue),(\Candle.ma20,MobileTheme.amber),(\Candle.ma60,MobileTheme.teal)] {
            var line=Path();var started=false
            for (index,bar) in bars.enumerated() { if let value=bar[keyPath:key] { let point=CGPoint(x:step*(Double(index)+0.5),y:y(value));if started { line.addLine(to:point) } else { line.move(to:point);started=true } } }
            context.stroke(line,with:.color(color),lineWidth:1)
        }
        if let selected,bars.indices.contains(selected) {
            let x=step*(Double(selected)+0.5);var line=Path();line.move(to:CGPoint(x:x,y:0));line.addLine(to:CGPoint(x:x,y:size.height))
            context.stroke(line,with:.color(.secondary),style:StrokeStyle(lineWidth:1,dash:[3,3]))
        }
    }
}
