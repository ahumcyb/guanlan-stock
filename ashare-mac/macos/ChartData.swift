import Foundation

enum ChartDataError:LocalizedError {
    case invalid, oversized
    var errorDescription:String? { self == .oversized ? "K线数据超过大小限制。":"K线日期、价格或版本没有通过校验。" }
}

enum ChartDate {
    static let calendar:Calendar = {
        var value=Calendar(identifier:.iso8601);value.timeZone=TimeZone(identifier:"Asia/Shanghai")!
        return value
    }()
    static func parse(_ value:String)->Date? {
        guard value.count==8,value.allSatisfy(\.isNumber),let year=Int(value.prefix(4)),
              let month=Int(value.dropFirst(4).prefix(2)),let day=Int(value.suffix(2)),(1900...2200).contains(year),
              let date=calendar.date(from:DateComponents(year:year,month:month,day:day)) else { return nil }
        let parts=calendar.dateComponents([.year,.month,.day],from:date)
        return parts.year==year && parts.month==month && parts.day==day ? date:nil
    }
    static func key(_ date:Date)->String {
        let p=calendar.dateComponents([.year,.month,.day],from:date)
        guard let year=p.year,let month=p.month,let day=p.day else { return "" }
        return String(format:"%04d%02d%02d",year,month,day)
    }
    static func label(_ value:String)->String {
        guard value.count==8 else { return value }
        return "\(value.prefix(4))-\(value.dropFirst(4).prefix(2))-\(value.suffix(2))"
    }
}

struct ChartCandle:Decodable,Equatable,Sendable,Identifiable {
    let date:String;let open:Double;let high:Double;let low:Double;let close:Double
    let ma10:Double?;let ma20:Double?;let ma60:Double?;let volume:Double
    let rawOpen:Double?;let rawHigh:Double?;let rawLow:Double?;let rawClose:Double?;let rawPreClose:Double?;let amount:Double?
    var id:String { date }
    func validate(extended:Bool) throws {
        func prices(_ o:Double,_ h:Double,_ l:Double,_ c:Double)->Bool {
            [o,h,l,c].allSatisfy{$0.isFinite && $0>=0.000001 && $0<1e15}
            && h+1e-6>=max(o,c,l) && l-1e-6<=min(o,c)
        }
        guard ChartDate.parse(date) != nil,prices(open,high,low,close),volume.isFinite,volume>=0,volume<1e18,
              [ma10,ma20,ma60].compactMap({$0}).allSatisfy({$0.isFinite && $0>0 && $0<1e15}) else { throw ChartDataError.invalid }
        if extended {
            guard let ro=rawOpen,let rh=rawHigh,let rl=rawLow,let rc=rawClose,let previous=rawPreClose,let amount,
                  prices(ro,rh,rl,rc),previous.isFinite,previous>0,previous<1e15,amount.isFinite,amount>=0,amount<1e18 else { throw ChartDataError.invalid }
            let scale=close/rc
            for (normal,raw) in [(open,ro),(high,rh),(low,rl)] {
                guard abs(normal-raw*scale)<=max(1e-5,abs(normal)*1e-6) else { throw ChartDataError.invalid }
            }
        }
    }
}

struct ChartDataset:Decodable,Sendable,Identifiable {
    let schemaVersion:Int;let tsCode:String;let asOf:String;let dataRevision:String?
    let priceBasis:String;let volumeUnit:String;let bars:[ChartCandle]
    private(set) var isLegacy=false
    var id=UUID()
    enum CodingKeys:String,CodingKey { case schemaVersion,tsCode,asOf,dataRevision,priceBasis,volumeUnit,bars }
    init(tsCode:String,asOf:String,dataRevision:String?,bars:[ChartCandle],legacy:Bool=false) {
        schemaVersion=1;self.tsCode=tsCode;self.asOf=asOf;self.dataRevision=dataRevision
        priceBasis="continuous_latest_close";volumeUnit="lot";self.bars=bars;isLegacy=legacy
    }
    static func legacy(_ candles:[Candle],code:String,asOf:String,revision:String?)->ChartDataset {
        let bars=candles.enumerated().map { index,c in
            ChartCandle(date:c.date,open:c.open,high:c.high,low:c.low,close:c.close,ma10:c.ma10,ma20:c.ma20,ma60:c.ma60,
                volume:c.volume,rawOpen:nil,rawHigh:nil,rawLow:nil,rawClose:index==candles.count-1 ? c.close:nil,rawPreClose:nil,amount:nil)
        }
        return ChartDataset(tsCode:code,asOf:asOf,dataRevision:revision,bars:bars,legacy:true)
    }
    var canUseRaw:Bool { !isLegacy && bars.allSatisfy{$0.rawOpen != nil && $0.rawClose != nil} }
    func validate(code:String,asOf:String,revision:String?) throws {
        guard schemaVersion==1,tsCode==code,tsCode.range(of:"^[0-9]{6}\\.(SH|SZ|BJ)$",options:.regularExpression) != nil,
              self.asOf==asOf,ChartDate.parse(asOf) != nil,dataRevision==revision,
              priceBasis=="continuous_latest_close",volumeUnit=="lot",!bars.isEmpty,bars.count<=(isLegacy ? 120:500),
              bars.map(\.date)==bars.map(\.date).sorted(),Set(bars.map(\.date)).count==bars.count,
              bars.allSatisfy({$0.date<=asOf}) else { throw ChartDataError.invalid }
        for bar in bars { try bar.validate(extended:!isLegacy) }
        if !isLegacy {
            guard abs(bars.last!.close-bars.last!.rawClose!)<=1e-6 else { throw ChartDataError.invalid }
            for (a,b) in zip(bars,bars.dropFirst()) {
                let ratio=b.rawClose!/b.rawPreClose!,expected=a.close*ratio
                guard abs(b.close-expected)<=2e-6*(1+abs(ratio))+abs(expected)*1e-8 else { throw ChartDataError.invalid }
            }
        }
    }
    static func decode(_ data:Data,code:String,asOf:String,revision:String?) throws -> ChartDataset {
        guard data.count<=512*1024 else { throw ChartDataError.oversized }
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value=try decoder.decode(ChartDataset.self,from:data);try value.validate(code:code,asOf:asOf,revision:revision)
        return value
    }
}

enum ChartPeriod:String,CaseIterable,Identifiable,Sendable {
    case day,week,month
    var id:String { rawValue }
    var label:String { [Self.day:"日K",.week:"周K",.month:"月K"][self]! }
    var unit:String { [Self.day:"日",.week:"周",.month:"月"][self]! }
    func key(_ day:String)->String {
        if self == .day { return day }
        if self == .month { return String(day.prefix(6)) }
        guard let date=ChartDate.parse(day),let start=ChartDate.calendar.dateInterval(of:.weekOfYear,for:date)?.start else { return day }
        return ChartDate.key(start)
    }
}
enum ChartPriceBasis:String,CaseIterable,Identifiable,Sendable {
    case continuous,raw
    var id:String { rawValue }
    var label:String { self == .continuous ? "连续价":"原始价" }
}
enum ChartPane:String,CaseIterable,Identifiable,Sendable {
    case volume,macd,rsi
    var id:String { rawValue }
    var label:String { [Self.volume:"成交量",.macd:"MACD",.rsi:"RSI14"][self]! }
}

func chartVolume(_ value:Double)->String {
    guard value.isFinite else { return "—" }
    if value>=1e8 { return String(format:"%.2f亿手",value/1e8) }
    if value>=1e4 { return String(format:"%.2f万手",value/1e4) }
    return String(format:"%.0f手",value)
}
func chartAmount(_ value:Double?)->String {
    guard let value,value.isFinite else { return "—" }
    return value>=1e5 ? String(format:"%.2f亿元",value/1e5):String(format:"%.2f万元",value/10)
}
func chartPrice(_ value:Double?)->String {
    guard let value,value.isFinite else { return "—" }
    let places=abs(value)>=1 ? 2:(abs(value)>=0.01 ? 4:6)
    return String(format:"%.*f",places,value)
}
