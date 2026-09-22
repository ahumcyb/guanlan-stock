import SwiftUI

enum Palette {
    static let ink=Color(red:0.10,green:0.19,blue:0.18)
    static let teal=Color(red:0.10,green:0.34,blue:0.29)
    static let muted=Color(red:0.43,green:0.49,blue:0.47)
    static let canvas=Color(red:0.97,green:0.975,blue:0.966)
    static let line=Color(red:0.87,green:0.90,blue:0.88)
    static let selected=Color(red:0.90,green:0.945,blue:0.92)
    static let up=Color(red:0.79,green:0.26,blue:0.23)
    static let down=Color(red:0.13,green:0.52,blue:0.39)
    static let amber=Color(red:0.66,green:0.44,blue:0.14)
    /// 红涨绿跌；零涨跌用中性色，不算上涨红。
    static func change(_ value:Double)->Color { value>0 ? up:(value<0 ? down:muted) }
}

struct Badge: View {
    let text:String
    var color:Color=Palette.teal
    var body: some View {
        Text(text).font(.system(size:10,weight:.medium)).foregroundStyle(color)
            .padding(.horizontal,7).padding(.vertical,4).background(color.opacity(0.085),in:RoundedRectangle(cornerRadius:4))
    }
}
struct Metric: View {
    let label:String; let value:String; var note:String=""; var color:Color=Palette.ink
    var body: some View {
        VStack(alignment:.leading,spacing:7) {
            Text(label).font(.system(size:11)).foregroundStyle(Palette.muted)
            Text(value).font(.system(size:27,weight:.semibold,design:.rounded)).monospacedDigit().foregroundStyle(color)
            if !note.isEmpty { Text(note).font(.system(size:10)).foregroundStyle(Palette.muted) }
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
}
struct Panel<Content:View>: View {
    @ViewBuilder let content: Content
    var body:some View {
        content.padding(20).background(.white,in:RoundedRectangle(cornerRadius:10))
            .overlay(RoundedRectangle(cornerRadius:10).stroke(Palette.line,lineWidth:0.7))
    }
}
struct EmptyViewMessage:View {
    let icon:String; let title:String; let message:String
    var body:some View {
        VStack(spacing:12) {
            Image(systemName:icon).font(.system(size:30,weight:.light)).foregroundStyle(Palette.teal)
            Text(title).font(.system(size:15,weight:.semibold))
            Text(message).font(.system(size:12)).foregroundStyle(Palette.muted).multilineTextAlignment(.center).frame(maxWidth:350)
        }.frame(maxWidth:.infinity,maxHeight:.infinity).padding(30)
    }
}
