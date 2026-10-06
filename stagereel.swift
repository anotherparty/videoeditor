// Another Party — stage-reel pipeline (Moth-style stage story -> captioned vertical reel)
// Native AVFoundation, no ffmpeg. Output 1080x1920 H.264 mp4.
//
// Usage:
//   swift stagereel.swift --in IN.mov --out OUT.mp4 \
//     --cuts "42.6-52.5,104-125"        # source ranges (sec) kept & concatenated, in order
//     [--cues cues.json]                # caption cues in OUTPUT time (sec, content timeline)
//     [--sticker "BOOK REPORT · Port Washington · 9/2"]
//     [--cta "The saga continues."]     # end card headline; omit --cta AND pass --no-endcard for none
//     [--no-endcard] [--logo L.png] [--handle @anotherparty25]
//     [--style classic|btb]             # btb = Books-Through-Bars look (Adam's pick, Sept 2026):
//                                       #   big ALL-CAPS karaoke captions lower third, active word mint
//                                       #   on a purple block; sticker becomes a black info box at top;
//                                       #   large logo top-left. Needs cues with per-word "words".
//     [--zoom 1.35 --focus 0.5,0.45]    # punch-in, scaled about focus point (fractions of frame, y from top)
//     [--edit edit.json]                # B-roll cutaways (+ Adam in a bubble), jump-zoom punches, animated
//                                       #   graphics (counter, slam, curtain). Build it from phrases with editplan.py.
//
// btb top band is HEAD-AWARE: Vision finds the face, and the logo + info box are sized/placed so they
// never sit on Adam's head or hair (standing rule, Oct 2026). It prints a WARNING if they can't fit.
//
// Layout: captions in the TOP band (clean ceiling, clear of a drifting head);
//         event sticker in the LOWER third over the crowd; AP watermark bottom-left;
//         appended end card (logo + handle + CTA).
import AVFoundation
import AppKit
import Vision

// ---------- args ----------
func arg(_ k: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: k), i+1 < a.count { return a[i+1] }
    return nil
}
func flag(_ k: String) -> Bool { CommandLine.arguments.contains(k) }
func die(_ m: String) -> Never { FileHandle.standardError.write((m+"\n").data(using:.utf8)!); exit(1) }

guard let SRC = arg("--in") else { die("need --in IN.mov") }
let OUT = arg("--out") ?? (SRC as NSString).deletingPathExtension + "_stagereel.mp4"
let LOGO = arg("--logo") ?? "/Users/adamroberts/Documents/Adam-HQ/Another-Party/brand/another-party-logo.png"
let HANDLE = arg("--handle") ?? "@anotherparty25"
let CTA = arg("--cta")
let STICKER = arg("--sticker")
let HAS_ENDCARD = !flag("--no-endcard")
let STYLE = arg("--style") ?? "classic"
let TAG = arg("--tag")          // btb: small per-video title tag under the info box (tells reels apart)
let DATE = arg("--date")        // btb: date line inside the info box
let ZOOM = CGFloat(Double(arg("--zoom") ?? "1") ?? 1)
let FOCUS: (CGFloat, CGFloat) = {
    let p = (arg("--focus") ?? "0.5,0.45").split(separator: ",").compactMap { Double($0) }
    return p.count == 2 ? (CGFloat(p[0]), CGFloat(p[1])) : (0.5, 0.45)
}()

// cut list -> [(start,end)]
guard let cutsStr = arg("--cuts"), !cutsStr.isEmpty else { die("need --cuts \"a-b,c-d\"") }
let CUTS: [(Double,Double)] = cutsStr.split(separator: ",").compactMap { piece in
    let p = piece.split(separator: "-").compactMap { Double($0) }
    guard p.count == 2, p[1] > p[0] else { return nil }
    return (p[0], p[1])
}
if CUTS.isEmpty { die("no valid cuts parsed from: \(cutsStr)") }

// caption cues (OUTPUT time, content timeline)
struct CueWord { let start: Double; let end: Double; let text: String }
struct Cue { let start: Double; let end: Double; let text: String; var words: [CueWord] = [] }
var CUES: [Cue] = []
if let cuesPath = arg("--cues"), let data = FileManager.default.contents(atPath: cuesPath),
   let arr = try? JSONSerialization.jsonObject(with: data) as? [[String:Any]] {
    for o in arr {
        if let s = o["start"] as? Double, let e = o["end"] as? Double, let t = o["text"] as? String {
            var c = Cue(start: s, end: e, text: t)
            for w in (o["words"] as? [[String:Any]]) ?? [] {
                if let ws = w["start"] as? Double, let we = w["end"] as? Double, let wt = w["text"] as? String {
                    c.words.append(CueWord(start: ws, end: we, text: wt))
                }
            }
            CUES.append(c)
        }
    }
}

// photo insets (OUTPUT time, content timeline)
struct Inset { let path: String; let start: Double; let end: Double }
var INSETS: [Inset] = []
if let insPath = arg("--insets"), let data = FileManager.default.contents(atPath: insPath),
   let arr = try? JSONSerialization.jsonObject(with: data) as? [[String:Any]] {
    for o in arr {
        if let p = o["image"] as? String, let s = o["start"] as? Double, let e = o["end"] as? Double {
            INSETS.append(Inset(path: p, start: s, end: e))
        }
    }
}

// edit plan (OUTPUT time, content timeline) — see editplan.py
struct Punch { let start: Double; let end: Double; let zoom: CGFloat; let focus: (CGFloat, CGFloat) }
struct Broll { let image: String?; let color: String?; let start: Double; let end: Double
               let bubble: String; let label: String?; let kb: String
               var marks: [[String: Any]] = []    // highlighter patches from brollcard.swift, each with "start"
               var layout: String = "full"        // full (cutaway + bubble) | split (image top half, Adam bottom half)
               var video: String? = nil }         // stock video clip: always split (the bubble can't show a second video)
var PUNCHES: [Punch] = [], BROLLS: [Broll] = [], GRAPHICS: [[String:Any]] = [], NOCAPS: [(Double,Double)] = []
if let ep = arg("--edit") {
    guard let data = FileManager.default.contents(atPath: ep),
          let o = try? JSONSerialization.jsonObject(with: data) as? [String:Any] else { die("bad --edit \(ep)") }
    for p in (o["punch"] as? [[String:Any]]) ?? [] {
        let f = (p["focus"] as? [Double]) ?? [0.5, 0.42]
        PUNCHES.append(Punch(start: p["start"] as! Double, end: p["end"] as! Double,
                             zoom: CGFloat(p["zoom"] as? Double ?? 1.4), focus: (CGFloat(f[0]), CGFloat(f[1]))))
    }
    for b in (o["broll"] as? [[String:Any]]) ?? [] {
        BROLLS.append(Broll(image: b["image"] as? String, color: b["color"] as? String,
                            start: b["start"] as! Double, end: b["end"] as! Double,
                            bubble: b["bubble"] as? String ?? "br", label: b["label"] as? String, kb: b["kb"] as? String ?? "in",
                            marks: b["marks"] as? [[String: Any]] ?? [], layout: b["video"] != nil ? "split" : (b["layout"] as? String ?? "full"),
                            video: b["video"] as? String))
    }
    GRAPHICS = (o["graphics"] as? [[String:Any]]) ?? []
    NOCAPS = ((o["nocaps"] as? [[Double]]) ?? []).map { ($0[0], $0[1]) }
}

let W = 1080, H = 1920
let FPS: Int32 = 30
let ENDCARD_SECS = 2.6
let TS: CMTimeScale = 600
let cream = NSColor(calibratedRed: 247/255.0, green: 241/255.0, blue: 230/255.0, alpha: 1)
let brandRed = NSColor(calibratedRed: 178/255.0, green: 46/255.0, blue: 38/255.0, alpha: 1)
let charcoal = NSColor(calibratedRed: 58/255.0, green: 46/255.0, blue: 42/255.0, alpha: 1)

guard let logoImg = NSImage(contentsOfFile: LOGO),
      let logoCG = logoImg.cgImage(forProposedRect: nil, context: nil, hints: nil) else { die("logo load failed: \(LOGO)") }
let logoAR = CGFloat(logoCG.width) / CGFloat(logoCG.height)

func font(_ sz: CGFloat, _ bold: Bool = true) -> NSFont {
    NSFont(name: bold ? "HelveticaNeue-Bold" : "HelveticaNeue-Medium", size: sz)
        ?? NSFont.systemFont(ofSize: sz, weight: bold ? .bold : .medium)
}

// ---------- end card ----------
let SCRATCH = NSTemporaryDirectory()
let ENDCARD = "\(SCRATCH)/ap_stage_endcard_\(getpid()).mp4"
func makeEndCardImage() -> CGImage {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: W, pixelsHigh: H,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = ctx
    let g = ctx.cgContext
    g.setFillColor(cream.cgColor); g.fill(CGRect(x:0,y:0,width:W,height:H))
    let para = NSMutableParagraphStyle(); para.alignment = .center
    let lw = CGFloat(W)*0.60, lh = (CGFloat(W)*0.60)/logoAR
    struct Item { let draw: (CGFloat)->Void; let h: CGFloat; let gap: CGFloat }
    var items = [Item]()
    items.append(Item(draw: { y in g.draw(logoCG, in: CGRect(x:(CGFloat(W)-lw)/2, y:y, width:lw, height:lh)) }, h: lh, gap: 56))
    func textItem(_ str: String, _ sz: CGFloat, _ col: NSColor, _ bold: Bool, gap: CGFloat) {
        let a = NSAttributedString(string: str, attributes: [.font: font(sz, bold), .foregroundColor: col, .paragraphStyle: para, .kern: 1.0])
        let maxW = CGFloat(W) - 120
        let br = a.boundingRect(with: CGSize(width: maxW, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin])
        let hh = ceil(br.height)
        items.append(Item(draw: { y in a.draw(with: CGRect(x:60, y:y, width:maxW, height:hh+10), options:[.usesLineFragmentOrigin]) }, h: hh, gap: gap))
    }
    if let cta = CTA { textItem(cta, 64, brandRed, true, gap: 24) }
    textItem(HANDLE, 50, charcoal, false, gap: 0)
    let totalH = items.reduce(0){ $0 + $1.h } + items.dropLast().reduce(0){ $0 + $1.gap }
    var y = (CGFloat(H) + totalH)/2
    for it in items { y -= it.h; it.draw(y); y -= it.gap }
    NSGraphicsContext.restoreGraphicsState()
    return rep.cgImage!
}
func pixelBuffer(from cg: CGImage) -> CVPixelBuffer {
    var pb: CVPixelBuffer?
    CVPixelBufferCreate(kCFAllocatorDefault, W, H, kCVPixelFormatType_32ARGB,
        [kCVPixelBufferCGImageCompatibilityKey as String: true,
         kCVPixelBufferCGBitmapContextCompatibilityKey as String: true] as CFDictionary, &pb)
    guard let buf = pb else { die("pb") }
    CVPixelBufferLockBaseAddress(buf, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: W, height: H, bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
    ctx.draw(cg, in: CGRect(x:0,y:0,width:W,height:H))
    CVPixelBufferUnlockBaseAddress(buf, [])
    return buf
}
func renderEndCard() {
    try? FileManager.default.removeItem(atPath: ENDCARD)
    let writer = try! AVAssetWriter(outputURL: URL(fileURLWithPath: ENDCARD), fileType: .mp4)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings:
        [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: W, AVVideoHeightKey: H])
    input.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
    writer.add(input); writer.startWriting(); writer.startSession(atSourceTime: .zero)
    let buf = pixelBuffer(from: makeEndCardImage())
    let total = Int(ENDCARD_SECS * Double(FPS)); var f = 0
    let sem = DispatchSemaphore(value: 0)
    input.requestMediaDataWhenReady(on: DispatchQueue(label:"ec")) {
        while input.isReadyForMoreMediaData {
            if f >= total { input.markAsFinished(); sem.signal(); return }
            adaptor.append(buf, withPresentationTime: CMTime(value: CMTimeValue(f), timescale: FPS)); f += 1
        }
    }
    sem.wait()
    let done = DispatchSemaphore(value: 0); writer.finishWriting { done.signal() }; done.wait()
    if writer.status != .completed { die("endcard writer: \(String(describing: writer.error))") }
}

// ---------- overlay layer helpers ----------
// discrete opacity window over [showStart, showEnd] of a `total`-second timeline
func addWindow(_ layer: CALayer, showStart: Double, showEnd: Double, total: Double) {
    let s = max(0.0001, min(0.9997, showStart/total))
    let e = max(s+0.0001, min(0.9998, showEnd/total))
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values = [0, 1, 0, 0]
    anim.keyTimes = [0, NSNumber(value: s), NSNumber(value: e), 1.0]
    anim.calculationMode = .discrete
    anim.beginTime = AVCoreAnimationBeginTimeAtZero; anim.duration = total
    anim.isRemovedOnCompletion = false; anim.fillMode = .forwards
    layer.opacity = 0
    layer.add(anim, forKey: "win")
}
// smooth fade in/out over [showStart, showEnd] of a `total`-second timeline
func addFadeWindow(_ layer: CALayer, showStart: Double, showEnd: Double, total: Double, fade: Double = 0.35) {
    let f = fade / total
    var s = max(0.0, showStart/total)
    var e = min(1.0, showEnd/total)
    if e - s < 2*f + 0.002 { let mid = (s+e)/2; s = max(0, mid - f - 0.001); e = min(1, mid + f + 0.001) }
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values  = [0, 0, 1, 1, 0, 0]
    anim.keyTimes = [0, NSNumber(value: s), NSNumber(value: min(s+f, e-0.001)),
                     NSNumber(value: max(e-f, s+0.001)), NSNumber(value: e), 1.0]
    anim.beginTime = AVCoreAnimationBeginTimeAtZero; anim.duration = total
    anim.isRemovedOnCompletion = false; anim.fillMode = .forwards
    layer.opacity = 0
    layer.add(anim, forKey: "fade")
}
func addVisibleUntil(_ layer: CALayer, contentDur: Double, total: Double) {
    guard total > contentDur + 0.01 else { layer.opacity = 1; return }
    let c = min(0.9998, contentDur/total)
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values = [1, 0, 0]; anim.keyTimes = [0, NSNumber(value: c), 1.0]
    anim.calculationMode = .discrete
    anim.beginTime = AVCoreAnimationBeginTimeAtZero; anim.duration = total
    anim.isRemovedOnCompletion = false; anim.fillMode = .forwards
    layer.add(anim, forKey: "vis")
}

// Render a rounded "pill" (bg + centered text) to a bitmap CGImage. Bitmaps render reliably
// inside AVVideoCompositionCoreAnimationTool; CATextLayer does not (fonts fail on the render thread).
// Returns (image, pointSize). Drawn at 2x for crispness.
func pillImage(_ text: String, fsize: CGFloat, textColor: NSColor, bg: NSColor,
               padX: CGFloat, padY: CGFloat, corner: CGFloat, maxTextW: CGFloat, kern: CGFloat)
               -> (CGImage, CGSize) {
    let para = NSMutableParagraphStyle(); para.alignment = .center; para.lineBreakMode = .byWordWrapping
    let attrs: [NSAttributedString.Key: Any] = [.font: font(fsize, true), .foregroundColor: textColor, .paragraphStyle: para, .kern: kern]
    let a = NSAttributedString(string: text, attributes: attrs)
    let br = a.boundingRect(with: CGSize(width: maxTextW, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin])
    let textW = ceil(br.width), textH = ceil(br.height)
    let pillW = textW + padX*2, pillH = textH + padY*2
    let scale: CGFloat = 2
    let pxW = Int(pillW*scale), pxH = Int(pillH*scale)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pxW, pixelsHigh: pxH,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = ctx
    let g = ctx.cgContext
    g.scaleBy(x: scale, y: scale)
    let path = CGPath(roundedRect: CGRect(x:0, y:0, width: pillW, height: pillH), cornerWidth: corner, cornerHeight: corner, transform: nil)
    g.addPath(path); g.setFillColor(bg.cgColor); g.fillPath()
    // center text vertically in the pill
    let ty = (pillH - textH)/2
    a.draw(with: CGRect(x: padX, y: ty, width: textW, height: textH+6), options: [.usesLineFragmentOrigin])
    NSGraphicsContext.restoreGraphicsState()
    return (rep.cgImage!, CGSize(width: pillW, height: pillH))
}

// sticker visibility: shown over plain footage, faded OUT while any photo inset is on screen,
// and off during the end card.
func addStickerVisibility(_ layer: CALayer, contentDur: Double, total: Double,
                          insets: [Inset], fade: Double = 0.3, pad: Double = 0.3) {
    let wins = insets.map { (max(0.0, $0.start - pad), min(contentDur, $0.end + pad)) }
                     .filter { $0.0 < $0.1 }.sorted { $0.0 < $1.0 }
    var merged: [(Double,Double)] = []
    for w in wins {
        if let last = merged.last, w.0 <= last.1 + 2*fade { merged[merged.count-1] = (last.0, max(last.1, w.1)) }
        else { merged.append(w) }
    }
    var pts: [(Double,Double)] = [(0.0, 1.0)]
    func add(_ t: Double, _ o: Double) {
        let tt = min(max(t, 0), total)
        if let l = pts.last, tt <= l.0 + 1e-4 { pts[pts.count-1] = (l.0, o) } else { pts.append((tt, o)) }
    }
    for (s,e) in merged {
        if s <= 0.001 { pts[0] = (0.0, 0.0) } else { add(s - fade, 1.0); add(s, 0.0) }
        add(e, 0.0)
        if e < contentDur - 0.001 { add(e + fade, 1.0) }
    }
    add(contentDur - 0.05, pts.last!.1); add(contentDur, 0.0)
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values = pts.map { NSNumber(value: $0.1) }
    anim.keyTimes = pts.map { NSNumber(value: min(0.99999, max(0.0, $0.0/total))) }
    anim.calculationMode = .linear
    anim.beginTime = AVCoreAnimationBeginTimeAtZero; anim.duration = total
    anim.isRemovedOnCompletion = false; anim.fillMode = .forwards
    layer.opacity = 1
    layer.add(anim, forKey: "stickvis")
}

// caption pill: white bold text on a translucent dark rounded bar, centered, in the TOP band
func makeCaption(_ text: String) -> CALayer {
    let (img, sz) = pillImage(text, fsize: 62, textColor: .white,
        bg: NSColor(calibratedWhite: 0, alpha: 0.52), padX: 34, padY: 22, corner: 26,
        maxTextW: CGFloat(W)*0.82, kern: 0.5)
    let layer = CALayer()
    let topInset = CGFloat(H) * 0.085
    layer.frame = CGRect(x: (CGFloat(W)-sz.width)/2, y: CGFloat(H) - topInset - sz.height, width: sz.width, height: sz.height)
    layer.contents = img; layer.contentsGravity = .resize
    return layer
}

// event sticker: white bold text on a brand-red chip, centered, LOWER third over the crowd
func makeSticker(_ text: String) -> CALayer {
    let (img, sz) = pillImage(text, fsize: 40, textColor: .white,
        bg: brandRed.withAlphaComponent(0.94), padX: 40, padY: 20, corner: 999,
        maxTextW: CGFloat(W)*0.9, kern: 1.5)
    let layer = CALayer()
    layer.frame = CGRect(x: (CGFloat(W)-sz.width)/2, y: CGFloat(H)*0.17, width: sz.width, height: sz.height)
    layer.contents = img; layer.contentsGravity = .resize
    layer.shadowColor = NSColor.black.cgColor; layer.shadowOpacity = 0.35
    layer.shadowRadius = 10; layer.shadowOffset = CGSize(width: 0, height: -3)
    return layer
}

// photo inset: rounded, white-bordered card with drop shadow, sized to the image's aspect,
// seated in the lower zone (over the crowd), bottom-anchored clear of the watermark row.
func makeInset(_ path: String) -> CALayer? {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("inset load failed: \(path)\n".data(using:.utf8)!); return nil
    }
    let ar = CGFloat(cg.width) / CGFloat(cg.height)
    let maxW = CGFloat(W) * 0.84, maxH = CGFloat(H) * 0.30   // <=576px tall
    var cw = maxW, ch = cw / ar
    if ch > maxH { ch = maxH; cw = ch * ar }
    let bottomTopCoord = CGFloat(H) * 0.075                  // card bottom ~7.5% up from frame bottom (in CA y)
    let x = (CGFloat(W) - cw)/2
    let wrap = CALayer()
    wrap.frame = CGRect(x: x, y: bottomTopCoord, width: cw, height: ch)
    wrap.shadowColor = NSColor.black.cgColor; wrap.shadowOpacity = 0.5
    wrap.shadowRadius = 18; wrap.shadowOffset = CGSize(width: 0, height: -6)
    let pic = CALayer()
    pic.frame = wrap.bounds
    pic.contents = cg; pic.contentsGravity = .resizeAspectFill
    pic.cornerRadius = 22; pic.masksToBounds = true
    pic.borderWidth = 6; pic.borderColor = cream.cgColor
    wrap.addSublayer(pic)
    return wrap
}

// ---------- btb style ----------
let btbMint   = NSColor(calibratedRed: 0.20, green: 0.95, blue: 0.78, alpha: 1)
let btbPurple = NSColor(calibratedRed: 0.55, green: 0.18, blue: 0.95, alpha: 1)
func btbFont(_ sz: CGFloat) -> NSFont { NSFont(name: "AvenirNext-Heavy", size: sz) ?? font(sz, true) }
let BTB_SIZE: CGFloat = 132
let BTB_LINE: CGFloat = BTB_SIZE * 1.08
let BTB_MAXW: CGFloat = CGFloat(W) * 0.86
let BTB_LOW: CGFloat = CGFloat(H) * 0.15         // default caption block bottom edge, px up from frame bottom
var BTB_BOTTOM: CGFloat = BTB_LOW                 // face-aware: placeCaptions() may move it so captions never cover the face
let CAP_POS = arg("--cap-pos") ?? "auto"          // auto | low | high
let CAP_STYLE = arg("--cap-style") ?? "btb"       // btb (karaoke) | box (white seam box) | mono (black typewriter box)
var FACE = FaceInfo(cx: 0.5, cy: 0.35, headTop: 0.2, faceW: 0.3, found: false)
var BAND_BOTTOM: CGFloat = 0                      // px from top where the title band ends
func btbWord(_ t: String) -> String {
    t.uppercased().trimmingCharacters(in: CharacterSet(charactersIn: ".,!?;:\"“”"))
}
// lay out words into centered lines; returns per-word rects in LAYER coords (y up) + block height
func btbLayout(_ words: [String], bottom: CGFloat = BTB_BOTTOM) -> [CGRect] {
    let f = btbFont(BTB_SIZE), space = (" " as NSString).size(withAttributes: [.font: f]).width
    var lines: [[(Int, CGFloat)]] = [[]]; var lw: CGFloat = 0
    for (i, w) in words.enumerated() {
        let ww = (w as NSString).size(withAttributes: [.font: f]).width
        if !lines[lines.count-1].isEmpty && lw + space + ww > BTB_MAXW { lines.append([]); lw = 0 }
        lw += (lines[lines.count-1].isEmpty ? 0 : space) + ww
        lines[lines.count-1].append((i, ww))
    }
    var rects = [CGRect](repeating: .zero, count: words.count)
    let blockH = CGFloat(lines.count) * BTB_LINE
    for (li, line) in lines.enumerated() {
        let total = line.reduce(0){ $0 + $1.1 } + space * CGFloat(max(0, line.count-1))
        var x = (CGFloat(W) - total)/2
        let y = bottom + blockH - CGFloat(li+1) * BTB_LINE
        for (i, ww) in line { rects[i] = CGRect(x: x, y: y, width: ww, height: BTB_LINE); x += ww + space }
    }
    return rects
}
func btbDraw(_ size: CGSize, _ body: (CGContext) -> Void) -> CGImage {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width), pixelsHigh: Int(size.height),
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = ctx
    body(ctx.cgContext)
    NSGraphicsContext.restoreGraphicsState()
    return rep.cgImage!
}
func btbAttrs(_ col: NSColor, shadow: Bool) -> [NSAttributedString.Key: Any] {
    var a: [NSAttributedString.Key: Any] = [.font: btbFont(BTB_SIZE), .foregroundColor: col,
                                            .kern: 1.0]
    if shadow { let sh = NSShadow(); sh.shadowColor = NSColor.black.withAlphaComponent(0.95)
        sh.shadowOffset = NSSize(width: 7, height: -9); sh.shadowBlurRadius = 0; a[.shadow] = sh }
    return a
}
// base layer: every word white, full-frame-width strip
func btbBase(_ words: [String], _ rects: [CGRect]) -> CALayer {
    let top = rects.map { $0.maxY }.max()! + 20, bot = rects.map { $0.minY }.min()! - 20
    let img = btbDraw(CGSize(width: W, height: Int(top - bot))) { _ in
        for (w, r) in zip(words, rects) {
            (w as NSString).draw(at: NSPoint(x: r.minX, y: r.minY - bot + BTB_SIZE*0.02), withAttributes: btbAttrs(.white, shadow: true))
        }
    }
    let l = CALayer(); l.frame = CGRect(x: 0, y: bot, width: CGFloat(W), height: top - bot)
    l.contents = img; l.contentsGravity = .resize; return l
}
// active overlay: purple block + mint word, exactly over the white word
func btbActive(_ word: String, _ r: CGRect) -> CALayer {
    let pad: CGFloat = 12
    let box = r.insetBy(dx: -pad, dy: -2)
    let img = btbDraw(CGSize(width: Int(box.width) + 20, height: Int(box.height) + 20)) { g in
        let bg = CGPath(roundedRect: CGRect(x: 0, y: 2 + BTB_SIZE*0.02 + BTB_SIZE*0.21, width: box.width, height: BTB_SIZE*0.74 + 22),
                        cornerWidth: 10, cornerHeight: 10, transform: nil)
        g.addPath(bg); g.setFillColor(btbPurple.cgColor); g.fillPath()
        (word as NSString).draw(at: NSPoint(x: pad, y: 2 + BTB_SIZE*0.02), withAttributes: btbAttrs(btbMint, shadow: true))
    }
    let l = CALayer(); l.frame = CGRect(x: box.minX, y: box.minY, width: box.width + 20, height: box.height + 20)
    l.contents = img; l.contentsGravity = .resize; return l
}
// info box: black rounded box, bold italic white text, top-right beside the logo
func btbInfoBox(_ text: String) -> CALayer {
    let f = NSFont(name: "AvenirNext-HeavyItalic", size: 50) ?? font(50, true)
    let para = NSMutableParagraphStyle(); para.lineSpacing = -4
    let a = NSMutableAttributedString(string: text, attributes: [.font: f, .foregroundColor: NSColor.white, .paragraphStyle: para])
    if let d = DATE { a.append(NSAttributedString(string: "  " + d, attributes: [.font: f, .foregroundColor: btbMint, .paragraphStyle: para])) }
    let boxX = CGFloat(W) * 0.36, boxW = CGFloat(W) - boxX - 24, padX: CGFloat = 30, padY: CGFloat = 24
    let br = a.boundingRect(with: CGSize(width: boxW - padX*2, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin])
    let boxH = ceil(br.height) + padY*2
    let img = btbDraw(CGSize(width: Int(boxW), height: Int(boxH))) { g in
        g.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: boxW, height: boxH), cornerWidth: 38, cornerHeight: 38, transform: nil))
        g.setFillColor(NSColor.black.withAlphaComponent(0.92).cgColor); g.fillPath()
        a.draw(with: CGRect(x: padX, y: padY - 4, width: boxW - padX*2, height: ceil(br.height) + 8), options: [.usesLineFragmentOrigin])
    }
    let l = CALayer(); l.frame = CGRect(x: boxX, y: CGFloat(H) * 0.905 - boxH, width: boxW, height: boxH)
    l.contents = img; l.contentsGravity = .resize; return l
}

// title tag: small cream chip, brand-red caps, right-aligned under the info box
func btbTag(_ text: String, below box: CGRect) -> CALayer {
    let (img, sz) = pillImage(text.uppercased(), fsize: 34, textColor: brandRed, bg: cream.withAlphaComponent(0.96),
        padX: 26, padY: 12, corner: 14, maxTextW: box.width - 20, kern: 2.0)
    let l = CALayer(); l.frame = CGRect(x: box.maxX - sz.width, y: box.minY - 16 - sz.height, width: sz.width, height: sz.height)
    l.contents = img; l.contentsGravity = .resize
    l.shadowColor = NSColor.black.cgColor; l.shadowOpacity = 0.35; l.shadowRadius = 8; l.shadowOffset = CGSize(width: 0, height: -3)
    return l
}

// ---------- face analysis (head-aware layout + bubble framing) ----------
// Samples frames across the kept ranges, finds the face with Vision, and reports it in OUTPUT
// coordinates (normalized, y from top) after the base --zoom. headTop includes hair allowance.
struct FaceInfo { var cx: CGFloat; var cy: CGFloat; var headTop: CGFloat; var faceW: CGFloat; var found: Bool; var chin: CGFloat = 0.62 }
let CHIN_ALLOW: CGFloat = 0.25    // beard/jaw below the Vision face box, as a fraction of face height
let HAIR_ALLOW: CGFloat = 0.70     // hair/scalp above the Vision face box, as a fraction of face height
func zoomed(_ x: CGFloat, _ y: CGFloat, _ z: CGFloat, _ f: (CGFloat, CGFloat)) -> (CGFloat, CGFloat) {
    (f.0 + (x - f.0) * z, f.1 + (y - f.1) * z)
}
func analyzeFace() -> FaceInfo {
    let asset = AVURLAsset(url: URL(fileURLWithPath: SRC))
    let gen = AVAssetImageGenerator(asset: asset)
    gen.appliesPreferredTrackTransform = true
    gen.maximumSize = CGSize(width: 540, height: 960)
    gen.requestedTimeToleranceBefore = CMTime(seconds: 0.5, preferredTimescale: TS)
    gen.requestedTimeToleranceAfter = CMTime(seconds: 0.5, preferredTimescale: TS)
    var times: [Double] = []
    for (a, b) in CUTS { times.append(a + (b - a) * 0.3); times.append(a + (b - a) * 0.8) }
    if times.count > 24 { let st = Double(times.count) / 24; times = (0..<24).map { times[Int(Double($0) * st)] } }
    var cxs: [CGFloat] = [], cys: [CGFloat] = [], fws: [CGFloat] = [], tops: [CGFloat] = [], chins: [CGFloat] = []
    for t in times {
        guard let cg = try? gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: TS), actualTime: nil) else { continue }
        let req = VNDetectFaceRectanglesRequest()
        try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
        guard let bb = (req.results ?? []).max(by: { $0.boundingBox.width < $1.boundingBox.width })?.boundingBox else { continue }
        let top = 1 - bb.maxY - HAIR_ALLOW * bb.height
        cxs.append(bb.midX); cys.append(1 - bb.midY); fws.append(bb.width); tops.append(top)
        chins.append(1 - bb.minY + CHIN_ALLOW * bb.height)
    }
    guard !cxs.isEmpty else {
        FileHandle.standardError.write("WARNING: no face found; head-aware layout falls back to defaults\n".data(using: .utf8)!)
        return FaceInfo(cx: 0.5, cy: 0.35, headTop: 0.18, faceW: 0.3, found: false)
    }
    let avg = { (a: [CGFloat]) in a.reduce(0, +) / CGFloat(a.count) }
    let (cx, cy) = zoomed(avg(cxs), avg(cys), ZOOM, FOCUS)
    let ht = zoomed(0.5, tops.min()!, ZOOM, FOCUS).1
    let ch = zoomed(0.5, chins.max()!, ZOOM, FOCUS).1
    return FaceInfo(cx: cx, cy: cy, headTop: ht, faceW: avg(fws) * ZOOM, found: true, chin: ch)
}
// head top for a given punch (raw face -> punch zoom about punch focus, applied on top of base)
func punchedHeadTop(_ face: FaceInfo, _ p: Punch) -> CGFloat {
    zoomed(0.5, face.headTop, p.zoom, p.focus).1
}

// ---------- face-clear captions (btb) ----------
// Captions must never cover the face. Uses the head's extremes across all sampled frames:
// below the chin if a 2-line block fits above the IG safe zone, else in the gap between the
// title band and the top of the head, else whichever side has more room (with a warning).
func placeCaptions(face: FaceInfo, bandBottom: CGFloat) {
    let blockH = BTB_LINE * 2, gap: CGFloat = 28, safe = CGFloat(H) * 0.10
    let chinPx = face.chin * CGFloat(H), headPx = face.headTop * CGFloat(H)
    let lowRoom = CGFloat(H) - chinPx - gap - safe            // space below the chin
    let highTop = bandBottom + gap, highRoom = headPx - gap - highTop
    func high() { BTB_BOTTOM = CGFloat(H) - (highTop + max(0, highRoom - blockH) / 2) - blockH }
    func low()  { BTB_BOTTOM = min(BTB_LOW, max(safe, CGFloat(H) - chinPx - gap - blockH)) }
    var how = ""
    if CAP_POS == "low" { BTB_BOTTOM = BTB_LOW; how = "low (forced)" }
    else if CAP_POS == "high" { high(); how = "above head (forced)" }
    else if !face.found { BTB_BOTTOM = BTB_LOW; how = "low (no face found)" }
    else if lowRoom >= blockH { low(); how = "below chin" }
    else if highRoom >= blockH { high(); how = "above head" }
    else {
        if highRoom > lowRoom { high(); how = "above head (tight)" } else { low(); how = "below chin (tight)" }
        FileHandle.standardError.write("WARNING: no clean caption zone; captions may touch the face. Try --zoom/--focus.\n".data(using: .utf8)!)
    }
    print(String(format: "[captions] %@: head %.0f-%.0fpx, block bottom %.0fpx up", how, headPx, chinPx, BTB_BOTTOM))
}

// ---------- top band (btb): logo + info box + tag, kept clear of the head ----------
let TOP_MARGIN: CGFloat = CGFloat(H) * 0.035
let LOGO_W: CGFloat = CGFloat(W) * 0.22
func infoBoxImage(_ text: String, fsize: CGFloat, boxW: CGFloat) -> (CGImage, CGFloat) {
    let f = NSFont(name: "AvenirNext-HeavyItalic", size: fsize) ?? font(fsize, true)
    let para = NSMutableParagraphStyle(); para.lineSpacing = -4
    let a = NSMutableAttributedString(string: text, attributes: [.font: f, .foregroundColor: NSColor.white, .paragraphStyle: para])
    if let d = DATE { a.append(NSAttributedString(string: "  " + d, attributes: [.font: f, .foregroundColor: btbMint, .paragraphStyle: para])) }
    let padX = fsize * 0.6, padY = fsize * 0.45
    let br = a.boundingRect(with: CGSize(width: boxW - padX*2, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin])
    let boxH = ceil(br.height) + padY*2
    let img = btbDraw(CGSize(width: Int(boxW), height: Int(boxH))) { g in
        g.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: boxW, height: boxH), cornerWidth: fsize*0.7, cornerHeight: fsize*0.7, transform: nil))
        g.setFillColor(NSColor.black.withAlphaComponent(0.92).cgColor); g.fillPath()
        a.draw(with: CGRect(x: padX, y: padY - 4, width: boxW - padX*2, height: ceil(br.height) + 8), options: [.usesLineFragmentOrigin])
    }
    return (img, boxH)
}
struct TopBand { var layers: [CALayer]; var bottomFromTop: CGFloat; var logo: CALayer }
func buildTopBand(face: FaceInfo) -> TopBand {
    let lh = LOGO_W / logoAR
    let logo = CALayer()
    logo.frame = CGRect(x: 22, y: CGFloat(H) - TOP_MARGIN - lh, width: LOGO_W, height: lh)
    logo.contents = logoCG; logo.contentsGravity = .resizeAspect; logo.opacity = 0.92
    logo.shadowColor = NSColor.white.cgColor; logo.shadowOpacity = 0.7; logo.shadowRadius = 8; logo.shadowOffset = .zero
    var bottom = TOP_MARGIN + lh
    guard let st = STICKER else { return TopBand(layers: [], bottomFromTop: bottom, logo: logo) }
    let limit = face.headTop * CGFloat(H) - 24          // band must end above this (px from top)
    let boxX = 22 + LOGO_W + 22, boxW = CGFloat(W) - boxX - 24
    var chosen: (CGFloat, Bool)? = nil
    for withTag in (TAG == nil ? [false] : [true, false]) {
        for fs in stride(from: CGFloat(46), through: 28, by: -3) {
            var b = TOP_MARGIN + infoBoxImage(st, fsize: fs, boxW: boxW).1
            if withTag { b += 12 + 34 + 24 }
            if max(b, TOP_MARGIN + lh) <= limit { chosen = (fs, withTag); break }
        }
        if chosen != nil { break }
    }
    if chosen == nil {
        FileHandle.standardError.write("WARNING: title card can't clear the head even at the smallest size — ease --zoom or move --focus down\n".data(using: .utf8)!)
        chosen = (28, false)
    } else if TAG != nil && chosen!.1 == false {
        FileHandle.standardError.write("NOTE: dropped the title tag to keep the head clear\n".data(using: .utf8)!)
    }
    let (fs, withTag) = chosen!
    let (img, bh) = infoBoxImage(st, fsize: fs, boxW: boxW)
    let box = CALayer(); box.frame = CGRect(x: boxX, y: CGFloat(H) - TOP_MARGIN - bh, width: boxW, height: bh)
    box.contents = img; box.contentsGravity = .resize
    var layers = [box]
    bottom = max(bottom, TOP_MARGIN + bh)
    if withTag, let t = TAG {
        let (timg, tsz) = pillImage(t.uppercased(), fsize: 28, textColor: brandRed, bg: cream.withAlphaComponent(0.96),
            padX: 22, padY: 10, corner: 12, maxTextW: boxW - 20, kern: 2.0)
        let tg = CALayer(); tg.frame = CGRect(x: box.frame.maxX - tsz.width, y: box.frame.minY - 12 - tsz.height, width: tsz.width, height: tsz.height)
        tg.contents = timg; tg.contentsGravity = .resize
        layers.append(tg); bottom = max(bottom, TOP_MARGIN + bh + 12 + tsz.height)
    }
    print(String(format: "[layout] head top %.0fpx, top band ends %.0fpx, box font %.0f%@", face.headTop * CGFloat(H), bottom, fs, withTag ? " +tag" : ""))
    return TopBand(layers: layers, bottomFromTop: bottom, logo: logo)
}
// opacity: 1 except faded out over the given windows, 0 after content
func addHideWindows(_ layer: CALayer, hide: [(Double, Double)], contentDur: Double, total: Double, fade: Double = 0.15) {
    var pts: [(Double, Double)] = [(0, 1)]
    func add(_ t: Double, _ o: Double) {
        let tt = min(max(t, 0), total)
        if let l = pts.last, tt <= l.0 + 1e-4 { pts[pts.count-1] = (l.0, o) } else { pts.append((tt, o)) }
    }
    for (s, e) in hide.sorted(by: { $0.0 < $1.0 }) {
        if s <= 0.001 { pts[0] = (0, 0) } else { add(s - fade, 1); add(s, 0) }
        add(e, 0); if e < contentDur - 0.01 { add(e + fade, 1) }
    }
    add(contentDur - 0.03, pts.last!.1); add(contentDur, 0)
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values = pts.map { NSNumber(value: $0.1) }
    anim.keyTimes = pts.map { NSNumber(value: min(0.99999, max(0, $0.0 / total))) }
    anim.beginTime = AVCoreAnimationBeginTimeAtZero; anim.duration = total
    anim.isRemovedOnCompletion = false; anim.fillMode = .forwards
    layer.add(anim, forKey: "hidewin")
}

// ---------- B-roll, bubble, graphics ----------
func hexColor(_ h: String) -> NSColor {
    var v: UInt64 = 0; Scanner(string: h.replacingOccurrences(of: "#", with: "")).scanHexInt64(&v)
    return NSColor(calibratedRed: CGFloat((v >> 16) & 255)/255, green: CGFloat((v >> 8) & 255)/255, blue: CGFloat(v & 255)/255, alpha: 1)
}
func makeBroll(_ b: Broll, total: Double) -> CALayer {
    let box = CALayer(); box.masksToBounds = true
    box.frame = b.layout == "split" ? CGRect(x: 0, y: CGFloat(H) / 2, width: CGFloat(W), height: CGFloat(H) / 2)
                                    : CGRect(x: 0, y: 0, width: W, height: H)
    if let c = b.color { box.backgroundColor = hexColor(c).cgColor }
    if let path = b.image, let im = NSImage(contentsOfFile: path), let cg = im.cgImage(forProposedRect: nil, context: nil, hints: nil) {
        let pic = CALayer(); pic.frame = box.bounds; pic.contents = cg; pic.contentsGravity = .resizeAspectFill
        let kb = CABasicAnimation(keyPath: "transform.scale")
        kb.fromValue = b.kb == "out" ? 1.14 : 1.0; kb.toValue = b.kb == "out" ? 1.0 : (b.kb == "none" ? 1.0 : 1.14)
        kb.beginTime = AVCoreAnimationBeginTimeAtZero + b.start; kb.duration = max(0.1, b.end - b.start)
        kb.fillMode = .both; kb.isRemovedOnCompletion = false
        pic.add(kb, forKey: "kb"); box.addSublayer(pic)
        let dim = CALayer(); dim.frame = box.bounds; dim.backgroundColor = NSColor(calibratedWhite: 0, alpha: b.label != nil ? 0.22 : 0.0).cgColor   // dim stock photos only
        box.addSublayer(dim)
        // highlighter marks: each patch sweeps in left-to-right at its start time, with a small pop
        for m in b.marks {
            guard let pp = m["patch"] as? String, let mi = NSImage(contentsOfFile: pp)?.cgImage(forProposedRect: nil, context: nil, hints: nil),
                  let x = m["x"] as? Double, let y = m["y"] as? Double, let w = m["w"] as? Double, let h = m["h"] as? Double,
                  let st = m["start"] as? Double else { continue }
            let boxH = Double(box.bounds.height)
            let pl = CALayer(); pl.frame = CGRect(x: x, y: boxH - y - h, width: w, height: h); pl.contents = mi
            let mask = CALayer(); mask.backgroundColor = NSColor.black.cgColor
            mask.anchorPoint = CGPoint(x: 0, y: 0.5); mask.bounds = CGRect(x: 0, y: 0, width: w, height: h); mask.position = CGPoint(x: 0, y: h / 2)
            pl.mask = mask
            let dur = min(0.6, max(0.25, w / 1400))
            let sweep = CABasicAnimation(keyPath: "bounds.size.width"); sweep.fromValue = 0; sweep.toValue = w
            sweep.beginTime = AVCoreAnimationBeginTimeAtZero + st; sweep.duration = dur
            sweep.timingFunction = CAMediaTimingFunction(name: .easeOut); sweep.fillMode = .both; sweep.isRemovedOnCompletion = false
            mask.add(sweep, forKey: "sweep")
            let pop = CAKeyframeAnimation(keyPath: "transform.scale"); pop.values = [1.0, 1.07, 1.0]; pop.keyTimes = [0, 0.5, 1]
            pop.beginTime = AVCoreAnimationBeginTimeAtZero + st + dur * 0.6; pop.duration = 0.35
            pop.fillMode = .both; pop.isRemovedOnCompletion = false
            pl.add(pop, forKey: "pop")
            pic.addSublayer(pl)
        }
    } else if b.image != nil { FileHandle.standardError.write("broll load failed: \(b.image!)\n".data(using: .utf8)!) }
    if let lab = b.label {
        let (img, sz) = pillImage(lab.uppercased(), fsize: 22, textColor: .white, bg: NSColor(calibratedWhite: 0, alpha: 0.55),
                                  padX: 14, padY: 7, corner: 8, maxTextW: CGFloat(W) * 0.6, kern: 1.5)
        let l = CALayer(); l.frame = CGRect(x: 22, y: 34, width: sz.width, height: sz.height); l.contents = img
        box.addSublayer(l)
    }
    addFadeWindow(box, showStart: b.start, showEnd: b.end, total: total, fade: 0.12)
    return box
}
let BUBBLE_D: CGFloat = CGFloat(W) * 0.36
let BUBBLE_BOTTOM: CGFloat = CGFloat(H) * 0.15 + BTB_LINE * 2 + 34     // clear of a 2-line caption block
// Adam in a circle: a second video layer (same composited frame), scaled + offset so his face
// sits in the circle, masked round, white ring. Returns (wrapper, videoLayer).
func makeBubble(_ b: Broll, face: FaceInfo, total: Double) -> (CALayer, CALayer) {
    let D = BUBBLE_D
    let cxPos: CGFloat = b.bubble.hasSuffix("l") ? 26 + D/2 : CGFloat(W) - 26 - D/2
    let cyPos: CGFloat = b.bubble.hasPrefix("t") ? CGFloat(H) * 0.62 : BUBBLE_BOTTOM + D/2
    let wrap = CALayer(); wrap.frame = CGRect(x: cxPos - D/2, y: cyPos - D/2, width: D, height: D)
    wrap.shadowColor = NSColor.black.cgColor; wrap.shadowOpacity = 0.5; wrap.shadowRadius = 16; wrap.shadowOffset = CGSize(width: 0, height: -5)
    let clip = CALayer(); clip.frame = wrap.bounds; clip.cornerRadius = D/2; clip.masksToBounds = true
    clip.backgroundColor = NSColor.black.cgColor
    let s = (D * 0.58) / max(0.05, face.faceW * CGFloat(W))          // face fills ~58% of the circle
    let vw = CGFloat(W) * s, vh = CGFloat(H) * s
    let fx = face.cx * vw, fyUp = (1 - face.cy) * vh                // face centre in video-layer coords (y up)
    let vid = CALayer(); vid.frame = CGRect(x: D/2 - fx, y: D * 0.55 - fyUp, width: vw, height: vh)
    clip.addSublayer(vid)
    let ring = CALayer(); ring.frame = wrap.bounds; ring.cornerRadius = D/2; ring.borderWidth = 8; ring.borderColor = cream.cgColor
    wrap.addSublayer(clip); wrap.addSublayer(ring)
    addFadeWindow(wrap, showStart: b.start, showEnd: b.end, total: total, fade: 0.12)
    return (wrap, vid)
}
func bigText(_ t: String, size: CGFloat, color: NSColor) -> (CGImage, CGSize) {
    let a = NSAttributedString(string: t, attributes: btbAttrsSized(color, size))
    let sz = a.size(); let w = ceil(sz.width) + 30, h = ceil(sz.height) + 30
    let img = btbDraw(CGSize(width: Int(w), height: Int(h))) { _ in a.draw(at: NSPoint(x: 8, y: 18)) }
    return (img, CGSize(width: w, height: h))
}
func btbAttrsSized(_ col: NSColor, _ size: CGFloat) -> [NSAttributedString.Key: Any] {
    let sh = NSShadow(); sh.shadowColor = NSColor.black.withAlphaComponent(0.95)
    sh.shadowOffset = NSSize(width: size*0.05, height: -size*0.07); sh.shadowBlurRadius = 0
    return [.font: btbFont(size), .foregroundColor: col, .kern: 1.0, .shadow: sh]
}
func centered(_ img: CGImage, _ sz: CGSize, y: CGFloat) -> CALayer {
    let l = CALayer(); l.frame = CGRect(x: (CGFloat(W) - sz.width)/2, y: y - sz.height/2, width: sz.width, height: sz.height)
    l.contents = img; l.contentsGravity = .resize; return l
}
func addPop(_ l: CALayer, at t: Double, from: CGFloat = 1.7) {
    let a = CABasicAnimation(keyPath: "transform.scale"); a.fromValue = from; a.toValue = 1.0
    a.beginTime = AVCoreAnimationBeginTimeAtZero + max(0.001, t); a.duration = 0.16
    a.timingFunction = CAMediaTimingFunction(name: .easeOut); a.fillMode = .both; a.isRemovedOnCompletion = false
    l.add(a, forKey: "pop")
}
// ---------- text cards: seam captions, name labels, place cards, emoji ----------
func textCard(_ a: NSAttributedString, bg: NSColor, padX: CGFloat, padY: CGFloat, corner: CGFloat,
              maxW: CGFloat, bar: NSColor? = nil) -> CALayer {
    let br = a.boundingRect(with: CGSize(width: maxW, height: .greatestFiniteMagnitude), options: [.usesLineFragmentOrigin])
    let barW: CGFloat = bar == nil ? 0 : 12
    let w = ceil(br.width) + padX * 2 + barW, h = ceil(br.height) + padY * 2
    let img = btbDraw(CGSize(width: Int(w), height: Int(h))) { g in
        g.setFillColor(bg.cgColor)
        g.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: w, height: h), cornerWidth: corner, cornerHeight: corner, transform: nil)); g.fillPath()
        if let bar = bar { g.setFillColor(bar.cgColor); g.fill(CGRect(x: 0, y: 0, width: barW, height: h)) }
        a.draw(with: CGRect(x: padX + barW, y: padY, width: ceil(br.width) + 2, height: ceil(br.height)), options: [.usesLineFragmentOrigin])
    }
    let l = CALayer(); l.bounds = CGRect(x: 0, y: 0, width: w, height: h); l.anchorPoint = .zero
    l.contents = img; l.contentsGravity = .resize; return l
}
func capBox(_ text: String) -> CALayer {
    let para = NSMutableParagraphStyle(); para.alignment = .center; para.lineSpacing = 2
    if CAP_STYLE == "mono" {
        let f = NSFont(name: "Menlo-Bold", size: 58) ?? NSFont.monospacedSystemFont(ofSize: 58, weight: .bold)
        let a = NSAttributedString(string: text.uppercased(), attributes: [.font: f, .foregroundColor: NSColor.white, .kern: 3.0, .paragraphStyle: para])
        return textCard(a, bg: NSColor(calibratedWhite: 0.04, alpha: 0.92), padX: 30, padY: 16, corner: 14, maxW: CGFloat(W) * 0.8)
    }
    let f = NSFont(name: "HelveticaNeue-Medium", size: 62) ?? font(62, false)
    let a = NSAttributedString(string: text, attributes: [.font: f, .foregroundColor: NSColor(calibratedWhite: 0.07, alpha: 1), .paragraphStyle: para])
    return textCard(a, bg: NSColor(calibratedWhite: 0.97, alpha: 0.96), padX: 30, padY: 16, corner: 26, maxW: CGFloat(W) * 0.8)
}
// the free zone for graphics: wherever captions are NOT (captions high -> graphics low, and vice versa)
func freeZoneCenterY(_ h: CGFloat) -> CGFloat {
    BTB_BOTTOM > BTB_LOW + 1 ? CGFloat(H) * 0.13 + h / 2 : CGFloat(H) - BAND_BOTTOM - 36 - h / 2
}
func slideIn(_ l: CALayer, at t: Double, dx: CGFloat) {
    let a = CABasicAnimation(keyPath: "position.x"); a.fromValue = l.position.x + dx; a.toValue = l.position.x
    a.beginTime = AVCoreAnimationBeginTimeAtZero + max(0.001, t); a.duration = 0.3
    a.timingFunction = CAMediaTimingFunction(name: .easeOut); a.fillMode = .both; a.isRemovedOnCompletion = false
    l.add(a, forKey: "slide")
}
func makeGraphics(_ g: [String:Any], total: Double, contentDur: Double) -> [CALayer] {
    let type = g["type"] as? String ?? "", st = g["start"] as! Double, en = min(g["end"] as! Double, contentDur)
    var out: [CALayer] = []
    let midY = CGFloat(H) * 0.60
    switch type {
    case "counter":
        let n0 = g["n0"] as? Int ?? 1, n1 = g["n1"] as? Int ?? 100, pre = g["prefix"] as? String ?? ""
        let ce = min(g["count_end"] as? Double ?? (st + (en - st) * 0.7), en)
        if let lab = g["label"] as? String {
            let (img, sz) = bigText(lab.uppercased(), size: 58, color: btbMint)
            let l = centered(img, sz, y: midY + 190); addWindow(l, showStart: st, showEnd: en, total: total); out.append(l)
        }
        let steps = 36; var last = -1; var marks: [(Double, Int)] = []
        for i in 0...steps {
            let u = Double(i) / Double(steps), eased = 1 - pow(1 - u, 2.2)
            let v = n0 + Int((Double(n1 - n0) * eased).rounded())
            if v != last { marks.append((st + (ce - st) * u, v)); last = v }
        }
        for (k, (t, v)) in marks.enumerated() {
            let isLast = k == marks.count - 1
            let (img, sz) = bigText("\(pre)\(v)", size: isLast ? 230 : 200, color: isLast ? brandRed : .white)
            let l = centered(img, sz, y: midY)
            addWindow(l, showStart: t, showEnd: isLast ? en : marks[k+1].0, total: total)
            if isLast { addPop(l, at: t, from: 1.6) }
            out.append(l)
        }
    case "slam":
        let items = (g["items"] as? [[String:Any]]) ?? []
        let gap: CGFloat = 200, top = midY + gap * CGFloat(items.count - 1) / 2
        for (i, it) in items.enumerated() {
            let (img, sz) = bigText((it["text"] as? String ?? "").uppercased(), size: 140, color: i == items.count - 1 ? btbMint : .white)
            let l = centered(img, sz, y: top - gap * CGFloat(i))
            let t = it["start"] as? Double ?? st
            addWindow(l, showStart: t, showEnd: en, total: total); addPop(l, at: t); out.append(l)
        }
    case "label":   // lower-third name tag: NAME / role, red bar, slides in from the left
        let a = NSMutableAttributedString(string: (g["name"] as? String ?? "").uppercased(),
            attributes: [.font: btbFont(54), .foregroundColor: NSColor.white, .kern: 1.5])
        if let role = g["role"] as? String, !role.isEmpty {
            a.append(NSAttributedString(string: "\n" + role, attributes: [.font: NSFont(name: "AvenirNext-DemiBold", size: 34) ?? font(34, true), .foregroundColor: btbMint]))
        }
        let l = textCard(a, bg: NSColor(calibratedWhite: 0.04, alpha: 0.9), padX: 26, padY: 14, corner: 10, maxW: CGFloat(W) * 0.7, bar: brandRed)
        l.frame.origin = CGPoint(x: 40, y: freeZoneCenterY(l.bounds.height) - l.bounds.height / 2)
        addFadeWindow(l, showStart: st, showEnd: en, total: total, fade: 0.2); slideIn(l, at: st, dx: -420); out.append(l)
    case "place":   // place / date card: pin + PLACE, year in mint
        let a = NSMutableAttributedString(string: "📍 " + (g["place"] as? String ?? "").uppercased(),
            attributes: [.font: btbFont(78), .foregroundColor: NSColor.white, .kern: 2.0])
        if let yr = g["year"] as? String, !yr.isEmpty {
            a.append(NSAttributedString(string: "  " + yr, attributes: [.font: btbFont(78), .foregroundColor: btbMint]))
        }
        let l = textCard(a, bg: NSColor(calibratedWhite: 0.04, alpha: 0.82), padX: 30, padY: 12, corner: 18, maxW: CGFloat(W) * 0.9)
        l.frame.origin = CGPoint(x: (CGFloat(W) - l.bounds.width) / 2, y: freeZoneCenterY(l.bounds.height) - l.bounds.height / 2)
        addFadeWindow(l, showStart: st, showEnd: en, total: total, fade: 0.15); addPop(l, at: st, from: 1.4); out.append(l)
    case "emoji":   // big emoji pop beside the head, never on it
        let e = g["emoji"] as? String ?? "✨", sz: CGFloat = 190
        let a = NSAttributedString(string: e, attributes: [.font: NSFont(name: "AppleColorEmoji", size: sz) ?? NSFont.systemFont(ofSize: sz)])
        let bs = a.size(); let w = ceil(bs.width) + 20, h = ceil(bs.height) + 20
        let img = btbDraw(CGSize(width: Int(w), height: Int(h))) { _ in a.draw(at: NSPoint(x: 10, y: 10)) }
        let faceX = FACE.cx * CGFloat(W), half = FACE.faceW * CGFloat(W) * 0.75 + w / 2 + 20
        let right = faceX + half + w / 2 < CGFloat(W) - 10
        let cx = right ? min(CGFloat(W) - w / 2 - 20, faceX + half) : max(w / 2 + 20, faceX - half)
        let cy = CGFloat(H) - (FACE.headTop + (FACE.chin - FACE.headTop) * 0.35) * CGFloat(H)
        let l = CALayer(); l.frame = CGRect(x: cx - w / 2, y: cy - h / 2, width: w, height: h); l.contents = img
        addFadeWindow(l, showStart: st, showEnd: en, total: total, fade: 0.12); addPop(l, at: st, from: 0.2)
        let wob = CAKeyframeAnimation(keyPath: "transform.rotation.z"); wob.values = [0, 0.18, -0.12, 0.06, 0]
        wob.beginTime = AVCoreAnimationBeginTimeAtZero + st + 0.16; wob.duration = 0.6; wob.fillMode = .both; wob.isRemovedOnCompletion = false
        l.add(wob, forKey: "wob"); out.append(l)
    case "curtain":
        // two heavy maroon drapes slide in from the sides and meet in the middle
        let wrap = CALayer(); wrap.frame = CGRect(x: 0, y: 0, width: W, height: H); wrap.masksToBounds = true
        for side in [0, 1] {
            let d = CAGradientLayer(); d.frame = CGRect(x: 0, y: 0, width: CGFloat(W)/2 + 12, height: CGFloat(H))
            let dark = NSColor(calibratedRed: 0.30, green: 0.03, blue: 0.05, alpha: 1).cgColor
            let lite = NSColor(calibratedRed: 0.52, green: 0.07, blue: 0.10, alpha: 1).cgColor
            d.colors = (0..<14).map { $0 % 2 == 0 ? dark : lite }
            d.startPoint = CGPoint(x: 0, y: 0.5); d.endPoint = CGPoint(x: 1, y: 0.5)
            let closedX = side == 0 ? CGFloat(W)/4 + 6 : CGFloat(W)*3/4 - 6
            let openX = side == 0 ? -CGFloat(W)/4 - 20 : CGFloat(W)*5/4 + 20
            d.position = CGPoint(x: closedX, y: CGFloat(H)/2)
            let a = CABasicAnimation(keyPath: "position.x"); a.fromValue = openX; a.toValue = closedX
            a.beginTime = AVCoreAnimationBeginTimeAtZero + st; a.duration = 0.9
            a.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut); a.fillMode = .both; a.isRemovedOnCompletion = false
            d.add(a, forKey: "close"); wrap.addSublayer(d)
        }
        addWindow(wrap, showStart: st, showEnd: en, total: total); out.append(wrap)
    default:
        FileHandle.standardError.write("unknown graphic type \(type)\n".data(using: .utf8)!)
    }
    return out
}

// ---------- compose ----------
func compose() {
    let sem = DispatchSemaphore(value: 0)
    Task {
        let content = AVURLAsset(url: URL(fileURLWithPath: SRC))
        let comp = AVMutableComposition()
        let vTrack = comp.addMutableTrack(withMediaType:.video, preferredTrackID: kCMPersistentTrackID_Invalid)!
        let aTrack = comp.addMutableTrack(withMediaType:.audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
        let cVid = try! await content.loadTracks(withMediaType:.video).first!
        let cAud = try? await content.loadTracks(withMediaType:.audio).first
        let cTransform = try! await cVid.load(.preferredTransform)

        // insert each kept range sequentially
        var cursor = CMTime.zero
        for (s,e) in CUTS {
            let r = CMTimeRange(start: CMTime(seconds: s, preferredTimescale: TS),
                                duration: CMTime(seconds: e - s, preferredTimescale: TS))
            try! vTrack.insertTimeRange(r, of: cVid, at: cursor)
            if let a = cAud ?? nil { try? aTrack.insertTimeRange(r, of: a, at: cursor) }
            cursor = cursor + r.duration
        }
        let contentDur = vTrack.timeRange.duration

        // end card
        var total = contentDur
        if HAS_ENDCARD {
            renderEndCard()
            let card = AVURLAsset(url: URL(fileURLWithPath: ENDCARD))
            let eVid = try! await card.loadTracks(withMediaType:.video).first!
            let cardDur = try! await card.load(.duration)
            try! vTrack.insertTimeRange(CMTimeRange(start: .zero, duration: cardDur), of: eVid, at: contentDur)
            total = comp.duration
        }

        let vc = AVMutableVideoComposition()
        vc.renderSize = CGSize(width: W, height: H)
        vc.frameDuration = CMTime(value: 1, timescale: FPS)
        let inst = AVMutableVideoCompositionInstruction()
        inst.timeRange = CMTimeRange(start: .zero, duration: total)
        let li = AVMutableVideoCompositionLayerInstruction(assetTrack: vTrack)
        var vt = cTransform
        if ZOOM > 1.001 {
            let px = CGFloat(W) * FOCUS.0, py = CGFloat(H) * FOCUS.1
            vt = vt.concatenating(CGAffineTransform(translationX: -px, y: -py))
                   .concatenating(CGAffineTransform(scaleX: ZOOM, y: ZOOM))
                   .concatenating(CGAffineTransform(translationX: px, y: py))
        }
        li.setTransform(vt, at: .zero)
        // jump-zoom punches: extra zoom about the punch focus, on top of the base framing
        for p in PUNCHES.sorted(by: { $0.start < $1.start }) {
            let px = CGFloat(W) * p.focus.0, py = CGFloat(H) * p.focus.1
            let pt = vt.concatenating(CGAffineTransform(translationX: -px, y: -py))
                       .concatenating(CGAffineTransform(scaleX: p.zoom, y: p.zoom))
                       .concatenating(CGAffineTransform(translationX: px, y: py))
            li.setTransform(pt, at: CMTime(seconds: p.start, preferredTimescale: TS))
            if p.end < contentDur.seconds - 0.01 { li.setTransform(vt, at: CMTime(seconds: p.end, preferredTimescale: TS)) }
        }
        // split screen: slide the video down so Adam's head sits just under the seam, B-roll fills the top half
        FACE = STYLE == "btb" || !BROLLS.isEmpty ? analyzeFace() : FACE
        let splitShift = max(0, min(CGFloat(H) * 0.45, CGFloat(H) / 2 + 110 - FACE.headTop * CGFloat(H)))   // head lands just under the seam caption
        for b in BROLLS.sorted(by: { $0.start < $1.start }) where b.layout == "split" {
            let down = vt.concatenating(CGAffineTransform(translationX: 0, y: splitShift))
            let ramp = 0.25, s0 = max(0, b.start - ramp / 2)
            li.setTransformRamp(fromStart: vt, toEnd: down, timeRange: CMTimeRange(start: CMTime(seconds: s0, preferredTimescale: TS), duration: CMTime(seconds: ramp, preferredTimescale: TS)))
            let e0 = min(contentDur.seconds - ramp, b.end - ramp / 2)
            li.setTransform(down, at: CMTime(seconds: s0 + ramp, preferredTimescale: TS))
            li.setTransformRamp(fromStart: down, toEnd: vt, timeRange: CMTimeRange(start: CMTime(seconds: e0, preferredTimescale: TS), duration: CMTime(seconds: ramp, preferredTimescale: TS)))
            li.setTransform(vt, at: CMTime(seconds: e0 + ramp, preferredTimescale: TS))
        }
        if HAS_ENDCARD { li.setTransform(.identity, at: contentDur) }
        // stock video B-roll: a second track filling the top half, shown only inside its window
        var layerInsts: [AVMutableVideoCompositionLayerInstruction] = [li]
        let vbs = BROLLS.filter { $0.video != nil }
        if !vbs.isEmpty, let bTrack = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid) {
            let lb = AVMutableVideoCompositionLayerInstruction(assetTrack: bTrack)
            lb.setOpacity(0, at: .zero)
            for b in vbs {
                let a = AVURLAsset(url: URL(fileURLWithPath: b.video!))
                guard let t = try? await a.loadTracks(withMediaType: .video).first,
                      let nat = try? await t.load(.naturalSize), let pt = try? await t.load(.preferredTransform),
                      let dur = try? await a.load(.duration) else {
                    FileHandle.standardError.write("stock video load failed: \(b.video!)\n".data(using: .utf8)!); continue }
                let len = min(b.end - b.start, dur.seconds)
                let at = CMTime(seconds: b.start, preferredTimescale: TS)
                try? bTrack.insertTimeRange(CMTimeRange(start: .zero, duration: CMTime(seconds: len, preferredTimescale: TS)), of: t, at: at)
                let sz = nat.applying(pt); let sw = abs(sz.width), sh = abs(sz.height)
                let k = max(CGFloat(W) / sw, CGFloat(H) / 2 / sh)
                let tf = pt.concatenating(CGAffineTransform(scaleX: k, y: k))
                           .concatenating(CGAffineTransform(translationX: (CGFloat(W) - sw * k) / 2, y: (CGFloat(H) / 2 - sh * k) / 2))
                lb.setTransform(tf, at: at)
                // crop the source to exactly what lands in the top half, so a tall clip never spills onto Adam
                let tx = (CGFloat(W) - sw * k) / 2, ty = (CGFloat(H) / 2 - sh * k) / 2
                lb.setCropRectangle(CGRect(x: -tx / k, y: -ty / k, width: CGFloat(W) / k, height: CGFloat(H) / 2 / k), at: at)
                lb.setOpacity(1, at: at)
                lb.setOpacity(0, at: CMTime(seconds: b.start + len, preferredTimescale: TS))
            }
            layerInsts.insert(lb, at: 0)
        }
        inst.layerInstructions = layerInsts; vc.instructions = [inst]

        // overlay layer tree
        let parent = CALayer(); parent.frame = CGRect(x:0,y:0,width:W,height:H)
        let videoLayer = CALayer(); videoLayer.frame = parent.frame; parent.addSublayer(videoLayer)

        let totalS = total.seconds, contentS = contentDur.seconds
        let face = FACE
        let band: TopBand? = STYLE == "btb" ? buildTopBand(face: face) : nil
        if let band = band { BAND_BOTTOM = band.bottomFromTop; placeCaptions(face: face, bandBottom: band.bottomFromTop) }
        var videoLayers = [videoLayer]
        // B-roll cutaways, Adam's bubble over them, then animated graphics
        for b in BROLLS where b.video == nil { parent.addSublayer(makeBroll(b, total: totalS)) }
        for b in BROLLS where b.bubble != "none" && b.layout != "split" {
            let (wrap, vid) = makeBubble(b, face: face, total: totalS)
            parent.addSublayer(wrap); videoLayers.append(vid)
        }
        for g in GRAPHICS { for l in makeGraphics(g, total: totalS, contentDur: contentS) { parent.addSublayer(l) } }

        // photo insets (under captions/sticker/watermark)
        for ins in INSETS {
            if let card = makeInset(ins.path) {
                addFadeWindow(card, showStart: ins.start, showEnd: min(ins.end, contentS), total: totalS)
                parent.addSublayer(card)
            }
        }
        // captions (content timeline); during B-roll cutaways they sit low so they don't cover the image
        let overBroll = { (c: Cue) in BROLLS.contains { $0.layout != "split" && c.start < $0.end && c.end > $0.start } }
        let overSplit = { (c: Cue) in BROLLS.contains { $0.layout == "split" && c.start < $0.end && c.end > $0.start } }
        let capBottom = { (c: Cue, h: CGFloat) -> CGFloat in
            overSplit(c) ? CGFloat(H) / 2 - h / 2 : (overBroll(c) ? BTB_LOW : BTB_BOTTOM) }
        let capsOff = { (c: Cue) in NOCAPS.contains { c.start < $0.1 && c.end > $0.0 } }
        for c in CUES where STYLE == "btb" && (CAP_STYLE != "btb" || overSplit(c)) && !capsOff(c) {
            let l = capBox(c.text)
            let top = BTB_BOTTOM + BTB_LINE * 2            // keep the box inside the face-clear zone
            var y = overSplit(c) ? CGFloat(H) / 2 - l.bounds.height / 2 : (overBroll(c) ? BTB_LOW : top - l.bounds.height)
            if !overSplit(c) && !overBroll(c) && BTB_BOTTOM <= BTB_LOW + 1 { y = BTB_BOTTOM }   // low zone: sit on the bottom edge
            l.frame.origin = CGPoint(x: (CGFloat(W) - l.bounds.width) / 2, y: y)
            addWindow(l, showStart: c.start, showEnd: min(c.end, contentS), total: totalS); parent.addSublayer(l)
        }
        for c in CUES where STYLE == "btb" && CAP_STYLE == "btb" && !overSplit(c) && !capsOff(c) {
            let ws = c.words.isEmpty ? [CueWord(start: c.start, end: c.end, text: c.text)] : c.words
            let texts = ws.map { btbWord($0.text) }
            let nLines = Set(btbLayout(texts, bottom: 0).map { $0.minY }).count
            let rects = btbLayout(texts, bottom: capBottom(c, CGFloat(nLines) * BTB_LINE))
            let base = btbBase(texts, rects)
            addWindow(base, showStart: c.start, showEnd: min(c.end, contentS), total: totalS)
            parent.addSublayer(base)
            for (i, w) in ws.enumerated() {
                let act = btbActive(texts[i], rects[i])
                addWindow(act, showStart: w.start, showEnd: min(w.end, c.end, contentS), total: totalS)
                parent.addSublayer(act)
            }
        }
        for c in CUES where STYLE != "btb" {
            let cap = makeCaption(c.text)
            addWindow(cap, showStart: c.start, showEnd: min(c.end, contentS), total: totalS)
            parent.addSublayer(cap)
        }
        // btb: head-aware top band (logo + title card + tag); hidden during punches that push the head into it
        if let band = band {
            let lim = band.bottomFromTop / CGFloat(H) + 0.01
            let hide = PUNCHES.filter { punchedHeadTop(face, $0) < lim }.map { ($0.start, $0.end) }
            for l in band.layers { addHideWindows(l, hide: hide, contentDur: contentS, total: totalS); parent.addSublayer(l) }
            addVisibleUntil(band.logo, contentDur: contentS, total: totalS); parent.addSublayer(band.logo)
        }
        // sticker (whole content)
        if STYLE != "btb", let st = STICKER {
            let s = STYLE == "btb" ? btbInfoBox(st) : makeSticker(st)
            addStickerVisibility(s, contentDur: contentS, total: totalS, insets: INSETS)
            parent.addSublayer(s)
            if STYLE == "btb", let t = TAG {
                let tg = btbTag(t, below: s.frame)
                addVisibleUntil(tg, contentDur: contentS, total: totalS)
                parent.addSublayer(tg)
            }
        }
        // watermark bottom-left (whole content; btb's logo lives in the top band)
        let wm = CALayer()
        if STYLE != "btb" {
        if STYLE == "btb" {
            let lw = CGFloat(W)*0.31
            wm.frame = CGRect(x: 18, y: CGFloat(H)*0.905 - lw/logoAR - 10, width: lw, height: lw/logoAR)
        } else {
            let wmW = CGFloat(W)*0.16
            wm.frame = CGRect(x: 40, y: 52, width: wmW, height: wmW/logoAR)
        }
        wm.contents = logoCG; wm.contentsGravity = .resizeAspect; wm.opacity = 0.9
        wm.shadowColor = NSColor.white.cgColor; wm.shadowOpacity = 0.7; wm.shadowRadius = 8; wm.shadowOffset = .zero
        addVisibleUntil(wm, contentDur: contentS, total: totalS)
        parent.addSublayer(wm)
        }

        vc.animationTool = AVVideoCompositionCoreAnimationTool(postProcessingAsVideoLayers: videoLayers, in: parent)

        try? FileManager.default.removeItem(atPath: OUT)
        let ex = AVAssetExportSession(asset: comp, presetName: AVAssetExportPresetHighestQuality)!
        ex.outputURL = URL(fileURLWithPath: OUT); ex.outputFileType = .mp4; ex.videoComposition = vc
        await ex.export()
        try? FileManager.default.removeItem(atPath: ENDCARD)
        if ex.status == .completed {
            print("OK  \(OUT)  segments=\(CUTS.count)  content=\(String(format:"%.2f",contentS))s  total=\(String(format:"%.2f",totalS))s")
        } else { die("export: \(String(describing: ex.error))") }
        sem.signal()
    }
    sem.wait()
}

compose()
