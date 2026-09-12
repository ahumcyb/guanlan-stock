#if os(iOS)
import SwiftUI
import UIKit

struct KlineTouchSurface:UIViewRepresentable {
    var inspect:(CGPoint)->Void
    var pan:(CGFloat)->Void
    var panEnd:()->Void
    var zoom:(CGFloat,CGFloat)->Void
    var zoomEnd:()->Void
    func makeCoordinator()->Coordinator { Coordinator(self) }
    func makeUIView(context:Context)->UIView {
        let view=UIView();view.backgroundColor = .clear;view.isMultipleTouchEnabled=true
        let coordinator=context.coordinator
        let tap=UITapGestureRecognizer(target:coordinator,action:#selector(Coordinator.tap(_:)))
        tap.cancelsTouchesInView=false;tap.delegate=coordinator;view.addGestureRecognizer(tap)
        let pan=UIPanGestureRecognizer(target:coordinator,action:#selector(Coordinator.pan(_:)))
        pan.maximumNumberOfTouches=1;pan.cancelsTouchesInView=false;pan.delegate=coordinator;view.addGestureRecognizer(pan)
        let hold=UILongPressGestureRecognizer(target:coordinator,action:#selector(Coordinator.hold(_:)))
        hold.minimumPressDuration=0.25;hold.allowableMovement=15;hold.delegate=coordinator;view.addGestureRecognizer(hold)
        let pinch=UIPinchGestureRecognizer(target:coordinator,action:#selector(Coordinator.pinch(_:)))
        pinch.delegate=coordinator;view.addGestureRecognizer(pinch)
        coordinator.holdRecognizer=hold
        return view
    }
    func updateUIView(_ view:UIView,context:Context) { context.coordinator.owner=self }
    final class Coordinator:NSObject,UIGestureRecognizerDelegate {
        var owner:KlineTouchSurface
        weak var holdRecognizer:UILongPressGestureRecognizer?
        private var zoomAnchor:CGFloat=0.5
        init(_ owner:KlineTouchSurface) { self.owner=owner }
        func gestureRecognizerShouldBegin(_ recognizer:UIGestureRecognizer)->Bool {
            if let pan=recognizer as? UIPanGestureRecognizer {
                if holdRecognizer?.state == .began || holdRecognizer?.state == .changed { return false }
                let velocity=pan.velocity(in:pan.view)
                return ChartGestureDirection.horizontal(x:Double(velocity.x),y:Double(velocity.y))
            }
            return true
        }
        func gestureRecognizer(_ recognizer:UIGestureRecognizer,shouldRecognizeSimultaneouslyWith other:UIGestureRecognizer)->Bool {
            !(recognizer is UILongPressGestureRecognizer) && !(other is UILongPressGestureRecognizer)
        }
        @objc func tap(_ recognizer:UITapGestureRecognizer) {
            if recognizer.state == .ended { owner.inspect(recognizer.location(in:recognizer.view)) }
        }
        @objc func pan(_ recognizer:UIPanGestureRecognizer) {
            if recognizer.state == .began || recognizer.state == .changed { owner.pan(recognizer.translation(in:recognizer.view).x) }
            else if [.ended,.cancelled,.failed].contains(recognizer.state) { owner.panEnd() }
        }
        @objc func hold(_ recognizer:UILongPressGestureRecognizer) {
            if recognizer.state == .began || recognizer.state == .changed { owner.inspect(recognizer.location(in:recognizer.view)) }
        }
        @objc func pinch(_ recognizer:UIPinchGestureRecognizer) {
            if recognizer.state == .began { zoomAnchor=recognizer.location(in:recognizer.view).x/max(1,recognizer.view?.bounds.width ?? 1) }
            if recognizer.state == .began || recognizer.state == .changed { owner.zoom(recognizer.scale,zoomAnchor) }
            else if [.ended,.cancelled,.failed].contains(recognizer.state) { owner.zoomEnd() }
        }
    }
}
#endif
