// articlecard.swift — lay out an article excerpt as a clean news page (native AppKit text, no browser).
// Usage: swift articlecard.swift page.json out.png
//   page.json = {"outlet","title","byline","date","paras":[...], "lead": true if the passage starts mid-article}
// 2000x1120 = the split-screen card's shape (1000x560) at 2x, so brollcard.swift can OCR it sharply and add marks.
import AppKit

let a = CommandLine.arguments
guard a.count == 3, let d = FileManager.default.contents(atPath: a[1]),
      let page = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { print("usage: articlecard.swift page.json out.png"); exit(2) }
let W = 2000, H = 1120, pad: CGFloat = 80, tw = CGFloat(W) - 2 * pad
let str = { (k: String) in (page[k] as? String) ?? "" }

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: W, pixelsHigh: H, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext
ctx.translateBy(x: 0, y: CGFloat(H)); ctx.scaleBy(x: 1, y: -1)          // top-down coordinates
NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
NSColor.white.setFill(); NSRect(x: 0, y: 0, width: W, height: H).fill()

func font(_ names: [String], _ size: CGFloat, bold: Bool = false) -> NSFont {
    for n in names { if let f = NSFont(name: n, size: size) { return f } }
    return bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
}
func para(_ spacing: CGFloat) -> NSParagraphStyle { let p = NSMutableParagraphStyle(); p.lineSpacing = spacing; p.lineBreakMode = .byWordWrapping; return p }
var y = pad - 10
@discardableResult func draw(_ s: String, _ f: NSFont, _ c: NSColor, spacing: CGFloat = 0, kern: CGFloat = 0, maxH: CGFloat = 2000) -> CGFloat {
    let at = NSAttributedString(string: s, attributes: [.font: f, .foregroundColor: c, .paragraphStyle: para(spacing), .kern: kern])
    let h = min(maxH, ceil(at.boundingRect(with: NSSize(width: tw, height: 10000), options: [.usesLineFragmentOrigin]).height))
    at.draw(with: NSRect(x: pad, y: y, width: tw, height: h), options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine])
    y += h; return h
}

// outlet, headline, byline · date, rule, passage
draw(str("outlet").uppercased(), font(["HelveticaNeue-Bold"], 34, bold: true), NSColor(red: 0.75, green: 0.15, blue: 0.11, alpha: 1), kern: 3)
y += 22
draw(str("title"), font(["Georgia-Bold"], 68, bold: true), .black, spacing: 6, maxH: 3 * 84)
y += 22
var dateText = str("date")
if let dt = ISO8601DateFormatter().date(from: dateText + "T00:00:00Z") {
    let f = DateFormatter(); f.dateFormat = "MMM d, yyyy"; f.timeZone = TimeZone(identifier: "UTC"); dateText = f.string(from: dt)
}
let by = [str("byline").isEmpty ? "" : "By " + str("byline"), dateText].filter { !$0.isEmpty }.joined(separator: "  ·  ")
if !by.isEmpty { draw(by, font(["HelveticaNeue"], 30), NSColor(white: 0.42, alpha: 1)); y += 26 }
NSColor(white: 0.85, alpha: 1).setFill(); NSRect(x: pad, y: y, width: tw, height: 2).fill(); y += 34
let body = ((page["lead"] as? Bool) == true ? "… " : "") + ((page["paras"] as? [String]) ?? []).joined(separator: "\n\n")
draw(body, font(["Georgia"], 50), NSColor(white: 0.1, alpha: 1), spacing: 14, maxH: CGFloat(H) - y - 30)

// a long passage fades out at the bottom instead of ending on a cut line
let g = NSGradient(starting: NSColor.white.withAlphaComponent(0), ending: .white)!
g.draw(in: NSRect(x: 0, y: CGFloat(H) - 110, width: CGFloat(W), height: 110), angle: 90)

NSGraphicsContext.current = nil
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[2]))
print("wrote \(a[2])")
