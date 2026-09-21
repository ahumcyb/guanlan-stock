import Foundation
import CryptoKit

extension JevReview {
    func bound(to manifest:MobileManifest)->Bool {
        scope=="after_close" && generation==manifest.generation && dataRevision==manifest.dataRevision
            && date==manifest.asOf && sourceReportShas?[manifest.strategy]==manifest.reportSha256
    }
}
private struct JevDailyEnvelope:Codable { let payload:Data;let sha256:String }
private func jevDailyURL(_ root:URL,_ manifest:MobileManifest) throws -> URL {
    try manifest.validate();return root.appendingPathComponent("jev-daily-"+manifest.generation+".json")
}
func cachedDailyJev(_ root:URL,_ manifest:MobileManifest)->JevReview? {
    guard let path=try? jevDailyURL(root,manifest),let size=try? path.resourceValues(forKeys:[.fileSizeKey]).fileSize,size<=512*1024,
          let data=try? Data(contentsOf:path),let envelope=try? JSONDecoder().decode(JevDailyEnvelope.self,from:data),
          SHA256.hash(data:envelope.payload).map({String(format:"%02x",$0)}).joined()==envelope.sha256,
          let review=try? mobileDecoder().decode(JevReview.self,from:envelope.payload),review.bound(to:manifest) else { return nil }
    return review
}
func fetchDailyJev(_ api:MobileAPI,root:URL,manifest:MobileManifest) async throws -> JevReview {
    do {
        try manifest.validate()
        let raw=try await api.request("/v1/jev/daily/"+manifest.generation,limit:256*1024)
        let review=try mobileDecoder().decode(JevReview.self,from:raw)
        guard review.bound(to:manifest),review.rows.count<=50,Set(review.rows.map(\.tsCode)).count==review.rows.count else { throw MobileFailure.invalidData }
        if review.status=="ready" {
            let payload=JevDailyEnvelope(payload:raw,sha256:SHA256.hash(data:raw).map({String(format:"%02x",$0)}).joined())
            try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
            try JSONEncoder().encode(payload).write(to:jevDailyURL(root,manifest),options:.atomic)
            let files=try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.contentModificationDateKey]).filter{$0.lastPathComponent.hasPrefix("jev-daily-")}
            for file in files.sorted(by:{$0.lastPathComponent>$1.lastPathComponent}).dropFirst(10) { try? FileManager.default.removeItem(at:file) }
        }
        return review
    } catch {
        if let saved=cachedDailyJev(root,manifest) { return saved }
        throw error
    }
}
