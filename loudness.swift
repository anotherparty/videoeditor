// loudness.swift FILE [FILE...] -> peak and RMS level (dBFS) of each file's audio. Used to check and fix quiet reels.
import AVFoundation
func db(_ x: Float) -> Float { 20 * log10(max(x, 1e-9)) }
for p in CommandLine.arguments.dropFirst() {
    let asset = AVURLAsset(url: URL(fileURLWithPath: p))
    let sem = DispatchSemaphore(value: 0)
    Task {
        guard let t = try? await asset.loadTracks(withMediaType: .audio).first else { print("\(p): no audio"); sem.signal(); return }
        let r = try! AVAssetReader(asset: asset)
        let o = AVAssetReaderTrackOutput(track: t, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false, AVLinearPCMIsBigEndianKey: false])
        r.add(o); r.startReading()
        var peak: Float = 0, sum: Double = 0, n = 0
        while let sb = o.copyNextSampleBuffer(), let bb = CMSampleBufferGetDataBuffer(sb) {
            var len = 0; var ptr: UnsafeMutablePointer<Int8>?
            CMBlockBufferGetDataPointer(bb, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &len, dataPointerOut: &ptr)
            ptr!.withMemoryRebound(to: Float.self, capacity: len / 4) { f in
                for i in 0..<(len / 4) { let v = abs(f[i]); peak = max(peak, v); sum += Double(v * v) }
            }
            n += len / 4
        }
        let rms = Float((sum / Double(max(1, n))).squareRoot())
        print(String(format: "%@: peak %.1f dBFS, rms %.1f dBFS", (p as NSString).lastPathComponent, db(peak), db(rms)))
        sem.signal()
    }
    sem.wait()
}
