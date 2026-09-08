import Foundation

@MainActor final class DeferredRead {
    var continuation:CheckedContinuation<Data,Error>?
    var heldPath=""
    var first=true
    func response(_ path:String) throws -> Data {
        if path=="/v1/realtime" {
            return try JSONSerialization.data(withJSONObject:["schema_version":1,"settings":["enabled":true,"notification_enabled":true,"ai_enabled":false,"model":"deepseek-v4-pro","bark_configured":true,"deepseek_configured":true],"mac_online":true,"server_online":true,"running":false,"executor":"","schedule":[],"events":[],"latest":NSNull(),"last_screen":NSNull()])
        }
        let id=String(path.split(separator:"/").last!)
        return try JSONSerialization.data(withJSONObject:["event":["id":id,"created_at":1,"title":"原通知","body":id,"kind":"screen","status":"accepted"],"report":NSNull(),"message":"保留原始通知"])
    }
    func read(_ path:String,_ limit:Int) async throws -> Data {
        if first { first=false;heldPath=path;return try await withCheckedThrowingContinuation { continuation=$0 } }
        return try response(path)
    }
    func release() throws { let value=continuation;continuation=nil;value?.resume(returning:try response(heldPath)) }
}

@main struct NotificationRaceTests {
    @MainActor static func main() async throws {
        let first="00000000-0000-4000-8000-000000000001",second="00000000-0000-4000-8000-000000000002"
        for closeInstead in [false,true] {
            let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            defer { try? FileManager.default.removeItem(at:root) }
            let gate=DeferredRead()
            let store=MobileStore(storageRoot:root,startAutomatically:false,realtimeReader:gate.read)
            let older=Task { await store.openURL(URL(string:"guanlan://alerts/"+first)!) }
            for _ in 0..<10000 { if gate.continuation != nil { break };await Task.yield() }
            precondition(gate.continuation != nil,"Deferred request was not started")
            if closeInstead { store.closeRealtimeDetail() }
            else { await store.openRealtimeEvent(second);precondition(store.realtimeEventDetail?.event.id==second) }
            try gate.release();await older.value
            if closeInstead { precondition(!store.realtimeDetailPresented,"Late old notification reopened a dismissed detail") }
            else { precondition(store.realtimeEventDetail?.event.id==second,"Late old notification replaced newer selection") }
        }
        print("Real MobileStore slow notification vs newer selection/dismissal races passed")
    }
}
