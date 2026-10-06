// grabframes.swift — dump JPEG frames from a video at given seconds (native AVFoundation, no ffmpeg).
// Usage: swift grabframes.swift INPUT.mov OUTDIR 5 60 120 200 300 380
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count >= 4 else { FileHandle.standardError.write("usage: grabframes.swift IN OUTDIR sec [sec...]\n".data(using:.utf8)!); exit(2) }
let inURL = URL(fileURLWithPath: args[1])
let outDir = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let secs = args[3...].compactMap { Double($0) }

let asset = AVURLAsset(url: inURL)
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true          // respect rotation metadata
gen.requestedTimeToleranceBefore = .zero
gen.requestedTimeToleranceAfter = .zero
gen.maximumSize = CGSize(width: 540, height: 960)   // half-res is plenty to judge layout

for s in secs {
    let t = CMTime(seconds: s, preferredTimescale: 600)
    do {
        let cg = try gen.copyCGImage(at: t, actualTime: nil)
        let rep = NSBitmapImageRep(cgImage: cg)
        guard let data = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.7]) else { continue }
        let name = String(format: "frame_%04d.jpg", Int(s))
        try data.write(to: outDir.appendingPathComponent(name))
        print("wrote \(name)  (\(cg.width)x\(cg.height))")
    } catch { FileHandle.standardError.write("frame @\(s)s failed: \(error)\n".data(using:.utf8)!) }
}
