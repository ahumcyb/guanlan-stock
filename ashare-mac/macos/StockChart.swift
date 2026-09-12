import SwiftUI

struct ChartLink<Content:View>:View {
    let target:ChartTarget
    @ViewBuilder let content:Content
    @State private var presented=false
    var body:some View {
        Button { presented=true } label: { content }.buttonStyle(.plain)
            .sheet(isPresented:$presented) { PublishedChartSheet(target:target) }
    }
}

struct StockChart:View {
    @ObservedObject var loader:ChartLoadState
    let name:String;let signalDate:String;let signalLabel:String;let reference:Double?;let invalidation:Double?
    let retry:()->Void
    @State private var expanded:ChartViewOptions?
    var body:some View {
        Group {
            if let data=loader.data {
                let focus=ChartFocus(date:signalDate,price:nil,label:signalLabel)
                KlineView(data:data,focus:focus,reference:reference,invalidation:invalidation,referenceDate:signalDate,
                          plotHeight:340,onExpand:{expanded=$0})
                    .sheet(item:$expanded) { options in ExpandedKlineView(name:name,data:data,focus:focus,reference:reference,invalidation:invalidation,referenceDate:signalDate,initialState:options) }
            } else if let error=loader.error {
                VStack(alignment:.leading,spacing:12) { Text(error).font(.caption).foregroundStyle(Palette.amber);Button("重试K线",action:retry) }.frame(maxWidth:.infinity,minHeight:220,alignment:.leading)
            } else { ProgressView("读取K线…").frame(maxWidth:.infinity,minHeight:240) }
        }
    }
}

struct PublishedChartSheet:View {
    @EnvironmentObject var app:AppStore
    @Environment(\.dismiss) private var dismiss
    let target:ChartTarget
    @StateObject private var loader=ChartLoadState()
    var body:some View {
        VStack(spacing:0) {
            HStack { Text(target.name+" · "+target.code).font(.headline);Spacer();Button("完成") { dismiss() }.keyboardShortcut(.cancelAction) }.padding()
            GeometryReader { proxy in
                ScrollView {
                    if let data=loader.data {
                        KlineView(data:data,focus:target.focus,through:target.through,
                                  plotHeight:max(300,proxy.size.height-300)).padding(20)
                    } else if let error=loader.error { VStack(spacing:16) { Text(error);Button("重试") { Task { await load() } } }.padding(30) }
                    else { ProgressView("读取同一股票的已发布日线…").padding(40) }
                }
            }
        }.frame(minWidth:850,idealWidth:1050,minHeight:650,idealHeight:780)
            .task(id:target.id) { await load() }.onDisappear { loader.reset() }
    }
    private func load() async { await loader.load(key:target.id) { try await app.chartData(for:target) } }
}
