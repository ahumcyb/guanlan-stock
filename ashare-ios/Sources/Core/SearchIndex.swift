import Foundation

/// Precomputed lowercase haystacks for debounced stock-list filtering.
struct StockSearchIndex:Sendable {
    struct Entry:Sendable {
        let id:String
        let haystack:String
    }
    let entries:[Entry]
    init(stocks:[Stock]) {
        entries=stocks.map { Entry(id:$0.id,haystack:[$0.name,$0.tsCode,$0.industry].joined(separator:"\n").lowercased()) }
    }
    func matching(_ query:String)->Set<String>? {
        let needle=query.trimmingCharacters(in:.whitespacesAndNewlines).lowercased()
        if needle.isEmpty { return nil }
        return Set(entries.lazy.filter{$0.haystack.contains(needle)}.map(\.id))
    }
}

enum StockListFilter {
    static func apply(stocks:[Stock],favoritesOnly:Bool,favorites:Set<String>,filter:String,queryIds:Set<String>?,sort:String)->[Stock] {
        var rows=stocks
        if favoritesOnly { rows=rows.filter{favorites.contains($0.id)} }
        else if queryIds==nil {
            switch filter {
            case "精选":rows=rows.filter{$0.state=="入选"}
            case "转强":rows=rows.filter{["入选","转强","符合"].contains($0.state)}
            case "等待":rows=rows.filter{$0.state=="等待"}
            default:break
            }
        }
        if let queryIds { rows=rows.filter{queryIds.contains($0.id)} }
        rows.sort { a,b in
            if sort=="涨跌幅" { return a.change==b.change ? a.id<b.id:a.change>b.change }
            if sort=="成交额" { return a.amount20==b.amount20 ? a.id<b.id:(a.amount20 ?? 0)>(b.amount20 ?? 0) }
            return a.score==b.score ? a.id<b.id:a.score>b.score
        }
        return rows
    }
}
