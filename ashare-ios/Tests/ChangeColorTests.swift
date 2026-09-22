import Foundation

@main struct ChangeColorTests {
    static func changeBucket(_ value:Double)->String {
        if value>0 { return "up" }
        if value<0 { return "down" }
        return "flat"
    }
    static func main() throws {
        assert(changeBucket(1.25)=="up")
        assert(changeBucket(-0.01)=="down")
        assert(changeBucket(0)=="flat")
        assert(changeBucket(-0.0)=="flat")
        print("Realtime change-color sign buckets passed")
    }
}
