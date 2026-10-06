// Another Party — reel cover maker (Oct 2026)
// Instagram crops reels to 3:4 on the profile grid (cuts ~12.5% off the top and bottom), so the
// reel's own top band disappears there. This builds a 1080x1920 cover with the logo + headline
// inside the 3:4 safe area, never on Adam's head (Vision finds the face).
//
//   swift cover.swift --in SOURCE.mov --at 12.5 --title "Tennessee couldn't kill her." \
//       [--accent "So they closed the curtain."] [--date 9/30/26] [--out cover.jpg]
//       [--candidates]     # instead of one cover, write a contact sheet of 8 frames to pick --at from
//
// Writes OUT (1080x1920 jpg, upload as the IG cover / YT thumbnail) and OUT-grid.jpg (the 3:4
// crop Instagram's profile grid will show) so you can check what survives the crop.
import AVFoundation
import AppKit
import Vision

func arg(_ k: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: k), i+1 < a.count { return a[i+1] }
    return nil
}
func die(_ m: String) -> Never { FileHandle.standardError.write((m+"\n").data(using:.utf8)!); exit(1) }
guard let SRC = arg("--in") else { die("need --in SOURCE") }
let OUT = arg("--out") ?? (SRC as NSString).deletingPathExtension + "_cover.jpg"
let TITLE = arg("--title") ?? ""
let ACCENT = arg("--accent")
let DATE = arg("--date")
// logo: --logo, else brand/ next to this script (kept outside ~/Documents so the login agent can read it)
let LOGO = arg("--logo") ?? URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    .appendingPathComponent("brand/another-party-logo.png").path
let W: CGFloat = 1080, H: CGFloat = 1920
let SAFE_TOP: CGFloat = H * 0.125 + 30, SAFE_BOT: CGFloat = H * 0.125 + 30   // 3:4 grid crop + margin
let mint = NSColor(calibratedRed: 0.20, green: 0.95, blue: 0.78, alpha: 1)
let purple = NSColor(calibratedRed: 0.55, green: 0.18, blue: 0.95, alpha: 1)

let gen = AVAssetImageGenerator(asset: AVURLAsset(url: URL(fileURLWithPath: SRC)))
gen.appliesPreferredTrackTransform = true
gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
func frame(_ t: Double) -> CGImage {
    guard let cg = try? gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil) else { die("no frame at \(t)") }
    return cg
}
func render(_ size: CGSize, _ body: (CGContext) -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width), pixelsHigh: Int(size.height),
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = ctx
    body(ctx.cgContext)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}
func save(_ rep: NSBitmapImageRep, _ path: String) {
    try! rep.representation(using: .jpeg, properties: [.compressionFactor: 0.9])!.write(to: URL(fileURLWithPath: path))
}

// --candidates: contact sheet to choose a frame
if CommandLine.arguments.contains("--candidates") {
    let dur = (try? AVURLAsset(url: URL(fileURLWithPath: SRC)).duration.seconds) ?? 60
    let ts = (0..<8).map { dur * (0.06 + 0.11 * Double($0)) }
    let cw: CGFloat = 270, ch: CGFloat = 480
    let rep = render(CGSize(width: cw*4, height: ch*2)) { g in
        for (i, t) in ts.enumerated() {
            let r = CGRect(x: CGFloat(i % 4) * cw, y: CGFloat(1 - i / 4) * ch, width: cw, height: ch)
            g.draw(frame(t), in: r)
            ("\(String(format: "%.1f", t))s" as NSString).draw(at: NSPoint(x: r.minX + 10, y: r.minY + 10),
                withAttributes: [.font: NSFont.boldSystemFont(ofSize: 30), .foregroundColor: NSColor.yellow])
        }
    }
    save(rep, OUT); print("candidates -> \(OUT)"); exit(0)
}

guard let atS = arg("--at"), let AT = Double(atS) else { die("need --at SECONDS (run --candidates to pick)") }
let cg = frame(AT)

// face -> head box in cover coords (y from top)
let req = VNDetectFaceRectanglesRequest()
try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
var head = CGRect(x: W*0.3, y: H*0.15, width: W*0.4, height: H*0.35)
if let bb = (req.results ?? []).max(by: { $0.boundingBox.width < $1.boundingBox.width })?.boundingBox {
    let top = (1 - bb.maxY - 0.70 * bb.height) * H, bot = (1 - bb.minY + 0.25 * bb.height) * H   // beard/jaw allowance
    head = CGRect(x: (bb.minX - 0.25 * bb.width) * W, y: top, width: bb.width * 1.5 * W, height: bot - top)
} else { FileHandle.standardError.write("WARNING: no face found; using a default head zone\n".data(using: .utf8)!) }

let font = { (s: CGFloat) in NSFont(name: "AvenirNext-Heavy", size: s) ?? NSFont.boldSystemFont(ofSize: s) }
func attrs(_ s: CGFloat, _ c: NSColor) -> [NSAttributedString.Key: Any] {
    let sh = NSShadow(); sh.shadowColor = NSColor.black.withAlphaComponent(0.95)
    sh.shadowOffset = NSSize(width: s*0.05, height: -s*0.07); sh.shadowBlurRadius = 0
    return [.font: font(s), .foregroundColor: c, .shadow: sh, .kern: 1.0]
}
// greedy line wrap in caps
func wrap(_ t: String, _ s: CGFloat, _ maxW: CGFloat) -> [String] {
    var lines: [String] = [], cur = ""
    for w in t.uppercased().split(separator: " ") {
        let cand = cur.isEmpty ? String(w) : cur + " " + w
        if (cand as NSString).size(withAttributes: [.font: font(s)]).width > maxW && !cur.isEmpty { lines.append(cur); cur = String(w) }
        else { cur = cand }
    }
    if !cur.isEmpty { lines.append(cur) }
    return lines
}
// same line count, but as even as possible (no lone word stranded on the last line)
func balanced(_ t: String, _ s: CGFloat, _ maxW: CGFloat) -> [String] {
    let base = wrap(t, s, maxW); guard base.count > 1 else { return base }
    var best = base, bestSpread = CGFloat.greatestFiniteMagnitude
    var w = maxW
    while w > maxW * 0.45 {
        let l = wrap(t, s, w); if l.count != base.count { w -= 10; continue }
        let ws = l.map { ($0 as NSString).size(withAttributes: [.font: font(s)]).width }
        let spread = ws.max()! - ws.min()!
        if spread < bestSpread { bestSpread = spread; best = l }
        w -= 10
    }
    return best
}
// headline block: TITLE lines in white, ACCENT lines mint on purple blocks. Goes on whichever side of the
// head has more room inside the 3:4 safe area: above the head (under the logo) or below the chin.
// Shrinks until it fits; never overlaps the head.
let maxW = W * 0.90
var size: CGFloat = 112
var tl: [String] = [], al: [String] = []
var blockH: CGFloat = 0
let logoBottom = SAFE_TOP + W * 0.30 * 0.62 + 24                 // room for the logo (approx aspect)
let availAbove = head.minY - 30 - logoBottom, availBelow = (H - SAFE_BOT) - (head.maxY + 24)
let ABOVE = availAbove > availBelow
let avail = max(availAbove, availBelow)
while size >= 56 {
    tl = balanced(TITLE, size, maxW); al = ACCENT.map { balanced($0, size, maxW) } ?? []
    blockH = CGFloat(tl.count + al.count) * size * 1.12 + (DATE != nil ? size * 0.55 : 0)
    if blockH <= avail { break }
    size -= 6
}
if blockH > avail { FileHandle.standardError.write("WARNING: headline crowds the face; pick a frame where Adam sits higher (--at)\n".data(using: .utf8)!) }
let blockTop = ABOVE ? logoBottom + max(0, (availAbove - blockH) / 2)    // centered in the open wall above the head
                    : (H - SAFE_BOT) - blockH                            // bottom-aligned below the chin

let logoImg = NSImage(contentsOfFile: LOGO)!
let logoCG = logoImg.cgImage(forProposedRect: nil, context: nil, hints: nil)!
let logoW = W * 0.30, logoH = logoW * CGFloat(logoCG.height) / CGFloat(logoCG.width)
// logo: top-left of the safe area; if that hits the head, top-right; else smaller
var logoRect = CGRect(x: 30, y: SAFE_TOP, width: logoW, height: logoH)              // y from top
if logoRect.intersects(head) { logoRect.origin.x = W - 30 - logoW }
if logoRect.intersects(head) { logoRect = CGRect(x: 24, y: SAFE_TOP - 20, width: logoW * 0.7, height: logoH * 0.7) }
if logoRect.intersects(head) { FileHandle.standardError.write("WARNING: logo touches the head\n".data(using: .utf8)!) }

let rep = render(CGSize(width: W, height: H)) { g in
    // background frame, aspect-fill
    let iw = CGFloat(cg.width), ih = CGFloat(cg.height), sc = max(W/iw, H/ih)
    g.draw(cg, in: CGRect(x: (W - iw*sc)/2, y: (H - ih*sc)/2, width: iw*sc, height: ih*sc))
    // soft dark gradient behind the headline for legibility
    let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
        colors: [NSColor.black.withAlphaComponent(0).cgColor, NSColor.black.withAlphaComponent(0.55).cgColor] as CFArray, locations: [0, 1])!
    g.drawLinearGradient(grad, start: CGPoint(x: 0, y: H - blockTop + 120), end: CGPoint(x: 0, y: 0), options: [])
    g.draw(logoCG, in: CGRect(x: logoRect.minX, y: H - logoRect.maxY, width: logoRect.width, height: logoRect.height))
    var y = blockTop                                // y from top, walking down
    for line in tl {
        let a = NSAttributedString(string: line, attributes: attrs(size, .white))
        a.draw(at: NSPoint(x: (W - a.size().width)/2, y: H - y - size * 1.12 + size * 0.1)); y += size * 1.12
    }
    for line in al {
        let a = NSAttributedString(string: line, attributes: attrs(size, mint))
        let sz = a.size(), x = (W - sz.width)/2, base = H - y - size * 1.12 + size * 0.1
        g.setFillColor(purple.cgColor)
        g.addPath(CGPath(roundedRect: CGRect(x: x - 14, y: base + size * 0.16, width: sz.width + 28, height: size * 0.86),
                         cornerWidth: 12, cornerHeight: 12, transform: nil)); g.fillPath()
        a.draw(at: NSPoint(x: x, y: base)); y += size * 1.12
    }
    if let d = DATE {
        let a = NSAttributedString(string: d, attributes: attrs(size * 0.42, mint))
        a.draw(at: NSPoint(x: (W - a.size().width)/2, y: H - y - size * 0.5))
    }
}
save(rep, OUT)
// 3:4 grid preview (what the IG profile grid shows)
let gh = W * 4 / 3
let crop = rep.cgImage!.cropping(to: CGRect(x: 0, y: (H - gh)/2, width: W, height: gh))!
let grid = NSBitmapImageRep(cgImage: crop)
save(grid, (OUT as NSString).deletingPathExtension + "-grid.jpg")
print(String(format: "OK %@ (headline %.0fpt, %d+%d lines; grid preview saved)", OUT, size, tl.count, al.count))
