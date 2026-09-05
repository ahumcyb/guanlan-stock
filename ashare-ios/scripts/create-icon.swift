import Foundation
import ImageIO
import UniformTypeIdentifiers

// Prepare the selected artwork for Xcode without redrawing it through AppKit.
let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let sourceURL = root.appendingPathComponent("design/AppIconMaster.png")
let outputURL = CommandLine.arguments.count > 1
    ? URL(fileURLWithPath: CommandLine.arguments[1])
    : root.appendingPathComponent("Assets.xcassets/AppIcon.appiconset/AppIcon.png")

guard let source = CGImageSourceCreateWithURL(sourceURL as CFURL, nil),
      let original = CGImageSourceCreateImageAtIndex(source, 0, nil),
      original.width == original.height else {
    fatalError("App icon master must be a readable square image")
}
let options: [CFString: Any] = [
    kCGImageSourceCreateThumbnailFromImageAlways: true,
    kCGImageSourceCreateThumbnailWithTransform: true,
    kCGImageSourceThumbnailMaxPixelSize: 1024
]
guard let icon = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
      icon.width == 1024, icon.height == 1024,
      let pixels = icon.dataProvider?.data,
      Set(pixels as Data).count > 32,
      let destination = CGImageDestinationCreateWithURL(outputURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fatalError("App icon must contain visible artwork at 1024 x 1024")
}
CGImageDestinationAddImage(destination, icon, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Could not save the app icon") }
print("App icon prepared: 1024 x 1024")
