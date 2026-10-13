import SwiftUI

enum MobileTheme {
    static let ink=Color.primary
    static let muted=Color.secondary
    static let teal=Color(red:0.10,green:0.36,blue:0.31)
    static let up=Color(red:0.78,green:0.23,blue:0.20)
    static let down=Color(red:0.13,green:0.48,blue:0.36)
    static let amber=Color(red:0.61,green:0.40,blue:0.12)
    #if os(iOS)
    static let background=Color(uiColor:.systemGroupedBackground)
    #else
    static let background=Color(nsColor:.windowBackgroundColor)
    #endif
    static let line=Color.primary.opacity(0.08)
    /// 红涨绿跌；零涨跌用中性色，不算上涨红。
    static func change(_ value:Double)->Color { value>0 ? up:(value<0 ? down:muted) }
}

struct ResearchCard<Content:View>:View {
    @ViewBuilder let content:Content
    var body:some View { content.padding(16).frame(maxWidth:.infinity,alignment:.leading).background(.background,in:RoundedRectangle(cornerRadius:16)).overlay(RoundedRectangle(cornerRadius:16).stroke(MobileTheme.line)) }
}

struct StatePill:View {
    let text:String
    var body:some View { Text(text).font(.caption.weight(.medium)).padding(.horizontal,8).padding(.vertical,4).background(MobileTheme.teal.opacity(0.09),in:Capsule()).foregroundStyle(MobileTheme.teal) }
}

/// 横向滑动的策略标签，替代挤在一行的分段控件。
struct StrategyChips:View {
    let selection:String
    var disabled=false
    let onSelect:(String)->Void
    var body:some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal,showsIndicators:false) {
                HStack(spacing:8) {
                    ForEach(AfterCloseStrategies.ids,id:\.self) { id in
                        let active=id==selection
                        Button { onSelect(id) } label: {
                            Text(AfterCloseStrategies.shortName(id)).font(.subheadline.weight(active ? .semibold:.regular))
                                .padding(.horizontal,14).padding(.vertical,8)
                                .background(active ? MobileTheme.teal:MobileTheme.teal.opacity(0.08),in:Capsule())
                                .foregroundStyle(active ? Color.white:MobileTheme.teal)
                        }.buttonStyle(.plain).id(id).accessibilityAddTraits(active ? .isSelected:[])
                    }
                }.padding(.vertical,2)
            }
            .disabled(disabled).opacity(disabled ? 0.6:1)
            .onAppear { proxy.scrollTo(selection,anchor:.center) }
        }
    }
}

struct EmptyMessage:View {
    let title:String;let text:String;var icon="waveform.path.ecg"
    var body:some View { VStack(spacing:14) { Image(systemName:icon).font(.largeTitle).foregroundStyle(MobileTheme.teal);Text(title).font(.headline);Text(text).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center) }.padding(28).frame(maxWidth:.infinity,maxHeight:.infinity) }
}

struct Metric:View {
    let label:String;let value:String;var color:Color = .primary
    var body:some View { VStack(alignment:.leading,spacing:6) { Text(value).font(.title3.weight(.semibold)).monospacedDigit().foregroundStyle(color).minimumScaleFactor(0.7).lineLimit(1);Text(label).font(.caption).foregroundStyle(.secondary) }.frame(maxWidth:.infinity,alignment:.leading) }
}

extension View {
    /// iOS 26 默认让列表在标题后方半透明模糊，数字会叠在标题下；改为清晰分隔。
    @ViewBuilder func crispTopEdge()->some View {
        if #available(iOS 26.0,*) { self.scrollEdgeEffectStyle(.hard,for:.top) } else { self }
    }
}
