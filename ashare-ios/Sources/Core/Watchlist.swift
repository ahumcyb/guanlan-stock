import Foundation

struct WatchlistReply:Codable {
    let schemaVersion:Int;let revision:Int;let updatedAt:Double;let codes:[String]
    func validate() throws {
        guard schemaVersion==1,revision>=0,updatedAt.isFinite,updatedAt>=0,codes.count<=1000,
              codes==codes.sorted(),Set(codes).count==codes.count,codes.allSatisfy(validStockCode) else { throw MobileFailure.invalidData }
    }
}

struct FavoriteOperation:Codable {
    let operationId:String;let tsCode:String;let action:String
    init(code:String,selected:Bool) { operationId=UUID().uuidString.lowercased();tsCode=code;action=selected ? "add":"remove" }
}

struct WatchlistJournal:Codable {
    var remoteCodes:[String]=[]
    var revision=0
    var pending:[FavoriteOperation]
    init(legacy:Set<String>) { pending=legacy.sorted().filter(validStockCode).map { FavoriteOperation(code:$0,selected:true) } }
    var codes:Set<String> {
        var values=Set(remoteCodes)
        for operation in pending {
            if operation.action=="add" { values.insert(operation.tsCode) } else { values.remove(operation.tsCode) }
        }
        return values
    }
    mutating func toggle(_ code:String) { pending.append(FavoriteOperation(code:code,selected:!codes.contains(code))) }
    mutating func accept(_ reply:WatchlistReply,acknowledging id:String?=nil) throws {
        try reply.validate()
        if reply.revision>=revision { remoteCodes=reply.codes;revision=reply.revision }
        if let id { pending.removeAll{$0.operationId==id} }
    }
    func validate() throws {
        guard revision>=0,remoteCodes.count<=1000,Set(remoteCodes).count==remoteCodes.count,
              remoteCodes.allSatisfy(validStockCode),pending.count<=5000,
              Set(pending.map(\.operationId)).count==pending.count,
              pending.allSatisfy({UUID(uuidString:$0.operationId) != nil && validStockCode($0.tsCode) && ["add","remove"].contains($0.action)}) else { throw MobileFailure.invalidData }
    }
}

@MainActor final class WatchlistReplica {
    private let file:URL
    private(set) var journal:WatchlistJournal
    private(set) var message="自选等待同步"
    private var syncing=false
    var codes:Set<String> { journal.codes }
    init(file:URL,legacy:Set<String>) throws {
        self.file=file
        if FileManager.default.fileExists(atPath:file.path) {
            let data=try Data(contentsOf:file);guard data.count<=2*1024*1024 else { throw MobileFailure.oversized }
            journal=try JSONDecoder().decode(WatchlistJournal.self,from:data);try journal.validate()
        } else {
            journal=WatchlistJournal(legacy:legacy)
            try FileManager.default.createDirectory(at:file.deletingLastPathComponent(),withIntermediateDirectories:true)
            try JSONEncoder().encode(journal).write(to:file,options:.atomic)
        }
    }
    private func save(_ next:WatchlistJournal) throws {
        try next.validate();try JSONEncoder().encode(next).write(to:file,options:.atomic);journal=next
    }
    func toggle(_ code:String) throws {
        guard validStockCode(code),journal.pending.count<5000 else { throw MobileFailure.invalidData }
        guard codes.contains(code) || codes.count<1000 else { throw MobileFailure.server("自选最多保存1000只") }
        var next=journal;next.toggle(code);try save(next);message="自选更改已保存，等待同步"
    }
    func synchronize(_ api:MobileAPI) async {
        guard !syncing else { return };syncing=true;defer{syncing=false}
        do {
            let body=try await api.request("/v1/watchlist",limit:65536)
            var next=journal;try next.accept(mobileDecoder().decode(WatchlistReply.self,from:body));try save(next)
            while let operation=journal.pending.first {
                let encoder=JSONEncoder();encoder.keyEncodingStrategy = .convertToSnakeCase
                let result=try await api.request("/v1/watchlist",method:"POST",body:encoder.encode(operation),limit:65536)
                var updated=journal
                try updated.accept(mobileDecoder().decode(WatchlistReply.self,from:result),acknowledging:operation.operationId)
                try save(updated)
            }
            message="自选已跨设备同步"
        } catch { message=journal.pending.isEmpty ? "自选暂离线，保留本机记录":"自选更改已保存在本机，联网后自动同步" }
    }
}
