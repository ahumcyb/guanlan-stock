import Foundation
import Combine

@MainActor final class ChartLoadState:ObservableObject {
    @Published private(set) var data:ChartDataset?
    @Published private(set) var error:String?
    @Published private(set) var loading=false
    private(set) var identity:String?
    private var ticket=UUID()
    func reset() { ticket=UUID();identity=nil;data=nil;error=nil;loading=false }
    func load(key:String,fetch:() async throws -> ChartDataset) async {
        let request=UUID();ticket=request;identity=key;data=nil;error=nil;loading=true
        do {
            let value=try await fetch()
            guard ticket==request else { return }
            guard !Task.isCancelled else { loading=false;return }
            data=value;loading=false
        } catch {
            guard ticket==request else { return }
            loading=false
            if !Task.isCancelled && !(error is CancellationError) { self.error=error.localizedDescription }
        }
    }
}

struct ChartFocus:Equatable,Sendable {
    let date:String;let price:Double?;let label:String
}
struct ChartTarget:Identifiable,Equatable,Sendable {
    let code:String;let name:String;let focus:ChartFocus?;let through:String?
    var id:String { code+"|"+(focus?.date ?? "")+"|"+(through ?? "")+"|"+String(focus?.price ?? 0) }
}
