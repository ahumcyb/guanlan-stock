import Foundation

@main struct ChunkReadTests {
    static func assemble(_ chunks:[Data],limit:Int) throws -> Data {
        var data=Data()
        for chunk in chunks {
            if data.count+chunk.count>limit { throw MobileFailure.oversized }
            data.append(chunk)
        }
        return data
    }
    static func main() throws {
        let ok=try assemble([Data(repeating:1,count:64*1024),Data(repeating:2,count:1024)],limit:12*1024*1024)
        assert(ok.count==65*1024)
        do {
            _=try assemble([Data(repeating:1,count:100),Data(repeating:2,count:50)],limit:120)
            assertionFailure("oversized chunk accepted")
        } catch MobileFailure.oversized {}
        print("Chunked read size-cap checks passed")
    }
}
