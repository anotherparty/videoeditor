import AppKit
let a = CommandLine.arguments; let out = a[1]; let files = Array(a[2...])
let cw = 270, ch = 480, cols = 6, rows = (files.count + cols - 1) / cols
let img = NSImage(size: NSSize(width: cw*cols, height: ch*rows)); img.lockFocus()
for (i, f) in files.enumerated() { NSImage(contentsOfFile: f)?.draw(in: NSRect(x: (i%cols)*cw, y: (rows-1-i/cols)*ch, width: cw, height: ch)) }
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!; try! rep.representation(using: .jpeg, properties: [.compressionFactor: 0.8])!.write(to: URL(fileURLWithPath: out))
