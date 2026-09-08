import Foundation

@main struct NotificationTests {
    static func main() throws {
        let id="a8ea4ae9-b0e9-4fab-a986-5f4eee728dbd"
        assert(notificationTarget(URL(string:"guanlan://alerts/"+id)!) == .event(id))
        assert(notificationTarget(URL(string:"guanlan://daily?date=20260907")!) == .daily("20260907"))
        assert(notificationTarget(URL(string:"guanlan://daily")!) == .daily(nil))
        for value in ["guanlan://alerts/not-an-id","guanlan://alerts/../../file","guanlan://daily?date=20260230",
                      "guanlan://daily?date=20260907&date=20260904","https://example.test/alerts/"+id] {
            assert(notificationTarget(URL(string:value)!)==nil)
        }
        print("Notification event/date routing and invalid-link rejection passed")
    }
}
