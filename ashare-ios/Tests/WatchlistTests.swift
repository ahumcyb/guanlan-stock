import Foundation

@main struct WatchlistTests {
    @MainActor static func main() throws {
        var journal=WatchlistJournal(legacy:["000001.SZ"])
        assert(journal.codes==["000001.SZ"] && journal.pending.count==1)
        let add=journal.pending[0]
        journal.toggle("000001.SZ")
        try journal.accept(WatchlistReply(schemaVersion:1,revision:1,updatedAt:1,codes:["000001.SZ","600519.SH"]),acknowledging:add.operationId)
        assert(journal.codes==["600519.SH"] && journal.pending.count==1)
        let remove=journal.pending[0]
        try journal.accept(WatchlistReply(schemaVersion:1,revision:2,updatedAt:2,codes:["600519.SH"]),acknowledging:remove.operationId)
        assert(journal.pending.isEmpty && journal.codes==["600519.SH"])
        try journal.accept(WatchlistReply(schemaVersion:1,revision:1,updatedAt:1,codes:["000001.SZ"]))
        assert(journal.codes==["600519.SH"])
        do {
            try journal.accept(WatchlistReply(schemaVersion:1,revision:3,updatedAt:3,codes:["../bad"]))
            assertionFailure("Invalid remote favorite accepted")
        } catch {}
        journal.toggle("000001.SZ")
        let data=try JSONEncoder().encode(journal)
        let restored=try JSONDecoder().decode(WatchlistJournal.self,from:data)
        assert(restored.codes==["000001.SZ","600519.SH"] && restored.pending.map(\.operationId)==journal.pending.map(\.operationId))
        print("Watchlist legacy import, offline intent, reply race, validation and restart checks passed")
    }
}
