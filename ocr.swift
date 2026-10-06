// ocr.swift IMG [IMG...] -> JSON {path: {"size":[w,h], "lines":[{"text","y0","y1"}]}} (y from top, 0-1), top to bottom. Used by autoplan.py.
import AppKit
import Vision
var out: [String: Any] = [:]
for p in CommandLine.arguments.dropFirst() {
    guard let cg = NSImage(contentsOfFile: p)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest(); req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    let lines: [[String: Any]] = (req.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }.compactMap { o in
        guard let t = o.topCandidates(1).first?.string else { return nil }
        return ["text": t, "y0": 1 - o.boundingBox.maxY, "y1": 1 - o.boundingBox.minY] }
    out[p] = ["size": [cg.width, cg.height], "lines": lines]
}
print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted]), encoding: .utf8)!)
