import Foundation

enum ChartGestureDirection {
    static func horizontal(x:Double,y:Double)->Bool { x.isFinite && y.isFinite && abs(x)>abs(y)*1.2 }
}

struct ChartViewOptions:Identifiable {
    let id=UUID()
    let period:ChartPeriod;let basis:ChartPriceBasis;let pane:ChartPane;let averages:Set<Int>
    let count:Int;let start:Int;let selectedDate:String?
}

struct ChartMACD:Equatable,Sendable { let dif:Double;let dea:Double;var histogram:Double{2*(dif-dea)} }
enum ChartIndicators {
    static func average(_ prices:[Double],period:Int)->[Double?] {
        var sum=0.0;return prices.enumerated().map { index,value in
            sum+=value;if index>=period { sum-=prices[index-period] }
            return index>=period-1 ? sum/Double(period):nil
        }
    }
    static func ema(_ prices:[Double],period:Int)->[Double] {
        guard let first=prices.first else { return [] }
        var previous=first;let alpha=2/Double(period+1)
        return prices.enumerated().map { index,value in previous=index==0 ? value:alpha*value+(1-alpha)*previous;return previous }
    }
    static func macd(_ prices:[Double])->[ChartMACD?] {
        let fast=ema(prices,period:12),slow=ema(prices,period:26)
        let dif=zip(fast,slow).map(-),signal=ema(dif,period:9)
        return prices.indices.map { $0<33 ? nil:ChartMACD(dif:dif[$0],dea:signal[$0]) }
    }
    static func rsi(_ prices:[Double],period:Int=14)->[Double?] {
        var result=[Double?](repeating:nil,count:prices.count);guard prices.count>period else { return result }
        var gain=0.0,loss=0.0
        for i in 1...period { let change=prices[i]-prices[i-1];gain+=max(change,0);loss+=max(-change,0) }
        gain/=Double(period);loss/=Double(period)
        func value()->Double { gain+loss<=1e-14 ? 50:(loss<=1e-14 ? 100:100-100/(1+gain/loss)) }
        result[period]=value()
        if prices.count>period+1 {
            for i in (period+1)..<prices.count {
                let change=prices[i]-prices[i-1]
                gain=(gain*Double(period-1)+max(change,0))/Double(period)
                loss=(loss*Double(period-1)+max(-change,0))/Double(period);result[i]=value()
            }
        }
        return result
    }
}

struct ChartPoint:Sendable,Identifiable {
    let startDate:String;let date:String;let open:Double;let high:Double;let low:Double;let close:Double
    let previousClose:Double?;let volume:Double;let amount:Double?;let observations:Int
    var ma10:Double?;var ma20:Double?;var ma60:Double?;var macd:ChartMACD?;var rsi:Double?
    var id:String { date }
    var change:Double? { previousClose.flatMap{$0>0 ? (close/$0-1)*100:nil} }
    var amplitude:Double? { previousClose.flatMap{$0>0 ? (high-low)/$0*100:nil} }
    func ma(_ period:Int)->Double? { [10:ma10,20:ma20,60:ma60][period] ?? nil }
}

struct ChartSeries:Sendable {
    let bars:[ChartPoint];let period:ChartPeriod;let basis:ChartPriceBasis;let asOf:String
    let conversion:[String:Double];let availableDates:Set<String>;let notice:String?
    func index(for date:String)->Int? {
        guard availableDates.contains(date) else { return nil }
        return bars.firstIndex{$0.startDate<=date && date<=$0.date}
    }
    func focusPrice(_ raw:Double,date:String)->Double? {
        guard let scale=conversion[date],scale.isFinite,raw.isFinite,raw>0 else { return nil }
        let result=raw*scale
        return result.isFinite && result>0 ? result:nil
    }
    static func make(_ data:ChartDataset,period:ChartPeriod,basis:ChartPriceBasis,through:String?=nil)->ChartSeries {
        let cutoff=min(data.asOf,through ?? data.asOf)
        let input=data.bars.filter{$0.date<=cutoff}
        func empty(_ message:String)->ChartSeries { ChartSeries(bars:[],period:period,basis:basis,asOf:cutoff,conversion:[:],availableDates:[],notice:message) }
        guard let last=input.last else { return empty("当前历史不包含这个日期。") }
        if basis == .raw && !data.canUseRaw { return empty("这个旧版归档没有原始价格。") }
        let normalization=through != nil ? (last.rawClose.map{$0/last.close} ?? 1):1
        var groups:[[ChartCandle]]=[]
        for bar in input {
            if let current=groups.last,period.key(current[0].date)==period.key(bar.date) { groups[groups.count-1].append(bar) }
            else { groups.append([bar]) }
        }
        func value(_ bar:ChartCandle,_ key:KeyPath<ChartCandle,Double>,_ raw:KeyPath<ChartCandle,Double?>)->Double {
            basis == .raw ? bar[keyPath:raw]!:bar[keyPath:key]*normalization
        }
        var result:[ChartPoint]=[];var conversion:[String:Double]=[:]
        for bar in input {
            if basis == .raw { conversion[bar.date]=1 }
            else if let raw=bar.rawClose { conversion[bar.date]=bar.close*normalization/raw }
        }
        for rows in groups {
            let first=rows.first!,last=rows.last!
            let close=value(last,\.close,\.rawClose)
            let previous=period == .day ? last.rawPreClose.map { basis == .raw ? $0:$0*(conversion[last.date] ?? 1) } ?? result.last?.close:result.last?.close
            let amounts=rows.compactMap(\.amount)
            result.append(ChartPoint(startDate:first.date,date:last.date,open:value(first,\.open,\.rawOpen),
                high:rows.map{value($0,\.high,\.rawHigh)}.max()!,low:rows.map{value($0,\.low,\.rawLow)}.min()!,close:close,
                previousClose:previous,volume:rows.reduce(0){$0+$1.volume},amount:amounts.count==rows.count ? amounts.reduce(0,+):nil,
                observations:rows.count,ma10:nil,ma20:nil,ma60:nil,macd:nil,rsi:nil))
        }
        let closes=result.map(\.close),ma10=ChartIndicators.average(closes,period:10),ma20=ChartIndicators.average(closes,period:20),ma60=ChartIndicators.average(closes,period:60)
        let macd=ChartIndicators.macd(closes),rsi=ChartIndicators.rsi(closes)
        for i in result.indices {
            result[i].ma10=period == .day && basis == .continuous ? input[i].ma10.map{$0*normalization}:ma10[i]
            result[i].ma20=period == .day && basis == .continuous ? input[i].ma20.map{$0*normalization}:ma20[i]
            result[i].ma60=period == .day && basis == .continuous ? input[i].ma60.map{$0*normalization}:ma60[i]
            result[i].macd=macd[i];result[i].rsi=rsi[i]
        }
        var notice=data.isLegacy ? "旧版归档 · 最多120根日线，缺少原始价格和成交额。":nil
        if data.isLegacy && last.date != data.bars.last?.date {
            notice=(notice ?? "")+"此历史视图仍沿用 \(ChartDate.label(data.asOf)) 的连续价格基准。"
        }
        return ChartSeries(bars:result,period:period,basis:basis,asOf:cutoff,conversion:conversion,availableDates:Set(input.map(\.date)),notice:notice)
    }
}

struct ChartViewport:Equatable {
    private(set) var total:Int;private(set) var count:Int;private(set) var start:Int
    init(total:Int,count:Int) {
        self.total=max(total,0);self.count=min(max(count,1),max(total,0));start=max(0,total-self.count)
    }
    var range:Range<Int> { start..<min(total,start+count) }
    mutating func pan(by offset:Int) { start=max(0,min(max(0,total-count),start+offset)) }
    mutating func latest() { start=max(0,total-count) }
    mutating func focus(index:Int) { start=max(0,min(max(0,total-count),index-count/2)) }
    mutating func zoom(to requested:Int,anchor:Double=0.5) {
        let fraction=max(0,min(1,anchor));let index=Double(start)+Double(max(0,count-1))*fraction
        count=min(total,max(1,requested));start=max(0,min(max(0,total-count),Int((index-Double(max(0,count-1))*fraction).rounded())))
    }
    func index(at x:Double,width:Double)->Int? {
        guard total>0,count>0,x.isFinite,width.isFinite,width>0 else { return nil }
        return start+min(count-1,max(0,Int((min(max(x,0),width)/width*Double(count)).rounded(.down))))
    }
}

struct ChartDomain {
    let minimum:Double;let maximum:Double;let ticks:[Double];let decimals:Int
    init(prices:[Double],tickCount:Int=5,includeZero:Bool=false) {
        let values=prices.filter{$0.isFinite};let baseLow=values.min() ?? 0,baseHigh=values.max() ?? 1
        let span=max(baseHigh-baseLow,max(abs(baseHigh)*0.002,0.00001));let padding=span*0.08
        let low=includeZero ? min(0,baseLow-padding):max(0,baseLow-padding)
        let high=max(baseHigh+padding,low+0.00001)
        let raw=(high-low)/Double(max(2,tickCount)-1),power=pow(10,floor(log10(raw)))
        let step=([1.0,2.0,2.5,5.0,10.0].first(where:{$0*power>=raw}) ?? 10)*power
        let bottom=floor(low/step)*step,top=ceil(high/step)*step
        minimum=bottom;maximum=max(top,bottom+step);decimals=min(6,max(0,Int(ceil(-log10(step)))))
        let count=min(12,Int(((maximum-minimum)/step).rounded())+1)
        ticks=(0..<count).map{bottom+Double($0)*step}
    }
    func fraction(_ price:Double)->Double { (maximum-price)/(maximum-minimum) }
    func price(at fraction:Double)->Double { maximum-max(0,min(1,fraction))*(maximum-minimum) }
}
