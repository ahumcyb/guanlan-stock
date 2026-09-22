import SwiftUI

struct MobileCandleChart:View {
    let data:ChartDataset;let name:String;let tsCode:String;let signalDate:String;let signalLabel:String;let reference:Double?;let invalidation:Double?
    @State private var expanded:ChartViewOptions?
    var body:some View {
        let focus=ChartFocus(date:signalDate,price:nil,label:signalLabel)
        KlineView(data:data,focus:focus,reference:reference,invalidation:invalidation,referenceDate:signalDate,
                  plotHeight:310,onExpand:{expanded=$0})
            .fullScreenCover(item:$expanded) { options in
                ExpandedKlineView(name:name,data:data,focus:focus,reference:reference,invalidation:invalidation,referenceDate:signalDate,initialState:options)
                    .tonghuashunOpen(tsCode)
            }
    }
}

struct MobileChartScreen:View {
    @EnvironmentObject var store:MobileStore
    let target:ChartTarget
    @StateObject private var loader=ChartLoadState()
    @State private var expanded:ChartViewOptions?
    var body:some View {
        GeometryReader { proxy in
            ScrollView {
                if let data=loader.data {
                    ResearchCard {
                        KlineView(data:data,focus:target.focus,through:target.through,
                                  plotHeight:max(300,proxy.size.height-290),onExpand:{expanded=$0})
                    }.padding(12)
                        .fullScreenCover(item:$expanded) { options in
                            ExpandedKlineView(name:target.name,data:data,focus:target.focus,through:target.through,initialState:options)
                                .tonghuashunOpen(target.code)
                        }
                } else if let error=loader.error { VStack(spacing:16) { Text(error);Button("重试") { Task { await load() } } }.padding(30) }
                else { ProgressView("读取已发布日线…").padding(40) }
            }
        }.background(MobileTheme.background).navigationTitle(target.name+" · K线").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .primaryAction) { OpenInTonghuashunButton(tsCode: target.code) } }
            .task(id:target.id) { await load() }
    }
    private func load() async { await loader.load(key:target.id) { try await store.chartData(code:target.code,through:target.through) } }
}

private extension View {
    func tonghuashunOpen(_ tsCode:String)->some View {
        safeAreaInset(edge:.bottom) {
            OpenInTonghuashunButton(tsCode:tsCode).buttonStyle(.bordered).tint(MobileTheme.teal).padding(.bottom,8)
        }
    }
}
