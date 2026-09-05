import Foundation
import Security

enum MobileFailure: LocalizedError {
    case invalidConfiguration, invalidData, oversized, expiredSnapshot, unauthorized, server(String)
    var errorDescription:String? {
        switch self {
        case .invalidConfiguration:return "连接配置无效，请导入这台服务器的手机配对文件。"
        case .invalidData:return "数据没有通过完整性校验，已保留上次结果。"
        case .oversized:return "服务器响应超过大小限制。"
        case .expiredSnapshot:return "这个数据版本已过期，请同步最新结果。"
        case .unauthorized:return "连接凭据已失效，请重新导入配对文件。"
        case .server(let message):return message
        }
    }
}

struct Pairing:Codable {
    let endpoint:String
    let token:String
    let certificate:String
    func validated() throws -> Pairing {
        guard let url=URL(string:endpoint),url.scheme=="https",url.host=="106.14.125.189",
              url.port==nil || url.port==443,url.user==nil,url.password==nil,url.query==nil,url.fragment==nil,
              url.path.isEmpty || url.path=="/",token.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
              let cert=Data(base64Encoded:certificate),cert.count<16384,
              SecCertificateCreateWithData(nil,cert as CFData) != nil else { throw MobileFailure.invalidConfiguration }
        return self
    }
}

enum CredentialStore {
    private static var query:[String:Any] { [kSecClass as String:kSecClassGenericPassword,
        kSecAttrService as String:"local.guanlan.ios.connection",kSecAttrAccount as String:"personal-server"] }
    static func load() throws -> Pairing? {
        var request=query;request[kSecReturnData as String]=true;request[kSecMatchLimit as String]=kSecMatchLimitOne
        var result:CFTypeRef?;let status=SecItemCopyMatching(request as CFDictionary,&result)
        if status==errSecItemNotFound { return nil }
        guard status==errSecSuccess,let data=result as? Data else { throw MobileFailure.server("无法读取连接钥匙串。") }
        return try JSONDecoder().decode(Pairing.self,from:data).validated()
    }
    static func save(_ pairing:Pairing) throws {
        let data=try JSONEncoder().encode(pairing.validated())
        let values=[kSecValueData as String:data,kSecAttrAccessible as String:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly] as [String:Any]
        let status=SecItemUpdate(query as CFDictionary,values as CFDictionary)
        if status==errSecItemNotFound {
            guard SecItemAdd(query.merging(values,uniquingKeysWith:{$1}) as CFDictionary,nil)==errSecSuccess else { throw MobileFailure.server("保存连接钥匙串失败。") }
        } else if status != errSecSuccess { throw MobileFailure.server("更新连接钥匙串失败。") }
    }
}

final class ServerTrust:NSObject,URLSessionDelegate,URLSessionTaskDelegate,@unchecked Sendable {
    let pairing:Pairing
    init(_ pairing:Pairing) { self.pairing=pairing }
    func urlSession(_ session:URLSession,task:URLSessionTask,didReceive challenge:URLAuthenticationChallenge,
                    completionHandler:@escaping(URLSession.AuthChallengeDisposition,URLCredential?)->Void) {
        urlSession(session,didReceive:challenge,completionHandler:completionHandler)
    }
    func urlSession(_ session:URLSession,didReceive challenge:URLAuthenticationChallenge,
                    completionHandler:@escaping(URLSession.AuthChallengeDisposition,URLCredential?)->Void) {
        guard challenge.protectionSpace.authenticationMethod==NSURLAuthenticationMethodServerTrust else { completionHandler(.performDefaultHandling,nil);return }
        guard challenge.protectionSpace.host=="106.14.125.189",let trust=challenge.protectionSpace.serverTrust,
              let data=Data(base64Encoded:pairing.certificate),let anchor=SecCertificateCreateWithData(nil,data as CFData) else { completionHandler(.cancelAuthenticationChallenge,nil);return }
        SecTrustSetAnchorCertificates(trust,[anchor] as CFArray)
        SecTrustSetAnchorCertificatesOnly(trust,true)
        SecTrustSetPolicies(trust,SecPolicyCreateSSL(true,"106.14.125.189" as CFString))
        guard SecTrustEvaluateWithError(trust,nil) else { completionHandler(.cancelAuthenticationChallenge,nil);return }
        completionHandler(.useCredential,URLCredential(trust:trust))
    }
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,
                    newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) { completionHandler(nil) }
}

final class MobileAPI:@unchecked Sendable {
    let pairing:Pairing
    private let session:URLSession
    private let trust:ServerTrust
    init(_ pairing:Pairing) throws {
        self.pairing=try pairing.validated()
        let config=URLSessionConfiguration.ephemeral
        config.tlsMinimumSupportedProtocolVersion = .TLSv12
        config.timeoutIntervalForRequest=30;config.timeoutIntervalForResource=90
        config.httpMaximumConnectionsPerHost=3
        trust=ServerTrust(pairing)
        session=URLSession(configuration:config,delegate:trust,delegateQueue:nil)
    }
    deinit { session.invalidateAndCancel() }
    func request(_ path:String,method:String="GET",body:Data?=nil,limit:Int=12*1024*1024) async throws -> Data {
        guard path.hasPrefix("/v1/"),!path.contains(".."),!path.contains("?"),!path.contains("%"),
              let url=URL(string:pairing.endpoint.trimmingCharacters(in:CharacterSet(charactersIn:"/"))+path) else { throw MobileFailure.invalidConfiguration }
        var request=URLRequest(url:url);request.httpMethod=method;request.httpBody=body
        request.setValue("Bearer "+pairing.token,forHTTPHeaderField:"Authorization")
        request.setValue("application/json",forHTTPHeaderField:"Accept")
        if body != nil { request.setValue("application/json",forHTTPHeaderField:"Content-Type") }
        let (bytes,response)=try await session.bytes(for:request,delegate:trust)
        guard let response=response as? HTTPURLResponse else { throw MobileFailure.invalidData }
        if response.statusCode==401 { bytes.task.cancel();throw MobileFailure.unauthorized }
        if response.statusCode==404 {
            bytes.task.cancel()
            if path.hasSuffix("/current") { throw MobileFailure.server("服务器还没有研究结果，请到“数据”页重新选股。") }
            throw MobileFailure.expiredSnapshot
        }
        let allowed=(200..<300).contains(response.statusCode) ? limit:8192
        var data=Data()
        for try await byte in bytes {
            if data.count>=allowed { bytes.task.cancel();throw MobileFailure.oversized }
            data.append(byte)
        }
        guard (200..<300).contains(response.statusCode) else {
            struct Envelope:Decodable { struct Item:Decodable { let message:String };let error:Item }
            let message=(try? JSONDecoder().decode(Envelope.self,from:data).error.message) ?? "服务器暂时不可用，请稍后重试。"
            throw MobileFailure.server(String(message.prefix(200)))
        }
        return data
    }
}
