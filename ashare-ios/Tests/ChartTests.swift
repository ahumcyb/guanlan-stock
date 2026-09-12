import Foundation

@main struct ChartTests {
    static func main() throws {
        func bar(_ date:String,_ price:Double,volume:Double=100)->ChartCandle {
            ChartCandle(date:date,open:price,high:price+1,low:price-1,close:price,
                ma10:nil,ma20:nil,ma60:nil,volume:volume,rawOpen:price,rawHigh:price+1,rawLow:price-1,
                rawClose:price,rawPreClose:price,amount:price*volume/10)
        }
        let bars=[bar("20251229",10),bar("20251230",12),bar("20260102",11),bar("20260105",14)]
        let data=ChartDataset(tsCode:"600000.SH",asOf:"20260105",dataRevision:nil,bars:bars)
        let weeks=ChartSeries.make(data,period:.week,basis:.raw).bars
        assert(weeks.count==2 && weeks[0].startDate=="20251229" && weeks[0].date=="20260102")
        assert(weeks[0].open==10 && weeks[0].close==11 && weeks[0].high==13 && weeks[0].low==9 && weeks[0].volume==300)
        let months=ChartSeries.make(data,period:.month,basis:.raw).bars
        assert(months.count==2 && months[0].close==12 && months[1].open==11 && months[1].close==14)
        assert(months[0].ma10==nil)
        assert(ChartDate.parse("20260230")==nil && ChartDate.parse("20260911") != nil)

        var split=bar("20260908",10)
        split=ChartCandle(date:split.date,open:5,high:5.5,low:4.5,close:5,ma10:4.8,ma20:nil,ma60:nil,volume:100,
                          rawOpen:10,rawHigh:11,rawLow:9,rawClose:10,rawPreClose:10,amount:100)
        let splitData=ChartDataset(tsCode:"600000.SH",asOf:"20260909",dataRevision:nil,bars:[split,bar("20260909",5)])
        let continuous=ChartSeries.make(splitData,period:.day,basis:.continuous)
        assert(continuous.bars[0].close==5)
        assert(continuous.focusPrice(10,date:"20260908")==5)
        assert(continuous.focusPrice(10,date:"20260907")==nil)
        let historic=ChartSeries.make(splitData,period:.day,basis:.continuous,through:"20260908")
        assert(historic.bars.count==1 && historic.bars[0].close==10)
        assert(historic.focusPrice(10,date:"20260908")==10)
        assert(ChartSeries.make(splitData,period:.day,basis:.raw).bars[0].close==10)

        let up=Array(0...40).map { Double($0+10) }
        let down=up.reversed().map{$0};let flat=Array(repeating:10.0,count:41)
        assert(ChartIndicators.rsi(up)[13]==nil && ChartIndicators.rsi(up)[14]==100)
        assert(ChartIndicators.rsi(down).last! == 0 && ChartIndicators.rsi(flat).last! == 50)
        let seed=[10.0,11.0,10.0,11.0,10.0,11.0,10.0,11.0,10.0,11.0,10.0,11.0,10.0,11.0,10.0,11.0]
        assert(abs(ChartIndicators.rsi(seed)[15]!-53.5714285714)<1e-8)
        assert(ChartIndicators.ema([1.0,2.0,3.0],period:3)==[1.0,1.5,2.25])
        let macd=ChartIndicators.macd(flat)
        assert(macd[32]==nil && macd[33]!.histogram==0)

        var viewport=ChartViewport(total:412,count:60)
        assert(viewport.range==352..<412)
        viewport.pan(by:-10000);assert(viewport.range==0..<60)
        viewport.pan(by:10000);assert(viewport.range==352..<412)
        viewport.zoom(to:30,anchor:1);assert(viewport.range==382..<412)
        viewport.focus(index:20);assert(viewport.range.contains(20))
        viewport.zoom(to:500);assert(viewport.range==0..<412)
        viewport.latest();assert(viewport.range.upperBound==412)
        assert(ChartViewport(total:0,count:60).range.isEmpty)
        assert(ChartViewport(total:1,count:60).index(at:100,width:100)==0)
        assert(viewport.index(at:.nan,width:100)==nil)

        let domain=ChartDomain(prices:[9.99,10.0,10.01],tickCount:5)
        assert(domain.minimum<9.99 && domain.maximum>10.01 && domain.ticks.count>=3)
        assert(domain.ticks.allSatisfy{$0.isFinite})
        let single=ChartDomain(prices:[10.0],tickCount:5)
        assert(single.maximum>single.minimum)
        assert(ChartDomain(prices:[.nan,.infinity],tickCount:5).minimum.isFinite)
        assert(chartVolume(10000)=="1.00万手")
        assert(ChartGestureDirection.horizontal(x:100,y:10))
        assert(!ChartGestureDirection.horizontal(x:10,y:100))
        assert(!ChartGestureDirection.horizontal(x:0,y:0))
        assert(!ChartGestureDirection.horizontal(x:.infinity,y:0))
        print("Chart aggregation, raw/continuous focus, RSI/MACD warmup, viewport, axes and units passed")
    }
}
