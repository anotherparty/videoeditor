// normalize.swift IN.mp4 OUT.mp4 [--target -16] [--ceiling -1]
// Makes speech reel-loud: measures the voice level (ignoring silence), applies the gain needed to reach --target
// dBFS RMS, and runs a look-ahead peak limiter so nothing goes past --ceiling dBFS. Video is copied untouched.
// Phone recordings usually sit around -25 dBFS, far too quiet for Instagram (~-16).
import AVFoundation

let A = CommandLine.arguments
func arg(_ k: String) -> String? { if let i = A.firstIndex(of: k), i + 1 < A.count { return A[i + 1] }; return nil }
guard A.count >= 3 else { FileHandle.standardError.write("usage: normalize.swift IN OUT [--target -16] [--ceiling -1]\n".data(using: .utf8)!); exit(2) }
let IN = URL(fileURLWithPath: A[1]), OUT = URL(fileURLWithPath: A[2])
let TARGET = Float(arg("--target") ?? "-16")!, CEIL = powf(10, Float(arg("--ceiling") ?? "-1")! / 20)
let SR = 48000.0, CH = 2
func db(_ x: Float) -> Float { 20 * log10(max(x, 1e-9)) }

let sem = DispatchSemaphore(value: 0)
Task {
    let asset = AVURLAsset(url: IN)
    guard let at = try? await asset.loadTracks(withMediaType: .audio).first,
          let vt = try? await asset.loadTracks(withMediaType: .video).first else { print("no audio/video"); exit(1) }
    // 1. decode audio to interleaved float
    let pcm: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: SR, AVNumberOfChannelsKey: CH,
                              AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false, AVLinearPCMIsBigEndianKey: false]
    let r = try! AVAssetReader(asset: asset); let ro = AVAssetReaderTrackOutput(track: at, outputSettings: pcm)
    r.add(ro); r.startReading()
    var x: [Float] = []
    while let sb = ro.copyNextSampleBuffer(), let bb = CMSampleBufferGetDataBuffer(sb) {
        var len = 0; var p: UnsafeMutablePointer<Int8>?
        CMBlockBufferGetDataPointer(bb, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &len, dataPointerOut: &p)
        p!.withMemoryRebound(to: Float.self, capacity: len / 4) { x.append(contentsOf: UnsafeBufferPointer(start: $0, count: len / 4)) }
    }
    let frames = x.count / CH
    // 2. speech level: RMS over 50ms blocks louder than -45 dBFS (skips the silences)
    let blk = Int(SR * 0.05) * CH; var ss = 0.0, nn = 0
    var i = 0
    while i < x.count { let e = min(x.count, i + blk); var s = 0.0
        for k in i..<e { s += Double(x[k] * x[k]) }
        if db(Float((s / Double(e - i)).squareRoot())) > -45 { ss += s; nn += e - i }
        i = e }
    let speech = db(Float((ss / Double(max(1, nn))).squareRoot()))
    let gain = powf(10, min(24, max(0, TARGET - speech)) / 20)
    // 3. look-ahead limiter: per-frame gain = min(gain, ceiling/peak), min over a 5ms look-ahead, 120ms release
    var g = [Float](repeating: gain, count: frames)
    for f in 0..<frames { var pk: Float = 0; for c in 0..<CH { pk = max(pk, abs(x[f * CH + c])) }
        if pk * gain > CEIL { g[f] = CEIL / pk } }
    let look = Int(SR * 0.005)
    var m = [Float](repeating: gain, count: frames)
    var dq: [Int] = []; var head = 0                          // sliding-window minimum
    for f in 0..<(frames + look) {
        if f < frames { while dq.count > head && g[dq.last!] >= g[f] { dq.removeLast() }; dq.append(f) }
        let o = f - look
        if o >= 0 { while dq[head] < o { head += 1 }; m[o] = g[dq[head]] }
    }
    let rel = expf(-1 / Float(SR * 0.12)); var cur = gain
    for f in 0..<frames {
        cur = m[f] < cur ? m[f] : m[f] + (cur - m[f]) * rel
        cur = min(cur, m[f])
        for c in 0..<CH { x[f * CH + c] = max(-CEIL, min(CEIL, x[f * CH + c] * cur)) }
    }
    // 4. write: video passthrough + re-encoded AAC audio
    try? FileManager.default.removeItem(at: OUT)
    let w = try! AVAssetWriter(outputURL: OUT, fileType: .mp4)
    let vin = AVAssetWriterInput(mediaType: .video, outputSettings: nil, sourceFormatHint: (try? await vt.load(.formatDescriptions))?.first)
    vin.transform = (try? await vt.load(.preferredTransform)) ?? .identity
    let ain = AVAssetWriterInput(mediaType: .audio, outputSettings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: SR,
                                                                     AVNumberOfChannelsKey: CH, AVEncoderBitRateKey: 192_000])
    vin.expectsMediaDataInRealTime = false; ain.expectsMediaDataInRealTime = false
    w.add(vin); w.add(ain); w.startWriting(); w.startSession(atSourceTime: .zero)
    let vr = try! AVAssetReader(asset: asset); let vo = AVAssetReaderTrackOutput(track: vt, outputSettings: nil)
    vr.add(vo); vr.startReading()
    var fmt: CMAudioFormatDescription?
    var asbd = AudioStreamBasicDescription(mSampleRate: SR, mFormatID: kAudioFormatLinearPCM,
        mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked, mBytesPerPacket: UInt32(4 * CH), mFramesPerPacket: 1,
        mBytesPerFrame: UInt32(4 * CH), mChannelsPerFrame: UInt32(CH), mBitsPerChannel: 32, mReserved: 0)
    CMAudioFormatDescriptionCreate(allocator: nil, asbd: &asbd, layoutSize: 0, layout: nil, magicCookieSize: 0, magicCookie: nil, extensions: nil, formatDescriptionOut: &fmt)
    var aPos = 0; let chunk = 4096
    func nextAudio() -> CMSampleBuffer? {
        guard aPos < frames else { return nil }
        let n = min(chunk, frames - aPos); let bytes = n * CH * 4
        var bb: CMBlockBuffer?
        CMBlockBufferCreateWithMemoryBlock(allocator: nil, memoryBlock: nil, blockLength: bytes, blockAllocator: nil, customBlockSource: nil,
                                           offsetToData: 0, dataLength: bytes, flags: 0, blockBufferOut: &bb)
        x.withUnsafeBytes { CMBlockBufferReplaceDataBytes(with: $0.baseAddress! + aPos * CH * 4, blockBuffer: bb!, offsetIntoDestination: 0, dataLength: bytes) }
        var sb: CMSampleBuffer?
        CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: nil, dataBuffer: bb!, formatDescription: fmt!, sampleCount: n,
            presentationTimeStamp: CMTime(value: CMTimeValue(aPos), timescale: CMTimeScale(SR)), packetDescriptions: nil, sampleBufferOut: &sb)
        aPos += n; return sb
    }
    let done = DispatchGroup(); done.enter(); done.enter()
    vin.requestMediaDataWhenReady(on: DispatchQueue(label: "v")) {
        while vin.isReadyForMoreMediaData { if let s = vo.copyNextSampleBuffer() { vin.append(s) } else { vin.markAsFinished(); done.leave(); return } }
    }
    ain.requestMediaDataWhenReady(on: DispatchQueue(label: "a")) {
        while ain.isReadyForMoreMediaData { if let s = nextAudio() { ain.append(s) } else { ain.markAsFinished(); done.leave(); return } }
    }
    done.wait()
    await w.finishWriting()
    if w.status != .completed { print("write failed: \(String(describing: w.error))"); exit(1) }
    print(String(format: "[normalize] speech %.1f dBFS -> gain +%.1f dB, ceiling %.1f dBFS -> %@", speech, db(gain), db(CEIL), OUT.lastPathComponent))
    sem.signal()
}
sem.wait()
