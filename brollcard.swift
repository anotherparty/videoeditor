// brollcard.swift — turn a screenshot (article, Substack post, letter) into a full-screen 9:16 B-roll card,
// with optional highlighter "marks" on phrases that stagereel sweeps in one after another.
//
//   swift brollcard.swift --in shot.png --out card.jpg [--crop x,y,w,h] [--bg 18191B]
//       [--mark "my friend Adam Roberts" --mark "Concrete Carnival" ...] [--color 8B3DFF] [--size split]
//
// Writes card.jpg plus card.json = {"image": ..., "marks": [{"patch","x","y","w","h","group","phrase"}]}.
// Marks are found with on-device OCR (Vision); a phrase that wraps lines becomes several patches in one group.
// Use it in beats.json:  {"type":"broll","card":"card.json","kb":"none","from":"...","to":"..."}
// Image sits under the title band (top 330px) and above the low caption zone; captions drop low during B-roll.
import AppKit
import Vision

let A = CommandLine.arguments
func arg(_ k: String) -> String? { if let i = A.firstIndex(of: k), i + 1 < A.count { return A[i + 1] }; return nil }
func args(_ k: String) -> [String] { A.indices.filter { A[$0] == k && $0 + 1 < A.count }.map { A[$0 + 1] } }
func hex(_ s: String) -> (CGFloat, CGFloat, CGFloat) {
    var v: UInt64 = 0; Scanner(string: s.replacingOccurrences(of: "#", with: "")).scanHexInt64(&v)
    return (CGFloat((v >> 16) & 255) / 255, CGFloat((v >> 8) & 255) / 255, CGFloat(v & 255) / 255)
}
guard let inP = arg("--in"), let outP = arg("--out"),
      let src = NSImage(contentsOfFile: inP)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("usage: brollcard.swift --in IMG --out card.jpg [--crop x,y,w,h] [--bg HEX] [--mark PHRASE]... [--color HEX]\n".data(using: .utf8)!); exit(2)
}
var r = CGRect(x: 0, y: 0, width: src.width, height: src.height)
if let c = arg("--crop") { let p = c.split(separator: ",").compactMap { Double($0) }; if p.count == 4 { r = CGRect(x: p[0], y: p[1], width: p[2], height: p[3]) } }
let crop = src.cropping(to: r)!
let SPLIT = arg("--size") == "split"            // split: 1080x960 card for the top half of a split screen
let W = 1080, H = SPLIT ? 960 : 1920
let bg = hex(arg("--bg") ?? "18191B")
let mk = hex(arg("--color") ?? "8B3DFF")
let darkBg = (bg.0 + bg.1 + bg.2) / 3 < 0.5

let space = CGColorSpaceCreateDeviceRGB()
func newCtx(_ w: Int, _ h: Int) -> CGContext {
    CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: space,
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
}
let ctx = newCtx(W, H)
ctx.setFillColor(red: bg.0, green: bg.1, blue: bg.2, alpha: 1); ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
let maxW = SPLIT ? 1000.0 : 880.0, maxH = SPLIT ? 560.0 : 800.0, ar = r.width / r.height
var w = maxW, h = w / ar; if h > maxH { h = maxH; w = h * ar }
let topY = SPLIT ? 320.0 : 330.0   // both sit under the title band (ends ~300px)
let place = CGRect(x: (Double(W) - w) / 2, y: Double(H) - topY - h, width: w, height: h)   // CG coords, origin bottom-left
ctx.interpolationQuality = .high
ctx.draw(crop, in: place)
let card = ctx.makeImage()!

func save(_ img: CGImage, _ path: String, png: Bool = false) {
    let rep = NSBitmapImageRep(cgImage: img)
    let d = png ? rep.representation(using: .png, properties: [:])! : rep.representation(using: .jpeg, properties: [.compressionFactor: 0.92])!
    try! d.write(to: URL(fileURLWithPath: path))
}
save(card, outP)

// ---- marks: OCR the crop, find each phrase across lines ----
let phrases = args("--mark")
var marks: [[String: Any]] = []
if !phrases.isEmpty {
    let req = VNRecognizeTextRequest(); req.recognitionLevel = .accurate; req.usesLanguageCorrection = true
    try? VNImageRequestHandler(cgImage: crop, options: [:]).perform([req])
    let obs = (req.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }   // top to bottom
    let lines = obs.compactMap { $0.topCandidates(1).first }
    // one searchable string; remember which line owns each character
    var full = "", owner: [(Int, Int)] = []   // (line, offset in line)
    for (li, l) in lines.enumerated() {
        for (ci, _) in l.string.enumerated() { owner.append((li, ci)) }
        full += l.string; owner.append((li, -1)); full += " "
    }
    let norm = { (s: String) in s.lowercased().replacingOccurrences(of: "’", with: "'").replacingOccurrences(of: "“", with: "\"").replacingOccurrences(of: "”", with: "\"") }
    let hay = Array(norm(full))
    for (gi, ph) in phrases.enumerated() {
        let needle = Array(norm(ph))
        guard let at = (0...max(0, hay.count - needle.count)).first(where: { Array(hay[$0..<min(hay.count, $0 + needle.count)]) == needle }) else {
            FileHandle.standardError.write("WARNING: phrase not found on screenshot: \(ph)\n".data(using: .utf8)!); continue
        }
        // split the match into per-line character ranges
        var spans: [Int: (Int, Int)] = [:]
        for k in at..<(at + needle.count) {
            let (li, ci) = owner[k]; if ci < 0 { continue }
            let s = spans[li] ?? (ci, ci); spans[li] = (min(s.0, ci), max(s.1, ci))
        }
        for li in spans.keys.sorted() {
            let (a, b) = spans[li]!, str = lines[li].string
            let lo = str.index(str.startIndex, offsetBy: a), hi = str.index(str.startIndex, offsetBy: b + 1)
            guard let bb = try? lines[li].boundingBox(for: lo..<hi)?.boundingBox else { continue }
            // crop-normalized (bottom-left) -> card px (bottom-left), padded
            var rc = CGRect(x: place.minX + bb.minX * place.width, y: place.minY + bb.minY * place.height,
                            width: bb.width * place.width, height: bb.height * place.height).insetBy(dx: -8, dy: -6)
            rc = rc.integral.intersection(CGRect(x: 0, y: 0, width: W, height: H))
            // patch = that slice of the card with the highlighter blended under the text
            let pc = newCtx(Int(rc.width), Int(rc.height))
            pc.draw(card, in: CGRect(x: -rc.minX, y: -rc.minY, width: CGFloat(W), height: CGFloat(H)))
            pc.setBlendMode(darkBg ? .lighten : .multiply)       // light text stays light / dark text stays dark
            pc.setFillColor(red: mk.0, green: mk.1, blue: mk.2, alpha: 1)
            pc.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: rc.width, height: rc.height), cornerWidth: 8, cornerHeight: 8, transform: nil))
            pc.fillPath()
            let pp = outP.replacingOccurrences(of: ".jpg", with: "") + "_m\(marks.count).png"
            save(pc.makeImage()!, pp, png: true)
            marks.append(["patch": pp, "x": rc.minX, "y": CGFloat(H) - rc.maxY, "w": rc.width, "h": rc.height, "group": gi, "phrase": ph])
        }
    }
}
let jp = outP.replacingOccurrences(of: ".jpg", with: ".json")
let d = try! JSONSerialization.data(withJSONObject: ["image": outP, "marks": marks], options: [.prettyPrinted])
try! d.write(to: URL(fileURLWithPath: jp))
print("wrote \(outP) (\(Int(w))x\(Int(h))) + \(marks.count) mark patches -> \(jp)")
