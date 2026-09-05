import AppKit
let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:1024,pixelsHigh:1024,bitsPerSample:8,samplesPerPixel:3,hasAlpha:false,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
NSColor(red:0.09,green:0.32,blue:0.28,alpha:1).setFill()
NSBezierPath(rect:NSRect(x:0,y:0,width:1024,height:1024)).fill()
let path=NSBezierPath();path.lineWidth=42;path.lineCapStyle = .round;path.lineJoinStyle = .round
path.move(to:NSPoint(x:170,y:480))
for point in [NSPoint(x:305,y:480),NSPoint(x:372,y:660),NSPoint(x:451,y:330),NSPoint(x:535,y:720),NSPoint(x:625,y:420),NSPoint(x:702,y:545),NSPoint(x:855,y:545)] { path.line(to:point) }
NSColor(red:0.89,green:0.96,blue:0.87,alpha:1).setStroke();path.stroke()
NSGraphicsContext.restoreGraphicsState()
let data=bitmap.representation(using:.png,properties:[:])!
try data.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
